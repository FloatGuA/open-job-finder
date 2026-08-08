"""Minimum verification tests for RunLogger and ToolRegistry (Task 031)."""
import json

import pytest

import services.run_logger as _run_logger_mod
from services.run_logger import RunLogger, reconcile_orphaned_runs
from tools.base import BaseTool, ToolResult
from tools.registry import ToolRegistry


# ── RunLogger ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _redirect_runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(_run_logger_mod, "RUNS_DIR", tmp_path / "runs")


def test_run_logger_creates_jsonl_on_log_tool(tmp_path, monkeypatch):
    monkeypatch.setattr(_run_logger_mod, "RUNS_DIR", tmp_path / "runs")
    rl = RunLogger(run_id="w1_20260101_0900", pipeline="w1")
    rl.log_tool(
        step="fetch_jd",
        tool="read_panel_jd",
        scope={"job_id": "abc123"},
        status="successful",
        duration_ms=350,
        data={"salary_raw": "25k-40k"},
    )

    runs_dir = tmp_path / "runs"
    files = list(runs_dir.glob("w1_20260101_0900.jsonl"))
    assert len(files) == 1


def test_run_logger_tool_entry_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(_run_logger_mod, "RUNS_DIR", tmp_path / "runs")
    rl = RunLogger(run_id="w1_20260101_0901", pipeline="w1")
    rl.log_tool(
        step="fetch_jd",
        tool="read_panel_jd",
        scope={"job_id": "abc123"},
        status="successful",
        duration_ms=350,
        data={"salary_raw": "25k-40k"},
    )

    runs_dir = tmp_path / "runs"
    line = (runs_dir / "w1_20260101_0901.jsonl").read_text(encoding="utf-8").splitlines()[0]
    entry = json.loads(line)

    assert entry["event"] == "tool"
    assert entry["run_id"] == "w1_20260101_0901"
    assert entry["tool"] == "read_panel_jd"
    assert entry["status"] == "successful"
    assert "ts" in entry


def test_run_logger_run_start_end(tmp_path, monkeypatch):
    monkeypatch.setattr(_run_logger_mod, "RUNS_DIR", tmp_path / "runs")
    rl = RunLogger(run_id="w1_20260101_0902", pipeline="w1")
    rl.log_run_start()
    rl.log_run_end(status="successful", summary={"applied": 3})

    lines = (tmp_path / "runs" / "w1_20260101_0902.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(l) for l in lines]
    assert events[0]["event"] == "run_start"
    assert events[0]["pipeline"] == "w1"
    assert events[-1]["event"] == "run_end"
    assert events[-1]["status"] == "successful"
    assert events[-1]["summary"] == {"applied": 3}


def test_run_logger_business_event_has_no_status_or_duration(tmp_path, monkeypatch):
    monkeypatch.setattr(_run_logger_mod, "RUNS_DIR", tmp_path / "runs")
    rl = RunLogger(run_id="w1_20260101_0903", pipeline="w1")
    rl.log_business_event(
        event="job_scored",
        scope={"job_id": "abc123"},
        data={"score": 78, "above_threshold": True},
    )

    line = (tmp_path / "runs" / "w1_20260101_0903.jsonl").read_text(encoding="utf-8").splitlines()[0]
    entry = json.loads(line)
    assert entry["event"] == "job_scored"
    assert "status" not in entry
    assert "duration_ms" not in entry


def test_reconcile_orphaned_runs_closes_dangling_run(tmp_path, monkeypatch):
    monkeypatch.setattr(_run_logger_mod, "RUNS_DIR", tmp_path / "runs")
    rl = RunLogger(run_id="w2_20260101_0904", pipeline="w2")
    rl.log_run_start()
    rl.log_tool(step="scan", tool="extract_conversation_list", scope={}, status="successful",
                duration_ms=100, data={})
    # simulate a hard kill: no log_run_end / close() call

    reconciled = reconcile_orphaned_runs()
    assert reconciled == ["w2_20260101_0904"]

    lines = (tmp_path / "runs" / "w2_20260101_0904.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(l) for l in lines]
    assert events[-1]["event"] == "run_end"
    assert events[-1]["status"] == "failed"
    assert "orphaned" in events[-1]["summary"]["reason"]


def test_reconcile_orphaned_runs_leaves_finished_run_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(_run_logger_mod, "RUNS_DIR", tmp_path / "runs")
    rl = RunLogger(run_id="w1_20260101_0905", pipeline="w1")
    rl.log_run_start()
    rl.log_run_end(status="successful", summary={"applied": 1})

    assert reconcile_orphaned_runs() == []
    lines = (tmp_path / "runs" / "w1_20260101_0905.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # unchanged: run_start + the original run_end only


def test_reconcile_orphaned_runs_no_runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(_run_logger_mod, "RUNS_DIR", tmp_path / "does_not_exist")
    assert reconcile_orphaned_runs() == []


# ── ToolRegistry ──────────────────────────────────────────────────────────────

class _MockTool(BaseTool):
    name = "mock_tool"
    description = "A mock tool for testing."
    input_schema = {"type": "object", "properties": {}}

    def execute(self, **kwargs) -> ToolResult:
        return ToolResult(ok=True, data={"called": True})


def test_tool_registry_call_returns_tool_result():
    registry = ToolRegistry()
    registry.register(_MockTool())
    result = registry.call("mock_tool")
    assert isinstance(result, ToolResult)
    assert result.ok is True


def test_tool_registry_list_tools():
    registry = ToolRegistry()
    registry.register(_MockTool())
    assert "mock_tool" in registry.list_tools()


def test_tool_registry_get_unknown_raises_key_error():
    registry = ToolRegistry()
    with pytest.raises(KeyError):
        registry.get("nonexistent")


def test_tool_registry_holds_shared_resources():
    sentinel = object()
    registry = ToolRegistry(browser=sentinel)
    assert registry.browser is sentinel


class _RaisingTool(BaseTool):
    name = "boom"
    description = "always raises (fail-fast tool, e.g. a DB read)"
    input_schema = {"type": "object", "properties": {}}

    def execute(self, **kwargs) -> ToolResult:
        raise RuntimeError("db read exploded")


class _CapturingLogger:
    def __init__(self):
        self.tool_calls = []
        self.step_running = []

    def log_tool(self, **kwargs):
        self.tool_calls.append(kwargs)

    def emit_step_running(self, step, scope):
        self.step_running.append((step, scope))


def test_registry_call_logs_then_reraises_on_exception():
    """A fail-fast tool that raises must still be recorded in the tool trace
    (status=failed) before the exception propagates -- never swallowed."""
    logger = _CapturingLogger()
    registry = ToolRegistry(logger=logger)
    registry.register(_RaisingTool())
    registry.set_context("scan", {"conv_id": "abc"})

    with pytest.raises(RuntimeError, match="db read exploded"):
        registry.call("boom")

    assert len(logger.tool_calls) == 1
    logged = logger.tool_calls[0]
    assert logged["tool"] == "boom"
    assert logged["status"] == "failed"
    assert logged["step"] == "scan"
    assert logged["scope"] == {"conv_id": "abc"}
    assert "db read exploded" in logged["error"]


def test_registry_call_without_logger_still_reraises():
    """No logger configured -> the exception must still propagate, not be masked."""
    registry = ToolRegistry(logger=None)
    registry.register(_RaisingTool())
    with pytest.raises(RuntimeError, match="db read exploded"):
        registry.call("boom")
