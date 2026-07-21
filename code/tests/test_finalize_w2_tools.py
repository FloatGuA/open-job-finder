"""Tests for W2 FinalizeStep DB tools: sync_application_status + mark_timeout + purge.

State-machine model (2026-07-03 rework):
- Applying needs no HR reply, so "no reply after applying" is NOT a rejection.
  mark_timeout only puts a soft stall marker on conversations (stage='closed'); it
  never touches application status.
- REJECTED means only an explicit HR rejection (conversation intent='rejection').
- A REJECTED application whose conversation becomes active again is revived to APPLIED.
- Jobs with no progress older than the purge horizon are deleted entirely (application
  + conversation + messages) so they re-run the full W1 pipeline when they resurface.
"""
import pytest

from schemas import ApplicationRecord, AppStatus, HRConversation
from services.tracker import ApplicationTracker
from tools.db.w2.sync_application_status import SyncApplicationStatusFromConversations
from tools.db.w2.mark_timeout_statuses import MarkTimeoutStatuses
from tools.db.w2.purge_stale_applications import PurgeStaleApplications


@pytest.fixture
def tracker(tmp_path):
    t = ApplicationTracker(str(tmp_path / "test.db"))
    yield t
    t.close()


def _app(tracker, job_id, hr_name, company, status, applied_at=None):
    tracker.upsert(ApplicationRecord(
        job_id=job_id, title="后端", company=company, url="",
        status=status, hr_name=hr_name, applied_at=applied_at,
    ))


def _conv(tracker, conv_id, hr_name, company, stage, created_at=None, intent=None):
    tracker.upsert_hr_conversation(
        HRConversation(conv_id=conv_id, hr_name=hr_name, company=company,
                       stage=stage, intent=intent,
                       created_at=created_at or "2026-06-01T00:00:00+00:00")
    )


def _msg(tracker, conv_id, created_at, sender="hr", text="hi"):
    with tracker.conn:
        tracker.conn.execute(
            "INSERT INTO hr_messages (conv_id, sender, text, msg_time, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (conv_id, sender, text, created_at, created_at),
        )


# ── sync ──────────────────────────────────────────────────────────────────────

def test_sync_promotes_application_status_from_stage(tracker):
    _app(tracker, "j1", "王女士", "Acme", AppStatus.APPLIED.value)
    _conv(tracker, "c1", "王女士", "Acme", "interview")

    res = SyncApplicationStatusFromConversations(db=tracker).execute()
    assert res.ok
    assert tracker.get("j1").status == "INTERVIEWING"


def test_sync_ignores_non_terminal_stages(tracker):
    _app(tracker, "j1", "王女士", "Acme", AppStatus.APPLIED.value)
    _conv(tracker, "c1", "王女士", "Acme", "active")  # not interview/offer/closed
    SyncApplicationStatusFromConversations(db=tracker).execute()
    assert tracker.get("j1").status == "APPLIED"


def test_sync_rejects_only_explicit_rejection(tracker):
    # closed + intent='rejection' -> REJECTED; closed without rejection (soft stall) stays.
    _app(tracker, "rej", "A", "X", AppStatus.APPLIED.value)
    _conv(tracker, "c_rej", "A", "X", "closed", intent="rejection")
    _app(tracker, "stall", "B", "Y", AppStatus.APPLIED.value)
    _conv(tracker, "c_stall", "B", "Y", "closed", intent=None)

    SyncApplicationStatusFromConversations(db=tracker).execute()
    assert tracker.get("rej").status == "REJECTED"
    assert tracker.get("stall").status == "APPLIED"  # soft stall must NOT reject


def test_sync_revives_rejected_when_conversation_active(tracker):
    # A REJECTED job whose conversation is active again (HR re-engaged) -> APPLIED.
    _app(tracker, "j1", "A", "X", AppStatus.REJECTED.value)
    _conv(tracker, "c1", "A", "X", "active")
    SyncApplicationStatusFromConversations(db=tracker).execute()
    assert tracker.get("j1").status == "APPLIED"


# ── mark_timeout (conversation stall only) ──────────────────────────────────────

def test_mark_timeout_does_not_crash_and_closes_stale_conv(tracker):
    _conv(tracker, "c1", "王女士", "Acme", "active", created_at="2020-01-01T00:00:00+00:00")
    res = MarkTimeoutStatuses(db=tracker).execute(no_response_days=14, stale_conv_days=30)
    assert res.ok, res.error
    assert "c1" in res.data["stale_closed"]
    assert tracker.get_hr_conversation("c1").stage == "closed"


def test_mark_timeout_keeps_recent_and_terminal(tracker):
    _conv(tracker, "recent", "A", "X", "active", created_at="2099-01-01T00:00:00+00:00")
    _conv(tracker, "offered", "B", "Y", "offer", created_at="2020-01-01T00:00:00+00:00")
    res = MarkTimeoutStatuses(db=tracker).execute(no_response_days=14)
    assert res.ok
    assert res.data["stale_closed"] == []  # recent not stale; offer is terminal
    assert tracker.get_hr_conversation("offered").stage == "offer"


