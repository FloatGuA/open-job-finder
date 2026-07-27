"""OrchestrationService: workflow execution, tested directly.

While this lived inline in server.py it could only be reached through the HTTP
layer or a real queue run. Extracted with a state accessor + injected log writers,
the queue runner, the daily-cap gate and the self-check cycle are testable with
fakes -- no browser, no real W1/W2.

The three W1/W2/W3 runners are NOT unit-tested here (they only assemble kwargs and
call run_w1/run_w2/run_w3, which have their own tests); what matters is the
orchestration around them: dispatch, error handling, the cap gate, enqueueing.
"""
import types

import pytest

from services.workflow_orchestration import OrchestrationService


class _Emitter:
    def __init__(self):
        self.current_workflow = None
        self.finished = []

    def finish_workflow(self, workflow, summary, status="done"):
        self.finished.append({"workflow": workflow, "summary": summary, "status": status})


class _Queue:
    def __init__(self):
        self.enqueued = []

    def enqueue(self, wf, params, source, coalesce=False):
        item = types.SimpleNamespace(id=f"{wf}-{len(self.enqueued)}",
                                     workflow=wf, params=params, source=source)
        self.enqueued.append(item)
        return item


class _State:
    def __init__(self):
        self.config = {}
        self.tracker = object()
        self.model_router = object()
        self.emitter = _Emitter()
        self.workflow_queue = _Queue()
        self.smoke_summaries = {}
        self.rate_limited_date = None


def _service(state=None, **overrides):
    state = state or _State()
    logs = {"schedule": [], "selfcheck": []}
    deps = dict(
        get_state=lambda: state,
        ensure_state=lambda: None,
        data_dir="/tmp/x",
        write_schedule_log=lambda e: logs["schedule"].append(e),
        write_selfcheck_log=lambda e: logs["selfcheck"].append(e),
        smoke_log_path="/tmp/smoke.jsonl",
    )
    deps.update(overrides)
    return OrchestrationService(**deps), state, logs


class _Item:
    def __init__(self, workflow, source="manual", params=None, id="i1"):
        self.workflow = workflow
        self.source = source
        self.params = params or {}
        self.id = id


# ---- run_item: dispatch + mutex + logging -------------------------------------


def test_run_item_dispatches_by_workflow_and_logs_success(monkeypatch):
    svc, state, logs = _service()
    seen = []
    monkeypatch.setattr(svc, "_run_apply_workflow", lambda p: (seen.append(p), ("apply ok", {"applied": 1}))[1])

    svc.run_item(_Item("w1"))

    assert seen and seen[0]["_trigger"] == "manual"
    # run_item's finally now GUARANTEES the mutex is released, even when the runner
    # returns without calling finish_workflow (the bug that once wedged the queue).
    assert state.emitter.current_workflow is None
    assert logs["schedule"][0]["result"] == "success"
    assert logs["schedule"][0]["workflow"] == "apply"


def test_run_item_records_error_and_reraises(monkeypatch):
    """On failure the runner clears the mutex (via finish_workflow), logs an error
    entry, and re-raises so the queue records the failure."""
    svc, state, logs = _service()
    monkeypatch.setattr(svc, "_run_check_workflow",
                        lambda p: (_ for _ in ()).throw(RuntimeError("browser died")))

    with pytest.raises(RuntimeError, match="browser died"):
        svc.run_item(_Item("w2"))

    assert logs["schedule"][0]["result"] == "error"
    assert "browser died" in logs["schedule"][0]["summary"]
    assert state.emitter.finished[-1]["status"] == "error"


def test_smoke_summary_is_stashed_for_the_waiter(monkeypatch):
    """A smoke-sourced item's raw counters are stored on app.state for
    submit_and_wait to pick up."""
    svc, state, logs = _service()
    monkeypatch.setattr(svc, "_run_apply_workflow", lambda p: ("ok", {"applied": 3}))

    svc.run_item(_Item("w1", source="smoke_live", id="abc"))

    assert state.smoke_summaries["abc"] == {"applied": 3}


def test_smoke_summaries_are_bounded(monkeypatch):
    svc, state, logs = _service()
    monkeypatch.setattr(svc, "_run_apply_workflow", lambda p: ("ok", {}))
    for i in range(60):
        svc.run_item(_Item("w1", source="smoke", id=f"x{i}"))
    assert len(state.smoke_summaries) <= 50


def test_trigger_is_mapped_from_source(monkeypatch):
    """run_diagnostics finds the smoke's own runs by trigger, so smoke_live must
    reach the runner as _trigger=smoke_live, not 'manual'."""
    svc, state, logs = _service()
    seen = []
    monkeypatch.setattr(svc, "_run_apply_workflow", lambda p: (seen.append(p["_trigger"]), ("ok", {}))[1])
    svc.run_item(_Item("w1", source="smoke_live"))
    assert seen[0] == "smoke_live"


# ---- daily-cap state ----------------------------------------------------------


def test_rate_limit_marks_and_reads_back():
    svc, state, _ = _service()
    assert svc.is_rate_limited_today() is False
    svc.mark_rate_limited_today()
    assert svc.is_rate_limited_today() is True
    assert state.rate_limited_date == OrchestrationService.china_today()


# ---- self-check cycle ---------------------------------------------------------


def test_selfcheck_enqueues_w1_and_w2_when_probes_skipped():
    svc, state, logs = _service()
    entry = svc.run_selfcheck_cycle(w1_max=3, w2_max=7, with_probes=False, trigger_type="manual")

    assert entry["ok"] is True
    kinds = [(it.workflow, it.source) for it in state.workflow_queue.enqueued]
    assert ("w1", "selfcheck") in kinds and ("w2", "selfcheck") in kinds
    assert logs["selfcheck"][0]["ok"] is True


def test_selfcheck_is_skipped_at_the_daily_cap():
    svc, state, logs = _service()
    svc.mark_rate_limited_today()
    entry = svc.run_selfcheck_cycle(w1_max=3, w2_max=7, with_probes=False, trigger_type="manual")

    assert entry["ok"] is True
    assert "上限" in entry["skipped_reason"]
    assert state.workflow_queue.enqueued == []  # nothing enqueued when capped


def test_selfcheck_skips_probes_when_browser_busy():
    svc, state, logs = _service()
    state.emitter.current_workflow = "w1"  # something owns the browser
    entry = svc.run_selfcheck_cycle(w1_max=1, w2_max=1, with_probes=True, trigger_type="scheduler")

    # Probes skipped, but W1/W2 still enqueued behind the running work.
    assert any(s["stage"] == "probes" and "跳过" in s["detail"] for s in entry["stages"])
    assert len(state.workflow_queue.enqueued) == 2


# ---- submit_and_wait (smoke's queue hook) -------------------------------------


def test_submit_and_wait_pops_trigger_into_source():
    svc, state, _ = _service()
    # Make the item look done immediately so the wait loop returns.
    q = state.workflow_queue
    orig_enqueue = q.enqueue

    def enqueue(wf, params, source, coalesce=False):
        item = orig_enqueue(wf, params, source=source, coalesce=coalesce)
        state.smoke_summaries[item.id] = {"applied": 1}
        q.snapshot = lambda: {"recent": [{"id": item.id, "status": "done"}],
                              "pending": [], "current": None}
        return item

    q.enqueue = enqueue
    result = svc.submit_and_wait("w1", {"max_cards": 2, "trigger": "smoke_live"})

    assert result == {"applied": 1}
    assert state.workflow_queue.enqueued[0].source == "smoke_live"
    assert "trigger" not in state.workflow_queue.enqueued[0].params
