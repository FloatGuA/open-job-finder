"""同一个动作反复失败必须被叫停——agent 自己看不见循环。

2026-08-18 真机（m1 首次跑 join.qq.com）：agent 想勾「2027校园招聘」筛选项，
`click({"uid":"8_30"})` 返回 `Error: Failed to interact with the element ...`。
它于是重新截图、再点同一个 uid、再失败……**连续 29 次一模一样**，四分钟烧光步数，
`find_jobs` 只能报 partial、found=0。61 次工具调用里 59 次是废动作。

它并非没有意识：think 里明明写着 "Let me take a fresh snapshot to get current
uids"，然后照样点回旧 uid。**所以这不是提示不到位，是它看不见自己的循环模式**
——「这次调用和上次是不是同一个」是纯比对，不需要判断力，属于代码该管的事
（models judge / code decides）。

拦截返回文本而不抛异常，跟 `make_guarded_click` 同一个理由：agent 需要知道
"这条路堵死了、换个方式"，抛异常会把可恢复的局面变成整条 run 的硬失败。
"""
import asyncio

import pytest
from langchain_core.tools import StructuredTool

from multisite.safe_tools import make_repeat_failure_guard

ERROR_TEXT = ("Error: Failed to interact with the element with uid 8_30. "
              "The element did not become interactive within the configured timeout.")

# chrome-devtools-mcp 的错误是**当作正常内容返回的**（isError=False），形状是
# content block 列表——真机日志里记下来的就是这个。不是异常，所以只 try/except
# 抓不到它。
ERROR_BLOCKS = [{"type": "text", "text": ERROR_TEXT}]


def _make_tool(script, name="click"):
    """按脚本产出结果的真 BaseTool。列表里每项：要抛的异常，或要返回的值。

    用 `StructuredTool.from_function` 而不是手搓假对象，是为了让 `args_schema`
    真实存在——包装层能不能把它透传下去，正是要测的东西之一。
    """
    calls = []
    remaining = list(script)

    async def _fn(uid: str):
        calls.append(uid)
        out = remaining.pop(0) if remaining else "ok"
        if isinstance(out, Exception):
            raise out
        return out

    return StructuredTool.from_function(coroutine=_fn, name=name, description=name), calls


def _run(coro):
    return asyncio.run(coro)


class TestConsecutiveFailuresAreStopped:
    def test_third_identical_failing_call_is_not_executed(self):
        tool, calls = _make_tool([ERROR_BLOCKS] * 5)
        guarded = make_repeat_failure_guard(tool, limit=2)

        for _ in range(2):
            _run(guarded.ainvoke({"uid": "8_30"}))
        result = _run(guarded.ainvoke({"uid": "8_30"}))

        assert "BLOCKED" in str(result)
        # 关键断言是**底层没被调用**。只看返回值不够：先点了再回一句拦截文本，
        # 测试照样绿，而真机上那 29 次浪费一次都没省下来。
        assert calls == ["8_30", "8_30"]

    def test_the_block_message_repeats_the_last_error(self):
        """光说"被拦了"没用——agent 要知道为什么，才可能换对招。"""
        tool, _ = _make_tool([ERROR_BLOCKS] * 3)
        guarded = make_repeat_failure_guard(tool, limit=2)

        for _ in range(2):
            _run(guarded.ainvoke({"uid": "8_30"}))
        result = str(_run(guarded.ainvoke({"uid": "8_30"})))

        assert "did not become interactive" in result

    def test_a_success_clears_the_streak(self):
        """连续失败才是循环。失败一次、成功一次、再失败，不是循环，不该拦。"""
        tool, calls = _make_tool([ERROR_BLOCKS, "ok", ERROR_BLOCKS, "ok", ERROR_BLOCKS])
        guarded = make_repeat_failure_guard(tool, limit=2)

        for _ in range(5):
            _run(guarded.ainvoke({"uid": "8_30"}))

        assert len(calls) == 5

    def test_different_arguments_are_counted_separately(self):
        """换了 uid 就是换了招——那正是我们想逼它做的事，绝不能连坐。"""
        tool, calls = _make_tool([ERROR_BLOCKS] * 4)
        guarded = make_repeat_failure_guard(tool, limit=2)

        _run(guarded.ainvoke({"uid": "8_30"}))
        _run(guarded.ainvoke({"uid": "8_30"}))
        _run(guarded.ainvoke({"uid": "8_31"}))

        assert calls == ["8_30", "8_30", "8_31"]


