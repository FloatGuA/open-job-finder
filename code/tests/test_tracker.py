"""Tests for ApplicationTracker — CRUD, state machine, city/salary fields."""
import sqlite3
from datetime import datetime, timezone
from typing import Optional

import pytest

from schemas import AppStatus, ApplicationRecord
from services.tracker import ApplicationTracker, VALID_TRANSITIONS


@pytest.fixture
def tracker(tmp_path):
    t = ApplicationTracker(str(tmp_path / "test.db"))
    yield t
    t.close()


def _rec(
    job_id: str = "job_001",
    status: str = AppStatus.FOUND.value,
    city: Optional[str] = "北京",
    salary: Optional[str] = "10K-20K",
    applied_at: Optional[str] = None,
    score: Optional[int] = 70,
) -> ApplicationRecord:
    # score defaults to a real number: a genuine W1 apply is always scored, and
    # count_today now excludes score-NULL rows (backfill reconstructions).
    now = datetime.now(timezone.utc).isoformat()
    return ApplicationRecord(
        job_id=job_id,
        title="后端工程师",
        company="测试公司",
        url="https://www.zhipin.com/job/001",
        status=status,
        city=city,
        salary=salary,
        score=score,
        applied_at=applied_at,
        created_at=now,
    )


# ── Insert / Get ─────────────────────────────────────────────────────────────

class TestInsertAndGet:
    def test_insert_and_retrieve(self, tracker):
        tracker.upsert(_rec())
        r = tracker.get("job_001")
        assert r is not None
        assert r.job_id == "job_001"
        assert r.title == "后端工程师"

    def test_get_nonexistent_returns_none(self, tracker):
        assert tracker.get("ghost") is None

    def test_exists_after_insert(self, tracker):
        tracker.upsert(_rec())
        assert tracker.exists("job_001") is True

    def test_not_exists_before_insert(self, tracker):
        assert tracker.exists("job_001") is False

    def test_city_salary_persisted(self, tracker):
        tracker.upsert(_rec(city="上海", salary="15K-25K"))
        r = tracker.get("job_001")
        assert r.city == "上海"
        assert r.salary == "15K-25K"

    def test_null_city_salary_persisted(self, tracker):
        tracker.upsert(_rec(city=None, salary=None))
        r = tracker.get("job_001")
        assert r.city is None
        assert r.salary is None


# ── City / Salary update semantics ───────────────────────────────────────────

class TestCitySalaryPreservation:
    def test_empty_string_does_not_overwrite_existing_city(self, tracker):
        tracker.upsert(_rec(city="上海", salary="15K-25K"))
        tracker.upsert(_rec(city="", salary="", status=AppStatus.APPLIED.value))
        r = tracker.get("job_001")
        assert r.city == "上海", "empty string must not overwrite a populated value"
        assert r.salary == "15K-25K", "empty string must not overwrite a populated value"

    def test_none_does_not_overwrite_existing_city(self, tracker):
        tracker.upsert(_rec(city="上海", salary="15K-25K"))
        tracker.upsert(_rec(city=None, salary=None, status=AppStatus.APPLIED.value))
        r = tracker.get("job_001")
        assert r.city == "上海"
        assert r.salary == "15K-25K"

    def test_non_empty_update_overwrites_city(self, tracker):
        tracker.upsert(_rec(city="上海", salary="15K-25K"))
        tracker.upsert(_rec(city="深圳", salary="20K-30K", status=AppStatus.APPLIED.value))
        r = tracker.get("job_001")
        assert r.city == "深圳"
        assert r.salary == "20K-30K"

    def test_upsert_preserves_created_at(self, tracker):
        tracker.upsert(_rec())
        original_created = tracker.get("job_001").created_at
        tracker.upsert(_rec(status=AppStatus.APPLIED.value))
        assert tracker.get("job_001").created_at == original_created


# ── State transitions ─────────────────────────────────────────────────────────

