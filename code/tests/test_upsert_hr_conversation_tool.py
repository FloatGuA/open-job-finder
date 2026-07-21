"""Tests for the upsert_hr_conversation tool (W2 per-conversation final persist).

Regression: the tool used to INSERT hr_title/job_title/updated_at, none of which
exist in the T030 schema, so every per-conversation upsert raised "no such column"
and the final stage/preview persistence crashed on every conversation. Also pins
the forward-only stage machine.
"""
import pytest

from services.tracker import ApplicationTracker
from tools.db.w2.upsert_hr_conversation import UpsertHRConversation


@pytest.fixture
def tracker(tmp_path):
    t = ApplicationTracker(str(tmp_path / "test.db"))
    yield t
    t.close()


def _upsert(tracker, **kw):
    kw.setdefault("conv_id", "c1")
    kw.setdefault("hr_name", "王女士")
    kw.setdefault("company", "测试公司")
    return UpsertHRConversation(db=tracker).execute(**kw)


def test_insert_persists_hr_title_and_ignores_job_title(tracker):
    # hr_title IS now a real column and is persisted; job_title remains a non-column
    # accepted for caller compat but not persisted; must not raise.
    res = _upsert(tracker, stage="active", last_msg_preview="hi",
                  hr_title="人力资源岗", job_title="后端")
    assert res.ok, res.error
    assert res.data["stage"] == "active"
    assert res.data["prev_stage"] == "new"
    assert res.data["stage_changed"] is True

    conv = tracker.get_hr_conversation("c1")
    assert conv.stage == "active"
    assert conv.last_msg_preview == "hi"
    assert conv.hr_title == "人力资源岗"


def test_hr_title_not_wiped_by_empty(tracker):
    _upsert(tracker, hr_title="人力资源岗")
    _upsert(tracker, hr_title="")  # empty must not wipe the stored title
    conv = tracker.get_hr_conversation("c1")
    assert conv.hr_title == "人力资源岗"


def test_stage_only_moves_forward(tracker):
    _upsert(tracker, stage="interview")
    # a later upsert with an earlier stage must NOT regress
    res = _upsert(tracker, stage="active")
    assert res.data["stage"] == "interview"
    assert res.data["stage_changed"] is False


def test_closed_revives_on_new_activity(tracker):
    # A stale-closed conversation is only re-upserted when filter_conversations
    # decided to process it (i.e. there IS new activity), so the fresh stage must
    # win -- "HR re-engaged -> revive", not stay stuck closed.
    _upsert(tracker, stage="closed")
    res = _upsert(tracker, stage="active")
    assert res.data["stage"] == "active"
    assert res.data["stage_changed"] is True


def test_closed_stays_closed_without_reopen_signal(tracker):
    # A re-upsert that itself carries stage='closed' (e.g. rejection intent, or a
    # re-stale close) keeps it closed -- only a non-closed incoming stage revives.
    _upsert(tracker, stage="closed")
    res = _upsert(tracker, stage="closed")
    assert res.data["stage"] == "closed"
    assert res.data["stage_changed"] is False


def test_boss_conv_id_not_overwritten_by_empty(tracker):
    _upsert(tracker, boss_conv_id="62001")
    _upsert(tracker, boss_conv_id="")  # empty must not wipe the stored value
    conv = tracker.get_hr_conversation("c1")
    assert conv.boss_conv_id == "62001"
