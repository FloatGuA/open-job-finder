"""上下文裁剪的测试。

这块逻辑是 DeepSeek 能不能撑住长程浏览器循环的关键（64k 上下文 vs 单张几十 KB
的 a11y 快照，DECISION.md 已把它列为本方向的已知风险）。agent 循环本身要真浏览器
+ 真 LLM 才跑得起来，所以裁剪逻辑被刻意抽成纯函数，好在这里单测到。
"""
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from multisite.agent_runtime import _STALE_TOOL_PLACEHOLDER, trim_stale_snapshots


def _tool(content, name="take_snapshot", call_id="c1"):
    return ToolMessage(content=content, name=name, tool_call_id=call_id)


class TestTrimStaleSnapshots:
    def test_keeps_only_the_most_recent_bulky_result(self):
        msgs = [
            HumanMessage(content="go"),
            _tool("SNAPSHOT-1", call_id="c1"),
            AIMessage(content="thinking"),
            _tool("SNAPSHOT-2", call_id="c2"),
            AIMessage(content="thinking more"),
            _tool("SNAPSHOT-3", call_id="c3"),
        ]

        out = trim_stale_snapshots(msgs)
        contents = [m.content for m in out]

        # 最后一张完整保留，之前的都换成占位。
        assert contents[-1] == "SNAPSHOT-3"
        assert contents[1] == _STALE_TOOL_PLACEHOLDER
        assert contents[3] == _STALE_TOOL_PLACEHOLDER

    def test_preserves_order_and_length(self):
        msgs = [
            HumanMessage(content="go"),
            _tool("S1", call_id="c1"),
            AIMessage(content="a"),
            _tool("S2", call_id="c2"),
        ]
        out = trim_stale_snapshots(msgs)
        # 消息条数和顺序不能变——LangGraph 依赖 tool_call_id 与 AIMessage 的
        # tool_calls 一一配对，少一条或换个位置都会让下一次模型调用直接报错。
        assert len(out) == len(msgs)
        assert isinstance(out[0], HumanMessage)
        assert isinstance(out[2], AIMessage)

    def test_preserves_tool_call_ids(self):
        msgs = [_tool("S1", call_id="call_abc"), _tool("S2", call_id="call_def")]
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
        msgs = [HumanMessage(content="go"), _tool("ONLY-SNAPSHOT", call_id="c1")]
        out = trim_stale_snapshots(msgs)
        assert out[1].content == "ONLY-SNAPSHOT"

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
