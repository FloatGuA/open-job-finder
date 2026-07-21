"""Layer-3 smoke runner tests: the LIVE-mode assertions that an outbound action
actually PERSISTED (W1 apply -> count_today grows; W2 resume send -> hr_messages
grows). These are the checks that would have caught the historical "applied but
never stored" bug, so they matter more than the dry-run path.

run_w1 / run_w2 are patched; a FakeTracker exposes the two read-only getters the
runner uses (count_today, get_lifecycle_counts). No browser, no DB.
"""
import pytest

from services import regression


class FakeTracker:
    def __init__(self, today=0, msgs=0, convs=0):
        self._today = today
        self._msgs = msgs
        self._convs = convs

    def count_today(self):
        return self._today

    def get_lifecycle_counts(self):
        return {"tables": {"applications": 0,
                           "hr_conversations": self._convs,
                           "hr_messages": self._msgs}}


def _submit_for(w1_fn, w2_fn):
    """Build the injected `submit` the smoke calls instead of run_w1/run_w2.

    In production this is the queue-backed submit (enqueue + wait); here it just
    dispatches to the fake, so the smoke's assertion logic is tested without a
    browser or a queue.
    """
    def submit(workflow, params):
        return (w1_fn if workflow == "w1" else w2_fn)(**params)
    return submit


def _check(report, name_contains):
    return next(c for c in report["checks"] if name_contains in c["name"])


def test_dry_mode_only_checks_read_path(monkeypatch):
    _sub = _submit_for(
        lambda **kw: {"cards_viewed": 2, "scored": 1, "applied": 0, "errors": 0},
        lambda **kw: {"convs_processed": 5, "stage_changes": 0, "resumes_sent": 0},
    )
    tr = FakeTracker()
    rep = regression.run_smoke(submit=_sub, tracker=tr, dry_run=True)
    assert rep["mode"] == "dry"
    assert rep["ok"] is True


def test_live_w1_applied_and_persisted_is_ok(monkeypatch):
    tr = FakeTracker(today=5)

    def w1(**kw):
        tr._today += 1  # a real apply landed in the DB
        return {"cards_viewed": 1, "scored": 1, "applied": 1, "errors": 0}

    _sub = _submit_for( w1, lambda **kw: {"convs_processed": 0, "resumes_sent": 0})
    rep = regression.run_smoke(submit=_sub, tracker=tr, dry_run=False)
    w1c = _check(rep, "W1")
    assert w1c["ok"] is True
    assert "Δ+1" in w1c["detail"]


def test_live_w1_applied_but_not_persisted_fails(monkeypatch):
    """The bug this whole feature exists to catch: apply reported success but the
    DB did not move -> the check MUST go red, not silently pass."""
    tr = FakeTracker(today=5)
    # applied=1 but count_today does NOT advance
    _sub = _submit_for(
        lambda **kw: {"cards_viewed": 1, "scored": 1, "applied": 1, "errors": 0},
        lambda **kw: {"convs_processed": 0, "resumes_sent": 0},
    )
    rep = regression.run_smoke(submit=_sub, tracker=tr, dry_run=False)
    w1c = _check(rep, "W1")
    assert w1c["ok"] is False
    assert "落库失败" in w1c["detail"]  # 落库失败
    assert rep["ok"] is False


def test_live_w1_nothing_to_apply_is_honestly_not_covered(monkeypatch):
    tr = FakeTracker(today=5)
    _sub = _submit_for(
        lambda **kw: {"cards_viewed": 3, "scored": 2, "applied": 0, "errors": 0},
        lambda **kw: {"convs_processed": 0, "resumes_sent": 0},
    )
    rep = regression.run_smoke(submit=_sub, tracker=tr, dry_run=False)
    w1c = _check(rep, "W1")
    assert w1c["ok"] is True  # nothing applied is not a failure
    assert w1c["covered"] is False  # ...but nothing was verified either
    assert "未覆盖" in w1c["detail"]  # 未覆盖


