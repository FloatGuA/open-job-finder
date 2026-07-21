# Task 002 — Application Tracker (SQLite State Machine)

## 目标
Implement the SQLite-backed application tracker with full state machine support and operation-level idempotency.

## 上下文
- 依赖：Task 001 (schemas.py, services/exceptions.py, services/logger.py)
- 代码目录：`C:/Coding/AI-factory-projects/open-job-finder/code/`

## 实现要求

### `services/tracker.py` — ApplicationTracker

Implement a class `ApplicationTracker` that manages all job application state in a SQLite database stored at `data/jobs.db` (relative to the code directory). Create the `data/` directory if it does not exist.

#### SQLite Schema

Create two tables on initialization:

**`applications` table:**
```sql
CREATE TABLE IF NOT EXISTS applications (
    job_id          TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    company         TEXT NOT NULL,
    url             TEXT NOT NULL,
    status          TEXT NOT NULL,
    score           INTEGER,
    decision        TEXT,
    critic_verdict  TEXT,
    resume_path     TEXT,
    applied_at      TEXT,
    responded_at    TEXT,
    error_msg       TEXT,
    apply_attempted INTEGER NOT NULL DEFAULT 0,  -- 0=False, 1=True
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
)
```

**`actions` table (idempotency log):**
```sql
CREATE TABLE IF NOT EXISTS actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      TEXT NOT NULL,
    action      TEXT NOT NULL,
    performed_at TEXT NOT NULL,
    UNIQUE(job_id, action)
)
```

#### Class Interface

```python
class ApplicationTracker:
    def __init__(self, db_path: str = "data/jobs.db"):
        """Initialize connection, create tables if not exist."""

    def exists(self, job_id: str) -> bool:
        """Return True if job_id exists in applications table."""

    def upsert(self, record: ApplicationRecord) -> None:
        """
        Insert or update an ApplicationRecord.
        On conflict (same job_id), update all fields except created_at.
        Always update updated_at to current ISO8601 timestamp.
        """

    def get(self, job_id: str) -> Optional[ApplicationRecord]:
        """Return ApplicationRecord for job_id, or None if not found."""

    def count_today(self) -> int:
        """
        Count jobs with status=APPLIED and applied_at on today's date (UTC).
        Used for daily limit enforcement.
        """

    def get_all(self) -> List[ApplicationRecord]:
        """Return all records, ordered by created_at DESC."""

    def get_by_status(self, status: AppStatus) -> List[ApplicationRecord]:
        """Return all records with a specific status."""

    def get_pending_responses(self) -> List[ApplicationRecord]:
        """
        Return records where status=APPLIED and apply_attempted=True.
        These are candidates for response checking.
        """

    def has_action(self, job_id: str, action: str) -> bool:
        """Return True if (job_id, action) exists in actions table."""

    def mark_action(self, job_id: str, action: str) -> None:
        """
        Insert (job_id, action, now) into actions table.
        If already exists (UNIQUE constraint), ignore (idempotent).
        """

    def update_status(self, job_id: str, new_status: AppStatus, **extra_fields) -> None:
        """
        Shortcut to update just the status field (and any extra_fields like
        applied_at, error_msg, etc.). Calls upsert internally after get().
        """

    def get_stats(self) -> dict:
        """
        Return summary counts:
        {
          "total": int,
          "by_status": {"DISCOVERED": N, "APPLIED": N, ...},
          "applied_today": int,
          "responded": int,
          "interviews": int,
          "offers": int
        }
        """

    def close(self) -> None:
        """Close the SQLite connection."""
```

#### Implementation Notes

- Use `sqlite3.connect(db_path, check_same_thread=False)` for the connection.
- Enable WAL mode: `conn.execute("PRAGMA journal_mode=WAL")`.
- All methods that write to the DB should use a context manager (`with self.conn:`) to auto-commit/rollback.
- `updated_at` is always set to `datetime.utcnow().isoformat()` on every write.
- `created_at` is set on first insert only.
- Map Python `bool` to SQLite `INTEGER` (0/1) for `apply_attempted`.
- Row factory: use `sqlite3.Row` to allow column-name access.
- Log all state transitions (old_status → new_status) at INFO level using `get_orchestrator_logger()`.

#### State Machine Validation

Add a method `_validate_transition(old_status: str, new_status: str) -> bool` that checks transitions against the valid state graph:

```
DISCOVERED → SCANNED, ERROR
SCANNED    → SCORED, ERROR
SCORED     → APPLIED, ERROR  (skip is handled at orchestrator level, not stored)
APPLIED    → RESPONDED, REJECTED, ERROR
RESPONDED  → INTERVIEW, REJECTED, ERROR
INTERVIEW  → OFFER, REJECTED, ERROR
```

If an invalid transition is attempted, log a WARNING but **do not raise** — still allow the update (for flexibility during debugging).

## 文件清单

- `code/services/tracker.py`：ApplicationTracker class

## Smoke Test

```bash
cd C:/Coding/AI-factory-projects/open-job-finder/code

python -c "
import os, datetime
# Clean up test DB
if os.path.exists('data/test_tracker.db'):
    os.remove('data/test_tracker.db')

from schemas import ApplicationRecord, AppStatus
from services.tracker import ApplicationTracker

tracker = ApplicationTracker(db_path='data/test_tracker.db')

# Test upsert + exists
now = datetime.datetime.utcnow().isoformat()
record = ApplicationRecord(
    job_id='test_001',
    title='Python Engineer',
    company='Test Corp',
    url='https://example.com/job/1',
    status=AppStatus.DISCOVERED.value,
    created_at=now,
    updated_at=now
)
tracker.upsert(record)
assert tracker.exists('test_001'), 'exists() failed'

# Test status update
tracker.update_status('test_001', AppStatus.SCANNED)
got = tracker.get('test_001')
assert got.status == AppStatus.SCANNED.value, f'Expected SCANNED, got {got.status}'

# Test idempotency
tracker.mark_action('test_001', 'apply_attempted')
tracker.mark_action('test_001', 'apply_attempted')  # should not raise
assert tracker.has_action('test_001', 'apply_attempted'), 'has_action() failed'

# Test count_today (0 since not APPLIED yet)
assert tracker.count_today() == 0, 'count_today should be 0'

# Test stats
stats = tracker.get_stats()
assert stats['total'] == 1
print('tracker OK, stats:', stats)

tracker.close()
os.remove('data/test_tracker.db')
"
```

<!-- FACTORY:DONE -->