class TestSuccessIsNeverBlocked:
    def test_identical_successful_calls_are_never_blocked(self):
        """真机那一轮里 `take_snapshot({})` 也被调了 30 次、参数完全相同，但它每次
        都成功。按「重复」拦会把 agent 的眼睛挖掉——比原来的循环严重得多。"""
        tool, calls = _make_tool(["ok"] * 10, name="take_snapshot")
        guarded = make_repeat_failure_guard(tool, limit=2)

        for _ in range(10):
            assert _run(guarded.ainvoke({"uid": "x"})) == "ok"

        assert len(calls) == 10

    def test_the_word_error_inside_page_content_is_not_a_failure(self):
        """快照/页面正文里出现 "Error" 是常事（404 页、报错文案）。把它当失败，
        会在一个完全正常的页面上把工具锁死。只认**开头**的 Error:。"""
        page = [{"type": "text", "text": "## Latest page snapshot\n"
                                         'uid=1_0 RootWebArea "Error 404 页面"\n'}]
        tool, calls = _make_tool([page] * 5, name="take_snapshot")
        guarded = make_repeat_failure_guard(tool, limit=2)

        for _ in range(5):
            _run(guarded.ainvoke({"uid": "x"}))

        assert len(calls) == 5


class TestExceptionsCountToo:
    def test_a_raised_exception_is_re_raised_not_swallowed(self):
        """包装层不处理异常，只数数。内部路径吞异常是本项目明令禁止的。"""
        tool, _ = _make_tool([RuntimeError("boom")])
        guarded = make_repeat_failure_guard(tool, limit=2)

        with pytest.raises(RuntimeError, match="boom"):
            _run(guarded.ainvoke({"uid": "8_30"}))

    def test_repeated_exceptions_also_trip_the_guard(self):
        """一直抛异常跟一直返回 Error 文本是同一种循环，不能只认后者。"""
        tool, calls = _make_tool([RuntimeError("boom")] * 5)
        guarded = make_repeat_failure_guard(tool, limit=2)

        for _ in range(2):
            with pytest.raises(RuntimeError):
                _run(guarded.ainvoke({"uid": "8_30"}))
        result = _run(guarded.ainvoke({"uid": "8_30"}))

        assert "BLOCKED" in str(result)
        assert calls == ["8_30", "8_30"]


class TestWrappedToolLooksTheSame:
    """对 agent 必须透明：名字和参数表变了，等于换了一套工具，prompt 全部作废。"""

    def test_name_is_preserved(self):
        tool, _ = _make_tool([], name="click")
        assert make_repeat_failure_guard(tool, limit=2).name == "click"

    def test_args_schema_is_preserved(self):
        tool, _ = _make_tool([], name="click")
        guarded = make_repeat_failure_guard(tool, limit=2)
        assert set(guarded.args) == set(tool.args)

    def test_arguments_actually_reach_the_inner_tool(self):
        """schema 对了但参数没透传，表现是"点击永远点在空 uid 上"——比换名字更难查。"""
        tool, calls = _make_tool(["ok"], name="click")
        guarded = make_repeat_failure_guard(tool, limit=2)

        _run(guarded.ainvoke({"uid": "8_30"}))

        assert calls == ["8_30"]


class TestGuardIsActuallyWiredIn:
    """写了守法不接上等于没写——而且不会有任何东西变红。

    跟 `tests/test_safe_tools.py::TestToolset` 同一个道理：那一组守的是"守法点击
    有没有真的接进工具集"，这一组守的是"防循环有没有真的接进工具集"。**逐个工具
    验**，不是只验 click：真机那轮里循环的是 click，但同样的死循环换成
    `navigate_page` 或 `wait_for` 一样会发生。
    """

    ALWAYS_FAILS = [{"type": "text", "text": ERROR_TEXT}]

    def _toolset(self):
        from multisite.layer1_agent import _PASSTHROUGH_OPEN_APPLICATION, build_agent_toolset

        calls = []

        # 签名写死一个具名参数，不用 `**kw`：langchain 会把 `**kw` 推成一个真的叫
        # `kw` 的必填 dict 字段，于是断言炸在 pydantic 校验上而不是在被测行为上。
        async def _fail(uid: str = ""):
            calls.append({"uid": uid})
            return self.ALWAYS_FAILS

        names = ["navigate_page", "take_snapshot", "click", "upload_file", "wait_for"]
        fakes = [StructuredTool.from_function(coroutine=_fail, name=n, description=n)
                 for n in names]

        async def _snap():
            calls.append({"tool": "take_snapshot"})
            return "Error: snapshot failed"

        toolset = build_agent_toolset(
            fakes,
            snapshot_provider=lambda: "",
            snapshot_taker=_snap,
            passthrough=_PASSTHROUGH_OPEN_APPLICATION,
        )
        return toolset, calls

    @pytest.mark.parametrize("tool_name",
                             ["click", "navigate_page", "wait_for", "take_snapshot"])
    def test_every_tool_stops_repeating_a_failing_call(self, tool_name):
        toolset, calls = self._toolset()
        tool = next(t for t in toolset if t.name == tool_name)
        # take_snapshot 是工具集自己建的（签名无参），其余都是上面那个假工具。
        args = {} if tool_name == "take_snapshot" else {"uid": "8_30"}

        results = [str(_run(tool.ainvoke(args))) for _ in range(3)]

        assert "BLOCKED" in results[-1], f"{tool_name} 没有被防循环包住"
        assert len(calls) == 2, f"{tool_name} 被拦下后底层仍被调用了"
