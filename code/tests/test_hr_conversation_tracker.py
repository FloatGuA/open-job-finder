"""Tests for ApplicationTracker HR conversation cache methods."""
import pytest

from schemas import HRConversation
from services.tracker import ApplicationTracker


@pytest.fixture
def tracker(tmp_path):
    db = tmp_path / "test.db"
    t = ApplicationTracker(str(db))
    yield t
    t.close()


def _make_conv(
    conv_id: str = "conv_001",
    company: str = "测试公司",
    boss_conv_id: str = "",
    stage: str = "new",
    last_msg_preview: str = "你好，请问方便电话沟通吗...",
) -> HRConversation:
    return HRConversation(
        conv_id=conv_id,
        hr_name="王女士",
        company=company,
        stage=stage,
        boss_conv_id=boss_conv_id,
        last_msg_preview=last_msg_preview,
    )


# ── upsert & get ─────────────────────────────────────────────────────────────

def test_upsert_and_get(tracker):
    conv = _make_conv()
    tracker.upsert_hr_conversation(conv)
    result = tracker.get_hr_conversation("conv_001")
    assert result is not None
    assert result.company == "测试公司"
    assert result.hr_name == "王女士"


def test_get_returns_none_for_missing(tracker):
    assert tracker.get_hr_conversation("nonexistent") is None


def test_upsert_updates_last_msg_preview(tracker):
    conv = _make_conv()
    tracker.upsert_hr_conversation(conv)

    updated = _make_conv(last_msg_preview="明天上午10点可以吗...")
    tracker.upsert_hr_conversation(updated)

    result = tracker.get_hr_conversation("conv_001")
    assert result.last_msg_preview == "明天上午10点可以吗..."


def test_upsert_stores_boss_conv_id(tracker):
    conv = _make_conv(boss_conv_id="abc123")
    tracker.upsert_hr_conversation(conv)
    result = tracker.get_hr_conversation("conv_001")
    assert result is not None
    assert result.boss_conv_id == "abc123"


def test_upsert_nonempty_boss_conv_id_wins(tracker):
    conv = _make_conv(boss_conv_id="abc123")
    tracker.upsert_hr_conversation(conv)

    updated = _make_conv()
    tracker.upsert_hr_conversation(updated, boss_conv_id="")

    result = tracker.get_hr_conversation("conv_001")
    assert result is not None
    assert result.boss_conv_id == "abc123"


def test_upsert_nonempty_overwrites_empty_boss_conv_id(tracker):
    conv = _make_conv()
    tracker.upsert_hr_conversation(conv)

    updated = _make_conv()
    tracker.upsert_hr_conversation(updated, boss_conv_id="abc123")

    result = tracker.get_hr_conversation("conv_001")
    assert result is not None
    assert result.boss_conv_id == "abc123"


# ── get_hr_conversations ──────────────────────────────────────────────────────

def test_get_all_conversations(tracker):
    tracker.upsert_hr_conversation(_make_conv("c1", "公司A"))
    tracker.upsert_hr_conversation(_make_conv("c2", "公司B"))
    results = tracker.get_hr_conversations()
    assert len(results) == 2


def test_get_conversations_by_stage(tracker):
    tracker.upsert_hr_conversation(_make_conv("c1", stage="new"))
    tracker.upsert_hr_conversation(_make_conv("c2", "公司B", stage="resume_sent"))

    new_ones = tracker.get_hr_conversations(stage="new")
    assert len(new_ones) == 1
    assert new_ones[0].conv_id == "c1"

    sent = tracker.get_hr_conversations(stage="resume_sent")
    assert len(sent) == 1


def test_get_by_stage_returns_empty_when_none_match(tracker):
    tracker.upsert_hr_conversation(_make_conv())
    assert tracker.get_hr_conversations(stage="offer") == []


# ── HR conversation schema columns ───────────────────────────────────────────

def test_hr_conversations_table_has_new_columns(tracker):
    cols = {
        row["name"]
        for row in tracker.conn.execute("PRAGMA table_info(hr_conversations)").fetchall()
    }
    for expected in ("intent", "reply_status", "reply_text", "boss_conv_id", "last_msg_preview"):
        assert expected in cols
    for deleted in ("messages", "suggested_reply", "needs_reply", "reply_draft",
                    "last_msg_text", "last_msg_from", "last_synced", "status"):
        assert deleted not in cols, f"deleted column still present: {deleted}"


# ── update_hr_analysis ────────────────────────────────────────────────────────

def test_update_hr_analysis_sets_intent_and_reply(tracker):
    conv = _make_conv()
    tracker.upsert_hr_conversation(conv)
    tracker.update_hr_analysis(conv.conv_id, "interview_invite", "好的，明天上午10点可以", "pending")

    result = tracker.get_hr_conversation(conv.conv_id)
    assert result.intent == "interview_invite"
    assert result.reply_text == "好的，明天上午10点可以"
    assert result.reply_status == "pending"


