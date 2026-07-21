from datetime import datetime, timezone
from typing import Optional

from tools.base import BaseTool, ToolResult


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class UpsertApplication(BaseTool):
    name = "upsert_application"
    description = "Insert or update an application row in the applications table."
    input_schema = {
        "type": "object",
        "properties": {
            "job_id":     {"type": "string"},
            "title":      {"type": "string"},
            "company":    {"type": "string"},
            "hr_name":    {"type": "string"},
            "url":        {"type": "string"},
            "status":     {"type": "string"},
            "city":       {"type": "string"},
            "salary":     {"type": "string"},
            "score":      {"type": "integer"},
            "applied_at": {"type": "string"},
            "content_hash": {"type": "string"},
        },
        "required": ["job_id", "title", "company", "status"],
    }

    def __init__(self, db) -> None:
        self._db = db

    def execute(
        self,
        *,
        job_id: str,
        title: str,
        company: str,
        status: str,
        hr_name: Optional[str] = None,
        url: Optional[str] = None,
        city: Optional[str] = None,
        salary: Optional[str] = None,
        score: Optional[int] = None,
        applied_at: Optional[str] = None,
        content_hash: Optional[str] = None,
    ) -> ToolResult:
        now = _utcnow_iso()
        try:
            with self._db.conn:
                self._db.conn.execute(
                    """
                    INSERT INTO applications
                        (job_id, title, company, hr_name, url, status,
                         city, salary, score, applied_at, content_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id) DO UPDATE SET
                        title      = excluded.title,
                        company    = excluded.company,
                        content_hash = CASE WHEN excluded.content_hash IS NOT NULL
                                          THEN excluded.content_hash ELSE content_hash END,
                        hr_name    = CASE WHEN excluded.hr_name IS NOT NULL
                                          THEN excluded.hr_name ELSE hr_name END,
                        url        = CASE WHEN excluded.url IS NOT NULL
                                          THEN excluded.url ELSE url END,
                        status     = excluded.status,
                        city       = CASE WHEN excluded.city IS NOT NULL AND excluded.city != ''
                                          THEN excluded.city ELSE city END,
                        salary     = CASE WHEN excluded.salary IS NOT NULL AND excluded.salary != ''
                                          THEN excluded.salary ELSE salary END,
                        score      = CASE WHEN excluded.score IS NOT NULL
                                          THEN excluded.score ELSE score END,
                        -- applied_at means LAST applied, not first. Every consumer
                        -- reads it that way: count_today counts rows whose
                        -- applied_at is today, purge_stale_applications ages rows
                        -- out by it, find_application_by_company orders by it.
                        -- Keeping the original value meant a REJECTED job re-applied
                        -- today (an intentional flow -- postings reopen) neither
                        -- counted toward today's total nor reset its staleness clock,
                        -- so it could be purged on the strength of an apply that had
                        -- since been superseded. NULL still leaves the stored value
                        -- alone, so callers that omit it cannot blank it.
                        applied_at = CASE WHEN excluded.applied_at IS NOT NULL
                                          THEN excluded.applied_at ELSE applications.applied_at END
                    """,
                    (
                        job_id, title, company, hr_name, url, status,
                        city, salary, score, applied_at, content_hash, now,
                    ),
                )
            return ToolResult(ok=True, data={"status": status})
        except Exception as exc:
            return ToolResult(ok=False, data={"status": status}, error=str(exc))