def _days_ago_ms(days: int) -> int:
    import time
    return int((time.time() - days * 86400) * 1000)


def _set_last_msg_ts(tracker, conv_id, ts_ms):
    """Write last_msg_ts directly.

    tracker.upsert_hr_conversation does not persist this column -- only the
    upsert_hr_conversation TOOL does (it also owns hr_title/job_id and the legacy
    re-key logic). That split is a known divergence queued for convergence; until
    then the fixture writes the column itself rather than silently testing nothing.
    """
    with tracker.conn:
        tracker.conn.execute(
            "UPDATE hr_conversations SET last_msg_ts = ? WHERE conv_id = ?",
            (ts_ms, conv_id),
        )


def test_stall_is_measured_from_when_the_hr_last_spoke(tracker):
    """last_msg_ts (real chat-list timestamp), not insert time.

    hr_messages.created_at is when WE wrote the row: the first time a months-old
    thread is scanned, every message gets today's created_at, so the thread looked
    freshly active and was never soft-closed. The row below is written today but
    its last real message is 60 days old -- it must still close.
    """
    _conv(tracker, "stale", "A", "X", "active", created_at="2026-07-22T00:00:00+00:00")
    _set_last_msg_ts(tracker, "stale", _days_ago_ms(60))

    res = MarkTimeoutStatuses(db=tracker).execute(no_response_days=14)
    assert "stale" in res.data["stale_closed"]


def test_recent_real_activity_survives_an_old_insert_date(tracker):
    """The mirror case: a row created long ago whose HR spoke yesterday is live."""
    _conv(tracker, "live", "A", "X", "active", created_at="2020-01-01T00:00:00+00:00")
    _set_last_msg_ts(tracker, "live", _days_ago_ms(1))

    res = MarkTimeoutStatuses(db=tracker).execute(no_response_days=14)
    assert res.data["stale_closed"] == []
    assert tracker.get_hr_conversation("live").stage == "active"


def test_rows_without_a_real_timestamp_fall_back_to_insert_time(tracker):
    """DOM-fallback / pre-migration rows have last_msg_ts=0; an unknown real time is
    better served by the old rough signal than by treating the row as infinitely old."""
    _conv(tracker, "nots", "A", "X", "active", created_at="2020-01-01T00:00:00+00:00")
    res = MarkTimeoutStatuses(db=tracker).execute(no_response_days=14)
    assert "nots" in res.data["stale_closed"]


def test_mark_timeout_never_rejects_applications(tracker):
    # A stale APPLIED job (old applied_at) must NOT be rejected — applying needs no reply.
    _app(tracker, "j1", "A", "X", AppStatus.APPLIED.value,
         applied_at="2020-01-01T00:00:00+00:00")
    MarkTimeoutStatuses(db=tracker).execute(no_response_days=14)
    assert tracker.get("j1").status == "APPLIED"


# ── purge (30-day cleanup / revival) ────────────────────────────────────────────

def test_purge_deletes_stale_no_progress(tracker):
    _app(tracker, "j1", "A", "X", AppStatus.APPLIED.value,
         applied_at="2020-01-01T00:00:00+00:00")
    _conv(tracker, "c1", "A", "X", "closed", created_at="2020-01-01T00:00:00+00:00")
    _msg(tracker, "c1", "2020-01-02T00:00:00+00:00")

    res = PurgeStaleApplications(db=tracker).execute(days=30)
    assert res.ok
    assert "j1" in res.data["purged"]
    assert tracker.get("j1") is None
    assert tracker.get_hr_conversation("c1") is None
    assert tracker.get_hr_messages("c1") == []


def test_purge_keeps_recent(tracker):
    _app(tracker, "j1", "A", "X", AppStatus.APPLIED.value,
         applied_at="2099-01-01T00:00:00+00:00")
    res = PurgeStaleApplications(db=tracker).execute(days=30)
    assert res.data["purged"] == []
    assert tracker.get("j1").status == "APPLIED"


def test_purge_protects_interview_and_offer(tracker):
    _app(tracker, "iv", "A", "X", AppStatus.INTERVIEWING.value,
         applied_at="2020-01-01T00:00:00+00:00")
    _app(tracker, "of", "B", "Y", AppStatus.OFFER.value,
         applied_at="2020-01-01T00:00:00+00:00")
    res = PurgeStaleApplications(db=tracker).execute(days=30)
    assert res.data["purged"] == []
    assert tracker.get("iv").status == "INTERVIEWING"
    assert tracker.get("of").status == "OFFER"


def test_purge_rejected_is_reappliable_by_deletion(tracker):
    # An explicitly REJECTED job past the horizon is also purged (regardless), so it can
    # re-run when it resurfaces — "no matter what, revive after the horizon".
    _app(tracker, "j1", "A", "X", AppStatus.REJECTED.value,
         applied_at="2020-01-01T00:00:00+00:00")
    res = PurgeStaleApplications(db=tracker).execute(days=30)
    assert "j1" in res.data["purged"]
    assert tracker.get("j1") is None