def test_upsert_does_not_overwrite_approved_analysis(tracker):
    conv = _make_conv()
    tracker.upsert_hr_conversation(conv)
    tracker.update_hr_analysis(conv.conv_id, "greeting", "你好，方便约个时间沟通吗？", "approved")

    updated = _make_conv(last_msg_preview="后天下午可以视频面试吗...")
    tracker.upsert_hr_conversation(updated)

    cached = tracker.get_hr_conversation(conv.conv_id)
    assert cached is not None
    assert cached.intent == "greeting"
    assert cached.reply_text == "你好，方便约个时间沟通吗？"
    assert cached.reply_status == "approved"


def test_update_hr_analysis_does_not_overwrite_sent(tracker):
    conv = _make_conv()
    tracker.upsert_hr_conversation(conv)
    # First analysis
    tracker.update_hr_analysis(conv.conv_id, "general", "第一条建议", "sent")
    # Re-analysis should not overwrite
    tracker.update_hr_analysis(conv.conv_id, "interview_invite", "第二条建议", "pending")

    result = tracker.get_hr_conversation(conv.conv_id)
    assert result.reply_text == "第一条建议"
    assert result.reply_status == "sent"


# ── reply approval & dismiss ──────────────────────────────────────────────────

def test_pending_and_approved_replies_returned(tracker):
    tracker.upsert_hr_conversation(_make_conv("c1", "公司A"))
    tracker.upsert_hr_conversation(_make_conv("c2", "公司B"))
    tracker.update_hr_analysis("c1", "info_request", "第一条建议", "pending")
    tracker.update_hr_analysis("c2", "interview_invite", "第二条建议", "approved")

    pending = tracker.get_pending_replies()
    conv_ids = {c.conv_id for c in pending}
    assert "c1" in conv_ids
    assert "c2" in conv_ids


def test_dismiss_reply_records_dismissed_not_null(tracker):
    """'dismissed' is PROTECTED; NULL is not.

    Writing NULL made the conversation look "never processed" to the next W2 scan,
    which would draft a fresh reply and put it straight back in the approval queue.
    A user decision must not be recorded as a neutral state -- same mistake
    mark_reply_sent once made.
    """
    conv = _make_conv("c1")
    tracker.upsert_hr_conversation(conv)
    tracker.update_hr_analysis("c1", "info_request", "建议", "pending")

    tracker.dismiss_reply("c1")

    cached = tracker.get_hr_conversation("c1")
    assert cached.reply_status == "dismissed"


def test_dismissed_reply_survives_reanalysis(tracker):
    """The point of using a protected status: a later scan must not resurrect the
    draft the user just rejected."""
    conv = _make_conv("c1")
    tracker.upsert_hr_conversation(conv)
    tracker.update_hr_analysis("c1", "info_request", "建议", "pending")
    tracker.dismiss_reply("c1")

    # Next W2 round analyses the conversation again and would like to draft.
    tracker.update_hr_analysis("c1", "resume_request", "新草稿", "pending")

    cached = tracker.get_hr_conversation("c1")
    assert cached.reply_status == "dismissed"
    assert cached.reply_text == "建议"  # the rejected draft is not replaced either


def test_dismiss_reply_removes_from_pending(tracker):
    tracker.upsert_hr_conversation(_make_conv("c1"))
    tracker.update_hr_analysis("c1", "general", "建议", "pending")

    tracker.dismiss_reply("c1")
    remaining = tracker.get_pending_replies()
    assert not any(c.conv_id == "c1" for c in remaining)


def test_update_reply_approval_persists(tracker):
    conv = _make_conv()
    tracker.upsert_hr_conversation(conv)
    tracker.update_hr_analysis(conv.conv_id, "info_request", "原始建议", "pending")

    tracker.update_reply_approval(conv.conv_id, "approved", "我周三下午方便电话沟通。")

    cached = tracker.get_hr_conversation(conv.conv_id)
    assert cached is not None
    assert cached.reply_status == "approved"
    assert cached.reply_text == "我周三下午方便电话沟通。"


def test_get_approved_replies(tracker):
    tracker.upsert_hr_conversation(_make_conv("c1"))
    tracker.upsert_hr_conversation(_make_conv("c2", "公司B"))
    tracker.upsert_hr_conversation(_make_conv("c3", "公司C"))
    tracker.update_hr_analysis("c1", "general", "建议1", "approved")
    tracker.update_hr_analysis("c2", "general", "建议2", "pending")
    tracker.update_reply_approval("c3", "revision", "改稿3")

    # approved + revision are both queued to send; pending is not.
    approved = tracker.get_approved_replies()
    assert {c.conv_id for c in approved} == {"c1", "c3"}


