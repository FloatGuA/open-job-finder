"""agent_step 事件：JSONL 落盘 + SSE 推送，两者形状由同一个函数产出。"""
import json

from pipeline.run_logger import RunLogger, agent_event
from services.progress_emitter import ProgressEvent, event_to_dict
from services.run_log_reader import parse_run_events

THINK = {"kind": "think", "seq": 13, "text": "先翻页",
         "calls": [{"id": "c1", "name": "click", "args": {"uid": "2_1"}}]}
OBSERVE = {"kind": "observe", "seq": 14, "call_id": "c1",
           "tool": "take_snapshot", "chars": 12431, "head": "uid=2_0 RootWebArea"}


class FakeEmitter:
    def __init__(self):
        self.events = []
        self.stop_requested = False

    def emit(self, event):
        self.events.append(event)


class TestEventToDict:
    def test_carries_every_field_including_seq(self):
        """SSE 的序列化原本在 server.py 里逐个字段手写——加一个字段就要记得
        改那里，忘了的表现是前端永远收不到它、而且不报错。收敛成一个函数。"""
        ev = ProgressEvent(workflow="m1", step="find_jobs", status="info",
                           message="x", tool=None, scope={}, detail={"a": 1},
                           seq=13, ts=1.0)
        assert event_to_dict(ev) == {
            "workflow": "m1", "step": "find_jobs", "tool": None, "status": "info",
            "message": "x", "scope": {}, "detail": {"a": 1}, "seq": 13, "ts": 1.0,
        }

    def test_seq_is_none_for_ordinary_events(self):
        ev = ProgressEvent(workflow="w1", step="scan", status="done", message="m")
        assert event_to_dict(ev)["seq"] is None


class TestAgentEvent:
    def test_think_event_shape(self):
        out = agent_event("m1", "find_jobs", THINK, ts=1.5)
        assert out["workflow"] == "m1" and out["step"] == "find_jobs"
        assert out["seq"] == 13 and out["status"] == "info"
        assert out["tool"] is None            # 「说」不是工具调用
        assert out["detail"] == THINK          # 完整 record 原样带上
        assert out["ts"] == 1.5

    def test_observe_event_carries_the_tool_name(self):
        out = agent_event("m1", "find_jobs", OBSERVE, ts=2.0)
        assert out["tool"] == "take_snapshot"
        assert out["detail"] == OBSERVE


class TestLogAgentStep:
    def test_writes_one_jsonl_line_with_the_record_nested(self, tmp_path, monkeypatch):
        import services.run_logger as srl
        monkeypatch.setattr(srl, "RUNS_DIR", tmp_path)
        logger = RunLogger(pipeline="m1", run_id="m1_test", debug=True)
        logger.log_agent_step("find_jobs", THINK)
        logger.close("done")

        lines = [json.loads(x) for x in (tmp_path / "m1_test.jsonl").read_text(
            encoding="utf-8").splitlines() if x.strip()]
        rec = next(x for x in lines if x["event"] == "agent_step")
        assert rec["step"] == "find_jobs"
        assert rec["record"] == THINK      # 整体嵌一层，不摊平

    def test_emits_sse_when_debug(self, tmp_path, monkeypatch):
        import services.run_logger as srl
        monkeypatch.setattr(srl, "RUNS_DIR", tmp_path)
        emitter = FakeEmitter()
        logger = RunLogger(pipeline="m1", run_id="m1_test2", emitter=emitter, debug=True)
        logger.log_agent_step("find_jobs", THINK)

        sent = [e for e in emitter.events if e.seq is not None]
        assert len(sent) == 1
        assert sent[0].workflow == "m1" and sent[0].detail == THINK


class TestReplayMatchesLive:
    """同一条 record 有两条路到达同一个前端组件：实时 SSE 和事后回放。
    两边各写一套格式化必然分叉，所以这里直接把两条路的产出摆在一起比。"""

    def test_replay_and_sse_produce_the_same_event(self, tmp_path, monkeypatch):
        import services.run_logger as srl
        monkeypatch.setattr(srl, "RUNS_DIR", tmp_path)
        emitter = FakeEmitter()
        logger = RunLogger(pipeline="m1", run_id="m1_same", emitter=emitter, debug=True)
        logger.log_agent_step("find_jobs", THINK)
        logger.close("done")

        live = event_to_dict(next(e for e in emitter.events if e.seq is not None))
        replayed = next(e for e in parse_run_events(tmp_path / "m1_same.jsonl")
                        if e.get("seq") is not None)

        assert {**live, "ts": 0} == {**replayed, "ts": 0}

    def test_observe_events_replay_too(self, tmp_path, monkeypatch):
        import services.run_logger as srl
        monkeypatch.setattr(srl, "RUNS_DIR", tmp_path)
        logger = RunLogger(pipeline="m1", run_id="m1_obs", debug=True)
        logger.log_agent_step("find_jobs", OBSERVE)
        logger.close("done")

        got = next(e for e in parse_run_events(tmp_path / "m1_obs.jsonl")
                   if e.get("seq") is not None)
        assert got["tool"] == "take_snapshot" and got["detail"] == OBSERVE


class TestReplaySeqDefault:
    """parse_run_events 的五个非 agent 分支（run_start/run_end/step/tool/业务事件）原本
    都没有 "seq" 键，而 agent_step 分支有——这是本次改动新引入的字段集合分叉。前端一旦
    写 `event.seq !== null` 就会误判（JS 里 undefined !== null 为真）。"""

    def test_every_replayed_event_has_seq_key_and_non_agent_is_none(self, tmp_path, monkeypatch):
        import services.run_logger as srl
        monkeypatch.setattr(srl, "RUNS_DIR", tmp_path)
        logger = RunLogger(pipeline="m1", run_id="m1_seq", debug=True)
        logger.log("job_scored", {}, {"score": 1})
        logger.log_step("find_jobs", {}, "successful", 10, {})
        logger.log_tool("find_jobs", "search", {}, "successful", 5, {})
        logger.log_agent_step("find_jobs", THINK)
        logger.close("done")

        events = parse_run_events(tmp_path / "m1_seq.jsonl")
        assert events
        for ev in events:
            assert "seq" in ev

        non_agent = [e for e in events if e.get("seq") is None]
        agent = [e for e in events if e.get("seq") is not None]
        # run_start / job_scored / step / tool / run_end = 5 个非 agent 事件
        assert len(non_agent) == 5
        assert len(agent) == 1
        assert agent[0]["detail"] == THINK