def test_live_w2_resume_sent_and_persisted_is_ok(monkeypatch):
    tr = FakeTracker(msgs=100, convs=10)

    def w2(**kw):
        tr._msgs += 1  # the sent resume card persisted as a new message
        return {"convs_processed": 1, "stage_changes": 1, "resumes_sent": 1}

    _sub = _submit_for( lambda **kw: {"cards_viewed": 0, "applied": 0}, w2)
    rep = regression.run_smoke(submit=_sub, tracker=tr, dry_run=False)
    w2c = _check(rep, "W2")
    assert w2c["ok"] is True


def test_live_w2_resume_sent_but_not_persisted_fails(monkeypatch):
    tr = FakeTracker(msgs=100, convs=10)
    # resumes_sent=1 but hr_messages does NOT grow
    _sub = _submit_for(
        lambda **kw: {"cards_viewed": 0, "applied": 0},
        lambda **kw: {"convs_processed": 1, "stage_changes": 0, "resumes_sent": 1},
    )
    rep = regression.run_smoke(submit=_sub, tracker=tr, dry_run=False)
    w2c = _check(rep, "W2")
    assert w2c["ok"] is False
    assert "落库失败" in w2c["detail"]  # 落库失败


def test_live_w2_no_outbound_is_ok(monkeypatch):
    """Rescanning already-seen conversations upserts via UPDATE (no row delta); with
    no resume send we only require the pipeline not to crash."""
    tr = FakeTracker(msgs=100, convs=10)
    _sub = _submit_for(
        lambda **kw: {"cards_viewed": 0, "applied": 0},
        lambda **kw: {"convs_processed": 3, "stage_changes": 0, "resumes_sent": 0},
    )
    rep = regression.run_smoke(submit=_sub, tracker=tr, dry_run=False)
    w2c = _check(rep, "W2")
    assert w2c["ok"] is True


# ---- execution path: the smoke must go through the injected submit -------------


def test_smoke_submits_both_workflows_with_the_knobs_it_was_given():
    """The smoke does not call run_w1/run_w2 itself -- it submits them, so in
    production they travel the queue like every other workflow start (one execution
    path, one place that maps triggers / writes the schedule log / clears the mutex).

    Also pins knob forwarding: score_threshold reaching the runner is what lets the
    apply path be covered at all (at the stock 60 the smoke may apply nothing).
    """
    seen = []

    def submit(workflow, params):
        seen.append((workflow, params))
        return {"cards_viewed": 1, "scored": 1, "applied": 0,
                "convs_processed": 1, "resumes_sent": 0}

    regression.run_smoke(
        submit=submit, tracker=FakeTracker(), dry_run=True, w1_max=3, w2_max=7,
        score_threshold=35, no_response_days=21, stale_conv_days=45,
    )

    assert [w for w, _ in seen] == ["w1", "w2"]
    w1p = dict(seen[0][1])
    w2p = dict(seen[1][1])
    assert w1p["max_cards"] == 3 and w1p["score_threshold"] == 35
    assert w2p["max_conversations"] == 7
    assert w2p["no_response_days"] == 21 and w2p["stale_conv_days"] == 45
    # trigger identifies the smoke's own runs in the log archive afterwards
    assert w1p["trigger"] == "smoke" and w2p["trigger"] == "smoke"


def test_live_mode_uses_a_distinct_trigger():
    """dry and live must be distinguishable in the log archive -- run_diagnostics
    locates 'the runs this smoke just produced' by trigger."""
    seen = []

    def submit(workflow, params):
        seen.append(params.get("trigger"))
        return {"applied": 0, "resumes_sent": 0}

    regression.run_smoke(submit=submit, tracker=FakeTracker(today=1), dry_run=False)
    assert seen == ["smoke_live", "smoke_live"]


def test_unset_knobs_are_not_forwarded():
    """None means 'use the runner default' -- forwarding an explicit None would
    override the resolved config with a null."""
    seen = []

    def submit(workflow, params):
        seen.append(params)
        return {"cards_viewed": 1, "scored": 1, "convs_processed": 1}

    regression.run_smoke(submit=submit, tracker=FakeTracker(), dry_run=True)
    assert "score_threshold" not in seen[0]
    assert "no_response_days" not in seen[1] and "stale_conv_days" not in seen[1]


# ---- coverage axis: "nothing failed" is NOT the same as "something was verified" --


