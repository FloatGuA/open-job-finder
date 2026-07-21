"""upsert_application: applied_at means LAST applied, not first.

Every consumer reads it that way -- count_today counts rows whose applied_at is
today, purge_stale_applications ages rows out by it, find_application_by_company
orders by it. The tool used to keep the original value, so a REJECTED job
re-applied today (an intentional flow: postings reopen, and both dedup layers
deliberately exclude REJECTED) neither counted toward today's total nor reset its
staleness clock.

Found by the live smoke: it applied for real, count_today did not move, and the
assertion went red -- exactly the "applied but not recorded" class it exists for.
"""
import sqlite3

import pytest

from tools.db.w1.upsert_application import UpsertApplication


class _DB:
    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute(
            """
            CREATE TABLE applications (
                job_id TEXT PRIMARY KEY, title TEXT, company TEXT, hr_name TEXT,
                url TEXT, status TEXT, city TEXT, salary TEXT, score INTEGER,
                applied_at TEXT, content_hash TEXT, created_at TEXT
            )
            """
        )
        self.conn.commit()


@pytest.fixture
def db(tmp_path):
    return _DB(tmp_path / "t.db")


def _apply(tool, job_id="j1", status="APPLIED", applied_at=None, score=None, **kw):
    return tool.execute(job_id=job_id, title="T", company="C", status=status,
                        applied_at=applied_at, score=score, **kw)


def _row(db, job_id="j1"):
    return db.conn.execute("SELECT * FROM applications WHERE job_id=?", (job_id,)).fetchone()


def test_reapplying_updates_applied_at(db):
    """The regression: a job applied 11 days ago, rejected, then re-applied today
    must carry today's timestamp."""
    tool = UpsertApplication(db)
    _apply(tool, applied_at="2026-07-10T06:29:29+00:00", score=81)
    _apply(tool, status="REJECTED", applied_at="2026-07-10T06:29:29+00:00")

    _apply(tool, applied_at="2026-07-21T19:07:15+00:00", score=81)

    assert _row(db)["applied_at"] == "2026-07-21T19:07:15+00:00"
    assert _row(db)["status"] == "APPLIED"


def test_omitting_applied_at_does_not_blank_it(db):
    """Callers that only update, say, hr_name must not wipe the timestamp."""
    tool = UpsertApplication(db)
    _apply(tool, applied_at="2026-07-10T06:29:29+00:00")

    _apply(tool, applied_at=None, hr_name="HR")

    assert _row(db)["applied_at"] == "2026-07-10T06:29:29+00:00"
    assert _row(db)["hr_name"] == "HR"


def test_score_is_preserved_when_not_supplied(db):
    """W2's backfill writes rows without a score; it must not erase a real one."""
    tool = UpsertApplication(db)
    _apply(tool, applied_at="2026-07-10T00:00:00+00:00", score=81)

    _apply(tool, applied_at="2026-07-21T00:00:00+00:00", score=None)

    assert _row(db)["score"] == 81


def test_first_apply_inserts(db):
    tool = UpsertApplication(db)
    res = _apply(tool, applied_at="2026-07-21T00:00:00+00:00", score=70)
    assert res.ok
    assert _row(db)["score"] == 70
    assert _row(db)["applied_at"] == "2026-07-21T00:00:00+00:00"
