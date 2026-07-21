"""Tests for the mark_reply_sent tool (ReplyStep's authoritative sent transition).

This must force reply_status='sent' even from 'approved' -- which update_hr_analysis
deliberately CANNOT do (it protects approved/revision/... from re-analysis). Using
update_hr_analysis here would leave the reply stuck at 'approved' and re-send it on
every W2 run.
"""
import pytest

from schemas import HRConversation
from services.tracker import ApplicationTracker
from tools.db.w2.mark_reply_sent import MarkReplySent


@pytest.fixture
def tracker(tmp_path):
    t = ApplicationTracker(str(tmp_path / "test.db"))
    yield t
    t.close()


def _seed(tracker, reply_status, reply_text="draft"):
    tracker.upsert_hr_conversation(
        HRConversation(conv_id="c1", hr_name="王女士", company="测试公司")
    )
    tracker.update_reply_approval("c1", reply_status, reply_text)


def test_marks_sent_from_approved(tracker):
    _seed(tracker, "approved", "user approved reply")
    res = MarkReplySent(db=tracker).execute(conv_id="c1")
    assert res.ok
    conv = tracker.get_hr_conversation("c1")
    assert conv.reply_status == "sent"        # forced through, unlike update_hr_analysis
    assert (conv.reply_text or "") == ""       # draft cleared


def test_marks_sent_from_pending(tracker):
    _seed(tracker, "pending")
    MarkReplySent(db=tracker).execute(conv_id="c1")
    assert tracker.get_hr_conversation("c1").reply_status == "sent"


def test_missing_conversation_updates_nothing(tracker):
    res = MarkReplySent(db=tracker).execute(conv_id="ghost")
    assert res.ok
    assert res.data["updated"] == 0
