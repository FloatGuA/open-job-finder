"""阶段耗时要能到前端。

m1/m2 的三层视图里，第 2 层要显示每个站点花了多久——`find_jobs` 137 秒
vs `ensure_ready` 3.9 秒，这才看得出时间花在哪。`duration_ms` 一直在 JSONL 的
step 记录里，但没进 ProgressEvent 契约，所以前端拿不到。
"""
import json

from pipeline.run_logger import RunLogger
from services.progress_emitter import ProgressEvent, event_to_dict
from services.run_log_reader import parse_run_events


class FakeEmitter:
    def __init__(self):
        self.events = []
        self.stop_requested = False

    def emit(self, event):
        self.events.append(event)


class TestEventCarriesDuration:
    def test_event_to_dict_includes_duration(self):
        ev = ProgressEvent(workflow="m1", step="find_jobs", status="done",
                           message="m", duration_ms=137077)
        assert event_to_dict(ev)["duration_ms"] == 137077

    def test_duration_is_none_when_not_applicable(self):
        """agent 步、run_start 这些没有"耗时"这个概念，留 None 而不是 0——
        0 会被渲染成"花了 0 毫秒"，那是错的信息，不是缺失的信息。"""
        ev = ProgressEvent(workflow="m1", step="find_jobs", status="info", message="m")
        assert event_to_dict(ev)["duration_ms"] is None


class TestLogStepEmitsDuration:
    def test_sse_step_event_carries_duration(self, tmp_path, monkeypatch):
        import services.run_logger as srl
        monkeypatch.setattr(srl, "RUNS_DIR", tmp_path)
        emitter = FakeEmitter()
        logger = RunLogger(pipeline="m1", run_id="m1_dur", emitter=emitter, debug=True)
        logger.log_step("find_jobs", {}, "successful", 137077, data={"found": 15})

        sent = emitter.events[-1]
        assert sent.duration_ms == 137077
        assert sent.detail == {"found": 15}


class TestReplayCarriesDuration:
    def test_replayed_step_has_duration(self, tmp_path, monkeypatch):
        """回放和实时必须给出同一个字段集合——这是本项目反复踩的那类分叉。"""
        import services.run_logger as srl
        monkeypatch.setattr(srl, "RUNS_DIR", tmp_path)
        logger = RunLogger(pipeline="m1", run_id="m1_dur2", debug=True)
        logger.log_step("find_jobs", {}, "successful", 137077, data={"found": 15})
        logger.close("done", summary={"found": 15})

        events = parse_run_events(tmp_path / "m1_dur2.jsonl")
        assert all("duration_ms" in e for e in events)
        step = next(e for e in events if e["step"] == "find_jobs")
        assert step["duration_ms"] == 137077

    def test_agent_steps_replay_with_none_duration(self, tmp_path, monkeypatch):
        import services.run_logger as srl
        monkeypatch.setattr(srl, "RUNS_DIR", tmp_path)
        logger = RunLogger(pipeline="m1", run_id="m1_dur3", debug=True)
        logger.log_agent_step("find_jobs", {"kind": "think", "seq": 1, "text": "x", "calls": []})
        logger.close("done")

        events = parse_run_events(tmp_path / "m1_dur3.jsonl")
        agent = next(e for e in events if e.get("seq") is not None)
        assert agent["duration_ms"] is None

    def test_the_jsonl_still_holds_duration(self, tmp_path, monkeypatch):
        """回放读的是这一列，别在重构里把它从文件层丢掉。"""
        import services.run_logger as srl
        monkeypatch.setattr(srl, "RUNS_DIR", tmp_path)
        logger = RunLogger(pipeline="m1", run_id="m1_dur4", debug=True)
        logger.log_step("find_jobs", {}, "successful", 42, data={})
        logger.close("done")

        rows = [json.loads(x) for x in (tmp_path / "m1_dur4.jsonl").read_text(
            encoding="utf-8").splitlines() if x.strip()]
        step = next(r for r in rows if r.get("event") == "step")
        assert step["duration_ms"] == 42
