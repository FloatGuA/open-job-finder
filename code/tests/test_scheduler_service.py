"""SchedulerService: the scheduled entrypoints, tested directly.

While this lived inline in server.py it could only be reached through the HTTP
layer. Extracted with its cross-cutting deps injected, the two entrypoints
(_scheduled_run / _scheduled_selfcheck) are testable with fakes -- no APScheduler,
no app.state.
"""
import pytest

from services.scheduler_service import SchedulerService


def _service(**overrides):
    calls = {"enqueued": [], "selfcheck": [], "log": []}

    deps = dict(
        load_config=lambda: {
            "apply": {"params": {"max_cards": 5}},
            "check": {"params": {"max_conversations": 20}},
            "selfcheck": {"w1_max": 3, "w2_max": 7, "with_probes": False},
        },
        get_last_run_time=lambda wf: None,
        enqueue=lambda wf, params, source, coalesce: calls["enqueued"].append(
            {"wf": wf, "params": params, "source": source, "coalesce": coalesce}),
        rate_limited_today=lambda: False,
        run_selfcheck=lambda **kw: calls["selfcheck"].append(kw),
        write_schedule_log=lambda entry: calls["log"].append(entry),
    )
    deps.update(overrides)
    return SchedulerService(**deps), calls


# ---- scheduled apply / check --------------------------------------------------


def test_scheduled_apply_enqueues_w1_with_config_params():
    svc, calls = _service()
    svc._scheduled_run("apply")

    assert len(calls["enqueued"]) == 1
    item = calls["enqueued"][0]
    assert item["wf"] == "w1"
    assert item["params"] == {"max_cards": 5}
    assert item["source"] == "scheduled"
    assert item["coalesce"] is True  # a pending duplicate must not pile up


def test_scheduled_check_enqueues_w2():
    svc, calls = _service()
    svc._scheduled_run("check")
    assert calls["enqueued"][0]["wf"] == "w2"


def test_scheduled_apply_is_gated_by_the_daily_cap():
    """Once W1 hit the Boss cap today, a scheduled apply must be skipped and logged,
    not enqueued."""
    svc, calls = _service(rate_limited_today=lambda: True)
    svc._scheduled_run("apply")

    assert calls["enqueued"] == []
    assert len(calls["log"]) == 1
    entry = calls["log"][0]
    assert entry["result"] == "skipped"
    assert entry["workflow"] == "apply"


def test_scheduled_check_is_not_gated_by_the_cap():
    """W2 sends no greetings, so the daily cap does not apply to it."""
    svc, calls = _service(rate_limited_today=lambda: True)
    svc._scheduled_run("check")

    assert calls["enqueued"][0]["wf"] == "w2"
    assert calls["log"] == []


# ---- scheduled self-check -----------------------------------------------------


def test_scheduled_selfcheck_reads_live_config():
    svc, calls = _service()
    svc._scheduled_selfcheck()

    assert len(calls["selfcheck"]) == 1
    kw = calls["selfcheck"][0]
    assert kw["w1_max"] == 3
    assert kw["w2_max"] == 7
    assert kw["with_probes"] is False
    assert kw["trigger_type"] == "scheduler"


def test_selfcheck_falls_back_to_defaults_when_config_absent():
    svc, calls = _service(load_config=lambda: {})
    svc._scheduled_selfcheck()
    kw = calls["selfcheck"][0]
    assert kw["w1_max"] == 10 and kw["w2_max"] == 300 and kw["with_probes"] is True


# ---- config is read live, not cached at construction --------------------------


def test_config_is_read_at_trigger_time_not_construction():
    """A schedule edit must take effect on the next tick without a restart."""
    cfg = {"apply": {"params": {"max_cards": 1}}}
    svc, calls = _service(load_config=lambda: cfg)

    svc._scheduled_run("apply")
    cfg["apply"]["params"]["max_cards"] = 99   # user edits the schedule
    svc._scheduled_run("apply")

    assert calls["enqueued"][0]["params"]["max_cards"] == 1
    assert calls["enqueued"][1]["params"]["max_cards"] == 99