def test_invalidate_reply_for_reanalysis_voids_and_resets(tracker):
    """W3's stale-draft handling: an approved reply the conversation has outrun is
    voided AND knocked back to 'unanalyzed' so the next W2 run re-decides intent."""
    tracker.upsert_hr_conversation(_make_conv("c1"))
    tracker.update_hr_analysis("c1", "general", "旧草稿", "approved", last_analyzed_ts=12345)

    assert tracker.invalidate_reply_for_reanalysis("c1") == 1

    conv = tracker.get_hr_conversation("c1")
    assert conv.reply_status is None
    assert (conv.reply_text or "") == ""
    assert (conv.intent or "") == ""
    assert conv.last_analyzed_ts == 0


def test_invalidate_reply_leaves_non_queued_status_alone(tracker):
    """Only a reply still queued to send (approved/revision) is voided; a 'pending'
    (or terminal) status is left untouched — idempotent, no accidental revival."""
    tracker.upsert_hr_conversation(_make_conv("c1"))
    tracker.update_hr_analysis("c1", "general", "草稿", "pending", last_analyzed_ts=999)

    assert tracker.invalidate_reply_for_reanalysis("c1") == 0

    conv = tracker.get_hr_conversation("c1")
    assert conv.reply_status == "pending"
    assert conv.last_analyzed_ts == 999


def test_concurrent_writes_no_lock(tracker):
    """Two threads writing at once must not hit 'database is locked'.

    The dashboard runs W2 in a worker thread while API handlers (approve/cancel)
    write from the event-loop thread. Thread-local connections + busy_timeout
    must let these serialize safely instead of raising — a single shared
    connection used from both threads used to error.
    """
    import threading

    errors: list = []

    def worker(prefix: str) -> None:
        try:
            for i in range(30):
                tracker.upsert_hr_conversation(_make_conv(f"{prefix}_{i}", company=f"公司{prefix}"))
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(p,)) for p in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == [], f"concurrent writes raised: {errors}"
    assert len(tracker.get_hr_conversations()) == 60


def test_mark_reply_sent_records_sent_not_null(tracker):
    """'sent' is a PROTECTED status in update_hr_analysis; NULL is not.

    This method used to write NULL/NULL, so a conversation whose reply had already
    gone out looked "never processed" to the next re-analysis, which could draft and
    send a SECOND reply to the same HR. The status must be the protected terminal
    value, and the working draft must be cleared.
    """
    conv = _make_conv()
    tracker.upsert_hr_conversation(conv)
    tracker.update_hr_analysis(conv.conv_id, "interview_invite", "我可以", "approved")

    updated = tracker.mark_reply_sent(conv.conv_id)

    assert updated == 1
    result = tracker.get_hr_conversation(conv.conv_id)
    assert result.reply_status == "sent"
    assert not (result.reply_text or "").strip()


def test_analysis_is_not_lost_when_the_row_does_not_exist_yet(tracker):
    """W2 analyses BEFORE it upserts (stage depends on the intent being computed),
    so for a conversation W1 never applied to -- an HR who messaged first -- the row
    does not exist yet. A plain UPDATE matched zero rows and silently dropped the
    intent, the draft and the watermark; the later upsert then wrote stage only,
    producing rows whose stage had advanced while intent stayed empty. Four such
    rows were found in production.
    """
    tracker.update_hr_analysis(
        "brand-new-conv", "interview_invite",
        reply_text="方便的", reply_status="pending", last_analyzed_ts=1700,
    )

    result = tracker.get_hr_conversation("brand-new-conv")
    assert result is not None, "分析结果不能因为行不存在而丢失"
    assert result.intent == "interview_invite"
    assert result.reply_text == "方便的"
    assert result.last_analyzed_ts == 1700


def test_ensuring_the_row_never_disturbs_an_existing_one(tracker):
    """The INSERT must be OR IGNORE: re-analysing an existing conversation must not
    reset its identity columns or walk its stage backwards."""
    conv = _make_conv()
    conv.stage = "interview"
    tracker.upsert_hr_conversation(conv)

    tracker.update_hr_analysis(conv.conv_id, "general", reply_text="草稿", reply_status="pending")

    result = tracker.get_hr_conversation(conv.conv_id)
    assert result.stage == "interview"          # not reset to 'new'
    assert result.hr_name == conv.hr_name       # identity preserved
    assert result.company == conv.company


def test_mark_reply_sent_reports_missing_conversation(tracker):
    """Rowcount is what lets the endpoint answer 404 instead of a silent success."""
    assert tracker.mark_reply_sent("nope") == 0


def test_sent_status_survives_reanalysis(tracker):
    """The whole point of using 'sent': a later re-analysis must not revive the
    reply and make it eligible for sending again."""
    conv = _make_conv()
    tracker.upsert_hr_conversation(conv)
    tracker.update_hr_analysis(conv.conv_id, "interview_invite", "我可以", "approved")
    tracker.mark_reply_sent(conv.conv_id)

    # A later scan re-analyses the conversation and would like to draft a reply.
    tracker.update_hr_analysis(conv.conv_id, "general", "新的草稿", "pending")

    result = tracker.get_hr_conversation(conv.conv_id)
    assert result.reply_status == "sent"
    assert not (result.reply_text or "").strip()
