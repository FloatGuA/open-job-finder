"""Bulk-dismiss of pending replies: clears the 待审批 backlog in one shot without
touching replies the user has already triaged (approved/revision/sent)."""
import pytest

from schemas import HRConversation
from services.tracker import ApplicationTracker


@pytest.fixture
def tracker(tmp_path):
    t = ApplicationTracker(str(tmp_path / "test.db"))
    yield t
    t.close()


def _conv(tracker, conv_id, reply_status):
    tracker.upsert_hr_conversation(
        HRConversation(conv_id=conv_id, hr_name="hr_" + conv_id, company="co_" + conv_id,
                       stage="active", intent="unknown",
                       created_at="2026-06-01T00:00:00+00:00")
    )
    tracker.update_reply_approval(conv_id, reply_status, reply_text="draft")


def test_dismiss_all_pending_only_hits_pending(tracker):
    _conv(tracker, "a", "pending")
    _conv(tracker, "b", "pending")
    _conv(tracker, "c", "approved")  # already triaged
    _conv(tracker, "d", "sent")

    n = tracker.dismiss_all_pending_replies()
    assert n == 2

    got = {c.conv_id: c.reply_status for c in tracker.get_hr_conversations()}
    assert got["a"] == "dismissed"
    assert got["b"] == "dismissed"
    assert got["c"] == "approved"  # untouched -- user already acted on it
    assert got["d"] == "sent"


def test_dismiss_all_pending_noop_when_none(tracker):
    _conv(tracker, "c", "approved")
    assert tracker.dismiss_all_pending_replies() == 0
    assert tracker.get_hr_conversation("c").reply_status == "approved"
