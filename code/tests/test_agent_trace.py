"""agent 每一轮的解读：stdout 追踪和 run 日志共用同一份。

分成两份的话，"日志里说的"和"终端里说的"会慢慢变成两回事，而那种漂移
没有任何东西会发现。
"""
import asyncio

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from multisite.agent_runtime import describe_message, format_record, run_agent


class TestDescribeMessage:
    def test_thinking_with_tool_calls(self):
        msg = AIMessage(
            content="列表里看到 20 个岗位，先处理前 5 个",
            tool_calls=[{"id": "call_1", "name": "record_job",
                         "args": {"title": "后端开发实习生"}}],
        )
        assert describe_message(msg, 13) == {
            "kind": "think", "seq": 13,
            "text": "列表里看到 20 个岗位，先处理前 5 个",
            "calls": [{"id": "call_1", "name": "record_job",
                       "args": {"title": "后端开发实习生"}}],
        }

    def test_tool_call_without_text(self):
        msg = AIMessage(content="", tool_calls=[
            {"id": "c", "name": "take_snapshot", "args": {}}])
        out = describe_message(msg, 4)
        assert out["kind"] == "think" and out["text"] == ""
        assert out["calls"][0]["name"] == "take_snapshot"

    def test_long_args_are_truncated(self):
        msg = AIMessage(content="", tool_calls=[
            {"id": "c", "name": "fill", "args": {"value": "x" * 500}}])
        assert len(describe_message(msg, 1)["calls"][0]["args"]["value"]) == 120

    def test_tool_result(self):
        msg = ToolMessage(content='uid=2_0 RootWebArea "招聘"\nuid=2_1 link',
                          tool_call_id="call_1", name="take_snapshot")
        assert describe_message(msg, 14) == {
            "kind": "observe", "seq": 14, "call_id": "call_1",
            "tool": "take_snapshot", "chars": 37,
            "head": 'uid=2_0 RootWebArea "招聘"',
        }

    def test_empty_ai_message_is_dropped(self):
        """既没说话也没调工具的一轮不该占一行。"""
        assert describe_message(AIMessage(content=""), 2) is None

    def test_non_agent_message_is_dropped(self):
        assert describe_message(HumanMessage(content="开始"), 0) is None


class TestFormatRecord:
    def test_think_renders_calls_then_text(self):
        record = {"kind": "think", "seq": 7, "text": "先翻页",
                  "calls": [{"id": "c", "name": "click", "args": {"uid": "2_1"}}]}
        lines = format_record(record)
        assert lines == ["  [07] -> click({'uid': '2_1'})", "  [07] 说: 先翻页"]

    def test_observe_renders_one_line(self):
        record = {"kind": "observe", "seq": 8, "call_id": "c",
                  "tool": "take_snapshot", "chars": 12431, "head": "uid=2_0"}
        assert format_record(record) == ["  [08] <- take_snapshot: 12431 字符 | uid=2_0"]


class FakeAgent:
    """按 stream_mode="values" 的形状吐 chunk：每个 chunk 是完整的 messages 快照，
    后一个包含前一个（这正是 run_agent 只处理新增部分的原因）。"""

    def __init__(self, batches):
        self._batches = batches

    async def astream(self, payload, config=None, stream_mode=None):
        for msgs in self._batches:
            yield {"messages": msgs}


class TestRunAgentOnStep:
    def _run(self, agent, **kw):
        return asyncio.run(run_agent(agent, "go", trace=False, **kw))

    def test_calls_on_step_once_per_new_message(self):
        a = AIMessage(content="", tool_calls=[{"id": "c1", "name": "take_snapshot", "args": {}}])
        t = ToolMessage(content="uid=1", tool_call_id="c1", name="take_snapshot")
        b = AIMessage(content="找到了", tool_calls=[])
        seen = []
        self._run(FakeAgent([[a], [a, t], [a, t, b]]), on_step=seen.append)

        assert [r["kind"] for r in seen] == ["think", "observe", "think"]
        assert [r["seq"] for r in seen] == [0, 1, 2]

    def test_returns_the_final_state(self):
        b = AIMessage(content="done", tool_calls=[])
        final = self._run(FakeAgent([[b]]), on_step=lambda r: None)
        assert final["messages"][-1].content == "done"

    def test_dropped_messages_do_not_reach_on_step_but_still_advance_seq(self):
        """空消息不占一行，但序号必须继续走——否则序号跟消息下标对不上。"""
        empty = AIMessage(content="")
        b = AIMessage(content="真正说了话", tool_calls=[])
        seen = []
        self._run(FakeAgent([[empty], [empty, b]]), on_step=seen.append)

        assert len(seen) == 1
        assert seen[0]["seq"] == 1
