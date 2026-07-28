"""GetApprovedReplies tool contract.

The tool is a THIN SHELL over tracker.get_approved_replies() (the one place that
SELECT lives) and must serialize job_id + boss_conv_id so W3 can direct-open the
conversation (navigate_to_conversation Treatment D) instead of the slow search box.
The old version inlined its own SQL and dropped job_id entirely.
"""
import pytest

from services.tracker import ApplicationTracker
from schemas import HRConversation
from tools.db.w2.get_approved_replies import GetApprovedReplies


@pytest.fixture
def tracker(tmp_path):
    t = ApplicationTracker(str(tmp_path / "test.db"))
    yield t
    t.close()


def _seed(tracker, conv_id, *, job_id, boss_conv_id, reply_status):
    tracker.upsert_hr_conversation(HRConversation(
        conv_id=conv_id, hr_name="李女士", company="X公司",
        job_id=job_id, boss_conv_id=boss_conv_id,
    ))
    tracker.update_reply_approval(conv_id, reply_status, "你好，方便聊聊吗")


def test_tool_serializes_job_id_and_boss_conv_id(tracker):
    _seed(tracker, "c1", job_id="encJob1", boss_conv_id="encBoss1", reply_status="approved")

    res = GetApprovedReplies(db=tracker).execute()

    assert res.ok
    assert res.data["count"] == 1
    conv = res.data["conversations"][0]
    # The whole point of the convergence: these two ids are now present so W3 can
    # direct-open instead of falling back to the slow search-box locate.
    assert conv["job_id"] == "encJob1"
    assert conv["boss_conv_id"] == "encBoss1"
    assert conv["reply_text"] == "你好，方便聊聊吗"


def test_tool_returns_approved_and_revision_only(tracker):
    _seed(tracker, "c1", job_id="j1", boss_conv_id="b1", reply_status="approved")
    _seed(tracker, "c2", job_id="j2", boss_conv_id="b2", reply_status="revision")
    _seed(tracker, "c3", job_id="j3", boss_conv_id="b3", reply_status="pending")

    res = GetApprovedReplies(db=tracker).execute()

    assert {c["conv_id"] for c in res.data["conversations"]} == {"c1", "c2"}