def test_run_that_did_nothing_passes_but_is_not_fully_covered(monkeypatch):
    """THE gate-integrity test. A live run where there was no card to apply and no
    resume to send satisfies every assertion while verifying nothing. ok stays True
    (nothing broke), but fully_covered MUST be False -- otherwise the smoke reads as
    a green light and silently stops being a gate."""
    tr = FakeTracker(today=5, msgs=100, convs=10)
    _sub = _submit_for(
        lambda **kw: {"cards_viewed": 3, "scored": 2, "applied": 0, "errors": 0},
        lambda **kw: {"convs_processed": 3, "stage_changes": 0, "resumes_sent": 0},
    )
    rep = regression.run_smoke(submit=_sub, tracker=tr, dry_run=False)
    assert rep["ok"] is True
    assert rep["fully_covered"] is False
    assert len(rep["uncovered"]) == 2  # both workflows verified nothing


def test_live_run_with_both_outbound_actions_is_fully_covered(monkeypatch):
    tr = FakeTracker(today=5, msgs=100, convs=10)

    def w1(**kw):
        tr._today += 1
        return {"cards_viewed": 1, "scored": 1, "applied": 1, "errors": 0}

    def w2(**kw):
        tr._msgs += 1
        return {"convs_processed": 1, "stage_changes": 1, "resumes_sent": 1}

    _sub = _submit_for( w1, w2)
    rep = regression.run_smoke(submit=_sub, tracker=tr, dry_run=False)
    assert rep["ok"] is True
    assert rep["fully_covered"] is True
    assert rep["uncovered"] == []


def test_dry_run_coverage_tracks_read_path(monkeypatch):
    """Dry-run exercises the READ path, so coverage means cards were seen+scored and
    conversations were processed. A run that reached nothing is not coverage."""
    _sub = _submit_for(
        lambda **kw: {"cards_viewed": 0, "scored": 0, "applied": 0, "errors": 0},
        lambda **kw: {"convs_processed": 0, "stage_changes": 0, "resumes_sent": 0},
    )
    rep = regression.run_smoke(submit=_sub, tracker=FakeTracker(), dry_run=True)
    assert rep["fully_covered"] is False

    _sub = _submit_for(
        lambda **kw: {"cards_viewed": 2, "scored": 2, "applied": 0, "errors": 0},
        lambda **kw: {"convs_processed": 4, "stage_changes": 0, "resumes_sent": 0},
    )
    rep = regression.run_smoke(submit=_sub, tracker=FakeTracker(), dry_run=True)
    assert rep["fully_covered"] is True


def test_report_declares_paths_it_never_exercises(monkeypatch):
    """W3 (sending approved replies to real HRs) is deliberately excluded. That gap
    must be stated in the report itself, not buried in a docstring, so nobody reads a
    green smoke as "replies verified"."""
    _sub = _submit_for(
        lambda **kw: {"cards_viewed": 1, "scored": 1, "applied": 0, "errors": 0},
        lambda **kw: {"convs_processed": 1, "resumes_sent": 0},
    )
    rep = regression.run_smoke(submit=_sub, tracker=FakeTracker(), dry_run=True)
    assert any("W3" in p for p in rep["not_covered_paths"])


def test_crashed_step_is_neither_ok_nor_covered(monkeypatch):
    def boom(**kw):
        raise RuntimeError("browser died")

    _sub = _submit_for( boom, lambda **kw: {"convs_processed": 1, "resumes_sent": 0})
    rep = regression.run_smoke(submit=_sub, tracker=FakeTracker(), dry_run=True)
    w1c = _check(rep, "W1")
    assert w1c["ok"] is False and w1c["covered"] is False
    assert rep["ok"] is False and rep["fully_covered"] is False


def test_live_w1_error_fails(monkeypatch):
    tr = FakeTracker(today=5)
    _sub = _submit_for(
        lambda **kw: {"error": "SessionExpiredError", "applied": 0, "errors": 1},
        lambda **kw: {"convs_processed": 0, "resumes_sent": 0},
    )
    rep = regression.run_smoke(submit=_sub, tracker=tr, dry_run=False)
    assert _check(rep, "W1")["ok"] is False
    assert rep["ok"] is False
