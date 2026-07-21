"""Tests for the update_hr_analysis tool's reply-state protection.

When W2 re-analyzes a conversation it must not clobber a user/system decision:
'approved', 'revision', 'dismissed', 'sent' keep both their reply_status and
reply_text; only null/'pending' are freely refreshed. (Regression: an earlier
version omitted 'approved' and left reply_text unprotected.)
"""
import pytest

from schemas import HRConversation
from services.tracker import ApplicationTracker
from tools.db.w2.update_hr_analysis import UpdateHRAnalysis


@pytest.fixture
def tracker(tmp_path):
    t = ApplicationTracker(str(tmp_path / "test.db"))
    yield t
    t.close()


def _seed(tracker, conv_id="c1", reply_status=None, reply_text=""):
    tracker.upsert_hr_conversation(
        HRConversation(conv_id=conv_id, hr_name="王女士", company="测试公司")
    )
    if reply_status is not None:
        tracker.update_reply_approval(conv_id, reply_status, reply_text)


def _reanalyze(tracker, **kw):
    kw.setdefault("conv_id", "c1")
    kw.setdefault("intent", "general")
    kw.setdefault("reply_status", "pending")
    UpdateHRAnalysis(db=tracker).execute(**kw)


def test_reanalysis_does_not_clobber_approved(tracker):
    _seed(tracker, reply_status="approved", reply_text="user approved reply")
    _reanalyze(tracker, reply_text="fresh llm draft")
    conv = tracker.get_hr_conversation("c1")
    assert conv.reply_status == "approved"            # not downgraded to pending
    assert conv.reply_text == "user approved reply"   # not overwritten
    assert conv.intent == "general"                   # intent still refreshed


def test_reanalysis_does_not_clobber_revision_text(tracker):
    _seed(tracker, reply_status="revision", reply_text="user edited reply")
    _reanalyze(tracker, reply_text="fresh llm draft")
    conv = tracker.get_hr_conversation("c1")
    assert conv.reply_status == "revision"
    assert conv.reply_text == "user edited reply"


def test_pending_is_freely_refreshed(tracker):
    _seed(tracker, reply_status="pending", reply_text="old draft")
    _reanalyze(tracker, intent="interview_invite", reply_text="new draft")
    conv = tracker.get_hr_conversation("c1")
    assert conv.reply_status == "pending"
    assert conv.reply_text == "new draft"
    assert conv.intent == "interview_invite"


def test_null_status_becomes_pending(tracker):
    _seed(tracker)  # fresh row, reply_status is NULL
    _reanalyze(tracker, reply_text="draft")
    conv = tracker.get_hr_conversation("c1")
    assert conv.reply_status == "pending"
    assert conv.reply_text == "draft"
