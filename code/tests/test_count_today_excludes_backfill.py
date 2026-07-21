"""count_today must count only genuine W1 applies (score set), not backfill
reconstructions (score NULL, applied_at=now) — those inflated 147 vs the real ~51."""
from datetime import datetime, timezone

from services.tracker import ApplicationTracker


def _insert_app(t, job_id, *, score, applied_at):
    with t.conn:
        t.conn.execute(
            "INSERT INTO applications (job_id, title, company, url, status, city, salary, score, applied_at, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (job_id, "T", "C", f"u/{job_id}", "APPLIED", "", "", score, applied_at, applied_at),
        )


def test_count_today_excludes_score_null_backfill(tmp_path):
    t = ApplicationTracker(db_path=str(tmp_path / "jobs.db"))
    try:
        today = datetime.now(timezone.utc).date().isoformat() + "T05:00:00+00:00"
        # genuine W1 applies (real score, and threshold<=0 score=0) -> counted
        _insert_app(t, "g1", score=72, applied_at=today)
        _insert_app(t, "g2", score=0, applied_at=today)
        # backfill reconstructions (score NULL) -> NOT counted
        _insert_app(t, "b1", score=None, applied_at=today)
        _insert_app(t, "b2", score=None, applied_at=today)
        assert t.count_today() == 2
    finally:
        t.close()