class TestStateTransitions:
    def test_found_to_applied(self, tracker):
        tracker.upsert(_rec(status=AppStatus.FOUND.value))
        tracker.update_status(
            "job_001", AppStatus.APPLIED,
            applied_at=datetime.now(timezone.utc).isoformat()
        )
        assert tracker.get("job_001").status == AppStatus.APPLIED.value

    def test_applied_to_interviewing(self, tracker):
        tracker.upsert(_rec(status=AppStatus.APPLIED.value))
        tracker.update_status("job_001", AppStatus.INTERVIEWING)
        assert tracker.get("job_001").status == AppStatus.INTERVIEWING.value

    def test_interviewing_to_offer(self, tracker):
        tracker.upsert(_rec(status=AppStatus.INTERVIEWING.value))
        tracker.update_status("job_001", AppStatus.OFFER)
        assert tracker.get("job_001").status == AppStatus.OFFER.value

    def test_invalid_transition_logs_but_does_not_raise(self, tracker):
        # FOUND -> OFFER is not in VALID_TRANSITIONS; must warn, not raise.
        tracker.upsert(_rec(status=AppStatus.FOUND.value))
        tracker.update_status("job_001", AppStatus.OFFER)

    def test_update_status_noop_for_missing_job(self, tracker):
        tracker.update_status("ghost", AppStatus.APPLIED)  # must not raise

    def test_same_status_update_is_idempotent(self, tracker):
        tracker.upsert(_rec(status=AppStatus.FOUND.value))
        tracker.update_status("job_001", AppStatus.FOUND)
        assert tracker.get("job_001").status == AppStatus.FOUND.value

    def test_applied_to_offer_is_valid(self, tracker):
        tracker.upsert(_rec(status=AppStatus.APPLIED.value))
        tracker.update_status("job_001", AppStatus.OFFER)
        assert AppStatus.OFFER.value in VALID_TRANSITIONS[AppStatus.APPLIED.value]
        assert tracker.get("job_001").status == AppStatus.OFFER.value

    def test_rejected_is_reappliable(self, tracker):
        # REJECTED is re-appliable: a rejected/timeout job that resurfaces in search goes
        # back through W1 and re-applies (REJECTED -> APPLIED is the only allowed exit).
        assert VALID_TRANSITIONS[AppStatus.REJECTED.value] == {AppStatus.APPLIED.value}

    def test_offer_only_exits_to_rejected(self, tracker):
        # OFFER is effectively terminal; the only modeled exit is REJECTED (offer
        # withdrawn / declined).
        assert VALID_TRANSITIONS[AppStatus.OFFER.value] == {AppStatus.REJECTED.value}


# ── count_today ───────────────────────────────────────────────────────────────

class TestCountToday:
    def test_zero_initially(self, tracker):
        assert tracker.count_today() == 0

    def test_applied_today_counted(self, tracker):
        tracker.upsert(_rec(
            status=AppStatus.APPLIED.value,
            applied_at=datetime.now(timezone.utc).isoformat()
        ))
        assert tracker.count_today() == 1

    def test_non_applied_status_not_counted(self, tracker):
        tracker.upsert(_rec(status=AppStatus.FOUND.value))
        assert tracker.count_today() == 0

    def test_applied_without_applied_at_not_counted(self, tracker):
        tracker.upsert(_rec(status=AppStatus.APPLIED.value, applied_at=None))
        assert tracker.count_today() == 0

    def test_old_applied_at_not_counted(self, tracker):
        tracker.upsert(_rec(status=AppStatus.APPLIED.value, applied_at="2020-01-01T10:00:00"))
        assert tracker.count_today() == 0

    def test_multiple_applications_today(self, tracker):
        for i in range(3):
            tracker.upsert(_rec(
                job_id=f"job_{i:03d}",
                status=AppStatus.APPLIED.value,
                applied_at=datetime.now(timezone.utc).isoformat(),
            ))
        assert tracker.count_today() == 3


# ── get_by_status / get_all ───────────────────────────────────────────────────

class TestQueryMethods:
    def test_get_by_status_filters(self, tracker):
        tracker.upsert(_rec("j1", AppStatus.FOUND.value))
        tracker.upsert(_rec("j2", AppStatus.APPLIED.value))
        tracker.upsert(_rec("j3", AppStatus.FOUND.value))
        results = tracker.get_by_status(AppStatus.FOUND.value)
        assert len(results) == 2
        assert all(r.status == AppStatus.FOUND.value for r in results)

    def test_get_by_status_empty(self, tracker):
        assert tracker.get_by_status(AppStatus.APPLIED.value) == []

    def test_get_all_returns_all(self, tracker):
        for i in range(5):
            tracker.upsert(_rec(job_id=f"j{i}"))
        assert len(tracker.get_all()) == 5


# ── get_stats ─────────────────────────────────────────────────────────────────

class TestGetStats:
    def test_stats_counts(self, tracker):
        tracker.upsert(_rec("j1", AppStatus.APPLIED.value))
        tracker.upsert(_rec("j2", AppStatus.FOUND.value))
        stats = tracker.get_stats()
        assert stats["total"] == 2
        assert stats["by_status"][AppStatus.APPLIED.value] == 1
        assert stats["by_status"][AppStatus.FOUND.value] == 1

    def test_stats_applied_today(self, tracker):
        tracker.upsert(_rec(
            status=AppStatus.APPLIED.value,
            applied_at=datetime.now(timezone.utc).isoformat()
        ))
        assert tracker.get_stats()["applied_today"] == 1

    def test_stats_all_statuses_present(self, tracker):
        stats = tracker.get_stats()
        for s in AppStatus:
            assert s.value in stats["by_status"]


