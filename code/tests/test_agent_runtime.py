"""上下文裁剪的测试。

这块逻辑是 DeepSeek 能不能撑住长程浏览器循环的关键（64k 上下文 vs 单张几十 KB
的 a11y 快照，DECISION.md 已把它列为本方向的已知风险）。agent 循环本身要真浏览器
+ 真 LLM 才跑得起来，所以裁剪逻辑被刻意抽成纯函数，好在这里单测到。
"""
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from multisite.agent_runtime import _STALE_TOOL_PLACEHOLDER, trim_stale_snapshots


def _tool(content, name="take_snapshot", call_id="c1"):
    return ToolMessage(content=content, name=name, tool_call_id=call_id)


def _big(tag: str) -> str:
    """一张够大的假快照。

    **不能再用 `"SNAPSHOT-1"` 这种十来个字符的桩**：裁剪的判据是输出大小
    （真机快照 6613 字符 vs 点击返回 114/206），拿十个字符当快照会让这组测试
    在一个真实世界里不存在的输入上做断言——2026-08-19 那个把 `click` 结果整个
    删掉的 bug 就是这么躲过它们的。
    """
    line = 'uid=1_9 StaticText "x"' + chr(10)
    return "## " + tag + chr(10) + line * 200


class TestTrimStaleSnapshots:
    def test_keeps_only_the_most_recent_bulky_result(self):
        msgs = [
            HumanMessage(content="go"),
            _tool(_big("SNAPSHOT-1"), call_id="c1"),
            AIMessage(content="thinking"),
            _tool(_big("SNAPSHOT-2"), call_id="c2"),
            AIMessage(content="thinking more"),
            _tool(_big("SNAPSHOT-3"), call_id="c3"),
        ]

        out = trim_stale_snapshots(msgs)
        contents = [m.content for m in out]

        # 最后一张完整保留，之前的都换成占位。
        assert contents[-1] == _big("SNAPSHOT-3")
        assert contents[1] == _STALE_TOOL_PLACEHOLDER
        assert contents[3] == _STALE_TOOL_PLACEHOLDER

    def test_preserves_order_and_length(self):
        msgs = [
            HumanMessage(content="go"),
            _tool(_big("S1"), call_id="c1"),
            AIMessage(content="a"),
            _tool(_big("S2"), call_id="c2"),
        ]
        out = trim_stale_snapshots(msgs)
        # 消息条数和顺序不能变——LangGraph 依赖 tool_call_id 与 AIMessage 的
        # tool_calls 一一配对，少一条或换个位置都会让下一次模型调用直接报错。
        assert len(out) == len(msgs)
        assert isinstance(out[0], HumanMessage)
        assert isinstance(out[2], AIMessage)

    def test_preserves_tool_call_ids(self):
        msgs = [_tool(_big("S1"), call_id="call_abc"), _tool(_big("S2"), call_id="call_def")]
        out = trim_stale_snapshots(msgs)
        assert [m.tool_call_id for m in out] == ["call_abc", "call_def"]

    def test_does_not_trim_non_bulky_tools(self):
        # fill/其他工具的返回值本来就短，砍它们没有收益，反而丢信息。
        msgs = [
            _tool("filled ok", name="fill", call_id="c1"),
            _tool("filled ok too", name="fill", call_id="c2"),
        ]
        out = trim_stale_snapshots(msgs)
        assert [m.content for m in out] == ["filled ok", "filled ok too"]

    def test_single_snapshot_is_untouched(self):
        msgs = [HumanMessage(content="go"), _tool(_big("ONLY"), call_id="c1")]
        out = trim_stale_snapshots(msgs)
        assert out[1].content == _big("ONLY")

    def test_empty_input(self):
        assert trim_stale_snapshots([]) == []


class TestHitStepLimit:
    """区分“干完了”和“没干完”。

    LangGraph 的 create_react_agent 在步数耗尽时**不抛异常**，只往 messages
    里塞一句固定文案就正常返回。两种结局的 state 长得一模一样，所以
    不检测的话，“扫完所有桶”和“扫到一半断了”在日志里无法区分——
    2026-08-14 第四次真机跑就是这么把一次半途而废读成了主动收尾。
    """

    @staticmethod
    def _state(*contents):
        from langchain_core.messages import AIMessage
        return {"messages": [AIMessage(content=c) for c in contents]}

    def test_detects_the_sentinel(self):
        from multisite.agent_runtime import hit_step_limit
        assert hit_step_limit(self._state("Sorry, need more steps to process this request."))

    def test_normal_finish_is_not_a_step_limit(self):
        from multisite.agent_runtime import hit_step_limit
        assert not hit_step_limit(self._state("找完了，共记录 5 个。"))

    def test_only_the_last_ai_message_counts(self):
        """早期消息里碰巧出现这句话（比如 agent 引用了它）不算——
        真正的信号总是最后一条。"""
        from multisite.agent_runtime import hit_step_limit
        assert not hit_step_limit(
            self._state("Sorry, need more steps to process this request.", "搞定了。"))

    def test_empty_state_is_not_a_step_limit(self):
        from multisite.agent_runtime import hit_step_limit
        assert not hit_step_limit({"messages": []})
        assert not hit_step_limit({})

    def test_tool_messages_do_not_confuse_it(self):
        from langchain_core.messages import AIMessage, ToolMessage
        from multisite.agent_runtime import hit_step_limit
        state = {"messages": [
            AIMessage(content="Sorry, need more steps to process this request."),
            ToolMessage(content="x", tool_call_id="t", name="take_snapshot"),
        ]}
        assert hit_step_limit(state), "最后一条 AI 消息才是信号源"


