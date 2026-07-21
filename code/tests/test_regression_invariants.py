"""Layer-2 regression: run_invariants asserts data-layer invariants the DB can't
enforce (status/stage enums, reply consistency, analysis watermarks) over tracker
getters.

Conversations are built from the REAL HRConversation dataclass, not a hand-rolled
stub: a stub silently drifts from the schema, so a new invariant reading a new
field blows up with AttributeError instead of being tested (which is exactly what
happened when last_analyzed_ts was added).
"""
from schemas import HRConversation
from services import regression


class _App:
    def __init__(self, status):
        self.status = status


def _conv(**kw) -> HRConversation:
    """HRConversation with the identity fields filled in; override the rest."""
    base = {"conv_id": "c1", "hr_name": "hr", "company": "co"}
    base.update(kw)
    return HRConversation(**base)


class _Tracker:
    def __init__(self, apps, convs, health=None):
        self._apps = apps
        self._convs = convs
        self._health = health or {"convs_hr_no_intent": 0, "orphan_messages": 0}

    def get_all(self):
        return self._apps

    def get_hr_conversations(self):
        return self._convs

    def get_data_health(self):
        return self._health


def test_invariants_all_clean():
    t = _Tracker(
        [_App("APPLIED"), _App("REJECTED"), _App("OFFER")],
        [
            _conv(stage="new"),
            # sent clears reply_text by design -> empty text here is LEGAL, not a violation
            _conv(stage="closed", reply_status="sent", reply_text=None),
        ],
    )
    rep = regression.run_invariants(t)
    assert rep["ok"] is True
    assert rep["total_apps"] == 3
    assert rep["total_convs"] == 2
    assert all(c["ok"] for c in rep["checks"])


def test_invariants_catches_dead_status_bad_stage_and_empty_reply():
    t = _Tracker(
        [_App("APPLIED"), _App("FOUND"), _App("BOGUS")],
        [
            _conv(stage="new", reply_status="approved", reply_text=""),  # empty reply body
            _conv(stage="weird"),  # illegal stage
        ],
    )
    rep = regression.run_invariants(t)
    assert rep["ok"] is False

    by_name = {c["name"]: c for c in rep["checks"]}
    # FOUND is a dead status
    dead = next(c for n, c in by_name.items() if "FOUND" in n)
    assert not dead["ok"] and dead["count"] == 1
    # Neither FOUND nor BOGUS is a legal status (FOUND is both dead and illegal)
    bad_status = next(c for n, c in by_name.items() if "应聘状态全部合法" in n)
    assert not bad_status["ok"] and bad_status["count"] == 2
    # illegal stage caught
    bad_stage = next(c for n, c in by_name.items() if "stage" in n)
    assert not bad_stage["ok"] and bad_stage["count"] == 1
    # approved reply with empty text caught
    empty = next(c for n, c in by_name.items() if "正文" in n)
    assert not empty["ok"] and empty["count"] == 1


# ---- watermark invariants (the read/analyze decoupling contract, #53) ---------


def test_invariants_catch_watermark_overshoot():
    """last_analyzed_ts > last_msg_ts means we claim to have analyzed past what we
    have seen -- the dirty check would then never re-fire and the conversation goes
    invisible. This is the failure mode #53 exists to prevent."""
    t = _Tracker(
        [],
        [_conv(intent="general", last_msg_ts=100, last_analyzed_ts=200)],
    )
    rep = regression.run_invariants(t)
    assert rep["ok"] is False
    overshoot = next(c for c in rep["checks"] if "水位线" in c["name"])
    assert not overshoot["ok"] and overshoot["count"] == 1


def test_invariants_catch_analyzed_without_intent():
    """A watermark that advanced without a stored verdict means analyze reported
    success but persisted nothing."""
    t = _Tracker([], [_conv(intent=None, last_msg_ts=100, last_analyzed_ts=100)])
    rep = regression.run_invariants(t)
    assert rep["ok"] is False
    no_intent = next(c for c in rep["checks"] if "必有结论" in c["name"])
    assert not no_intent["ok"] and no_intent["count"] == 1


def test_invariants_catch_sent_reply_still_holding_draft():
    """reply_text is a working draft cleared after send. A 'sent' row still holding
    text means one of the mark-sent implementations did not clear it -- the guard on
    the three-way mark-sent convergence."""
    t = _Tracker([], [_conv(reply_status="sent", reply_text="还没清掉的草稿")])
    rep = regression.run_invariants(t)
    assert rep["ok"] is False
    leftover = next(c for c in rep["checks"] if "不留草稿" in c["name"])
    assert not leftover["ok"] and leftover["count"] == 1


def test_invariants_surface_db_health_counters():
    """convs_hr_no_intent is the #52/#53 signature (read ok, analyze failed, then
    skipped forever); orphan_messages means unreachable history."""
    t = _Tracker([], [], health={"convs_hr_no_intent": 106, "orphan_messages": 3})
    rep = regression.run_invariants(t)
    assert rep["ok"] is False

    hr_no_intent = next(c for c in rep["checks"] if "必已分析" in c["name"])
    assert not hr_no_intent["ok"] and hr_no_intent["count"] == 106

    orphans = next(c for c in rep["checks"] if "孤儿" in c["name"])
    assert not orphans["ok"] and orphans["count"] == 3