# ── Schema validation ─────────────────────────────────────────────────────────

class TestSchema:
    def test_actions_table_does_not_exist(self, tracker):
        tables = {
            row[0]
            for row in tracker.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "actions" not in tables

    def test_applications_has_no_deprecated_columns(self, tracker):
        cols = {row[1] for row in tracker.conn.execute("PRAGMA table_info(applications)")}
        for deprecated in ("updated_at", "responded_at", "critic_verdict",
                           "resume_path", "apply_attempted", "error_msg", "decision"):
            assert deprecated not in cols, f"deprecated column still present: {deprecated}"

    def test_applications_has_hr_name(self, tracker):
        cols = {row[1] for row in tracker.conn.execute("PRAGMA table_info(applications)")}
        assert "hr_name" in cols

    def test_hr_conversations_has_new_schema(self, tracker):
        cols = {row[1] for row in tracker.conn.execute("PRAGMA table_info(hr_conversations)")}
        for expected in ("conv_id", "hr_name", "company", "job_id", "stage",
                         "boss_conv_id", "intent", "reply_status", "reply_text",
                         "last_msg_preview", "created_at"):
            assert expected in cols, f"missing column: {expected}"
        for deleted in ("messages", "status", "last_msg_text", "last_msg_from",
                        "last_synced", "needs_reply", "reply_draft", "suggested_reply"):
            assert deleted not in cols, f"deleted column still present: {deleted}"

    def test_hr_messages_table_exists_with_correct_columns(self, tracker):
        cols = {row[1] for row in tracker.conn.execute("PRAGMA table_info(hr_messages)")}
        for expected in ("id", "conv_id", "sender", "text", "msg_time", "created_at"):
            assert expected in cols, f"missing column in hr_messages: {expected}"


# ── HR Messages ───────────────────────────────────────────────────────────────

class TestHRMessages:
    def test_insert_and_get(self, tracker):
        msgs = [
            {"sender": "hr", "text": "你好", "time": "09:00"},
            {"sender": "me", "text": "您好", "time": "09:05"},
        ]
        count = tracker.insert_hr_messages("conv_001", msgs)
        assert count == 2
        result = tracker.get_hr_messages("conv_001")
        assert len(result) == 2
        assert result[0]["sender"] == "hr"
        assert result[1]["sender"] == "me"

    def test_insert_skips_duplicates(self, tracker):
        msgs = [{"sender": "hr", "text": "你好", "time": "09:00"}]
        tracker.insert_hr_messages("conv_001", msgs)
        count = tracker.insert_hr_messages("conv_001", msgs)
        assert count == 0  # duplicate skipped
        assert len(tracker.get_hr_messages("conv_001")) == 1

    def test_get_empty_for_unknown_conv(self, tracker):
        assert tracker.get_hr_messages("no_such_conv") == []

    def test_msg_time_from_time_key(self, tracker):
        msgs = [{"sender": "hr", "text": "hi", "time": "10:30"}]
        tracker.insert_hr_messages("c1", msgs)
        result = tracker.get_hr_messages("c1")
        assert result[0]["msg_time"] == "10:30"

    def test_get_hr_messages_bulk_matches_per_conv_calls(self, tracker):
        tracker.insert_hr_messages("c1", [
            {"sender": "hr", "text": "a", "time": "09:00"},
            {"sender": "me", "text": "b", "time": "09:05"},
        ])
        tracker.insert_hr_messages("c2", [{"sender": "hr", "text": "c", "time": "10:00"}])
        # c3 has no messages -- must still appear with an empty list, not be absent.
        result = tracker.get_hr_messages_bulk(["c1", "c2", "c3"])
        assert result["c1"] == tracker.get_hr_messages("c1")
        assert result["c2"] == tracker.get_hr_messages("c2")
        assert result["c3"] == []

    def test_get_hr_messages_bulk_empty_input(self, tracker):
        assert tracker.get_hr_messages_bulk([]) == {}


# ── Batch application lookup ─────────────────────────────────────────────────

class TestGetMany:
    def test_get_many_matches_individual_get(self, tracker):
        tracker.upsert(_rec("j1"))
        tracker.upsert(_rec("j2"))
        result = tracker.get_many(["j1", "j2", "missing"])
        assert set(result.keys()) == {"j1", "j2"}
        assert result["j1"].job_id == tracker.get("j1").job_id

    def test_get_many_empty_input(self, tracker):
        assert tracker.get_many([]) == {}