class TestShortToolResultsSurviveTrimming:
    """**裁剪不能把反馈删掉。**

    2026-08-19 真机（join.qq.com，三轮 found=0）的真正根因就在这里：`click` 被算进
    `_BULKY_TOOLS`，而 `kept_recent` 是一个全局开关——只留**最近的那一条** bulky 消息。
    agent 的实际序列是「点击 → 截图 → 点击 → 截图」，做决定时最近的 bulky 消息永远是
    那张快照，**于是每一条点击结果都被换成了占位符**。

    模型因此从来没看见过 `Error: ... did not become interactive`，也从来没看见过
    `BLOCKED: 你已经用同样的参数失败 2 次`。每一轮它醒来只有一张全新快照和一堆
    「较早的快照，页面已变化」——**从它的视角，它从来没试过点那个元素**，于是重新
    推导、重新得出同一个结论、再点一次。循环完全合理。

    占位符那句「页面此后已经变化」还在主动误导：页面一字未变，它被连着骗了 28 次。

    判据不该是「出自哪个工具」，而是「**这段输出是不是很大**」——大的是过时的页面
    描述，砍掉有收益；小的是状态与错误，砍掉就是删证据。`click` 的返回真机实测
    114（成功）/ 206（失败）字符，快照 6613，两者根本不是一回事。
    """

    CLICK_ERROR = ("Error: Failed to interact with the element with uid 8_30. "
                   "The element did not become interactive within the configured timeout.")
    BLOCKED = ("BLOCKED: 你已经用完全相同的参数调用 click 失败 2 次，这次没有执行。"
               "不要再用这组参数重试——重复同一个动作不会有不同结果。")
    BIG_SNAPSHOT = "## Latest page snapshot\n" + ("uid=1_9 StaticText \"x\"\n" * 500)

    def _sequence(self, click_payload):
        """真机那一轮的形状：点击失败 → 重新截图 → 又点击 → 又截图。"""
        return [
            HumanMessage(content="go"),
            _tool(click_payload, name="click", call_id="c1"),
            _tool(self.BIG_SNAPSHOT, name="take_snapshot", call_id="c2"),
            _tool(click_payload, name="click", call_id="c3"),
            _tool(self.BIG_SNAPSHOT, name="take_snapshot", call_id="c4"),
        ]

    def test_the_click_error_reaches_the_model(self):
        out = trim_stale_snapshots(self._sequence(self.CLICK_ERROR))
        kept = [m.content for m in out if m.content == self.CLICK_ERROR]
        assert len(kept) == 2, "点击失败的原文被裁掉了——模型不知道自己点失败过"

    def test_the_block_message_reaches_the_model(self):
        out = trim_stale_snapshots(self._sequence(self.BLOCKED))
        kept = [m.content for m in out if m.content == self.BLOCKED]
        assert len(kept) == 2, "拦截提示被裁掉了——防循环等于没做"

    def test_stale_big_snapshots_are_still_replaced(self):
        """别为了保住小消息把裁剪整个关掉——大快照该砍还得砍。"""
        out = trim_stale_snapshots(self._sequence(self.CLICK_ERROR))
        snaps = [m.content for m in out if m.name == "take_snapshot"]
        assert snaps[0] == _STALE_TOOL_PLACEHOLDER
        assert snaps[1] == self.BIG_SNAPSHOT

    def test_a_genuinely_huge_click_result_is_still_trimmed(self):
        """判据是大小不是工具名：万一某个站的 click 真的回一大坨，照砍。"""
        huge = "X" * 9000
        msgs = [_tool(huge, name="click", call_id="c1"),
                _tool(huge, name="click", call_id="c2")]
        out = trim_stale_snapshots(msgs)
        assert out[0].content == _STALE_TOOL_PLACEHOLDER
        assert out[1].content == huge
