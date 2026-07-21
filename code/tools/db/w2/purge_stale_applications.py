from tools.base import BaseTool, ToolResult

# Statuses with real progress are NEVER purged, no matter how old — an interview or
# offer must not be silently deleted. Everything else (APPLIED / REJECTED / stalled /
# legacy) is fair game once it has been sitting untouched past the purge horizon.
_PROTECTED_STATUSES = ("INTERVIEWING", "OFFER")


class PurgeStaleApplications(BaseTool):
    name = "purge_stale_applications"
    description = (
        "Delete applications (and their conversations + messages) older than N days "
        "with no real progress, so the job re-runs from scratch when it resurfaces."
    )
    input_schema = {
        "type": "object",
        "properties": {"days": {"type": "integer"}},
        "required": [],
    }

    def __init__(self, db) -> None:
        self._db = db

    def execute(self, *, days: int = 30) -> ToolResult:
        # Auto-revive by cleanup: a job applied more than `days` ago with no progress is
        # wiped — application row + its HR conversation(s) + messages (linked by
        # hr_name + company, the same scheme sync/mark_timeout use). Once gone, classify
        # finds nothing and the posting re-runs the full W1 pipeline the next time it
        # shows up in search. Protected statuses (interview/offer) are kept regardless.
        placeholders = ",".join("?" * len(_PROTECTED_STATUSES))
        victims = self._db.conn.execute(
            f"""
            SELECT job_id, hr_name, company FROM applications
            WHERE applied_at IS NOT NULL
              AND applied_at <= datetime('now', ? || ' days')
              AND status NOT IN ({placeholders})
            """,
            (f"-{days}", *_PROTECTED_STATUSES),
        ).fetchall()

        job_ids = [row["job_id"] for row in victims]
        pairs = {(row["hr_name"], row["company"]) for row in victims}

        with self._db.conn:
            for hr_name, company in pairs:
                self._db.conn.execute(
                    """
                    DELETE FROM hr_messages WHERE conv_id IN (
                        SELECT conv_id FROM hr_conversations
                        WHERE hr_name = ? AND company = ?
                    )
                    """,
                    (hr_name, company),
                )
                self._db.conn.execute(
                    "DELETE FROM hr_conversations WHERE hr_name = ? AND company = ?",
                    (hr_name, company),
                )
            for job_id in job_ids:
                self._db.conn.execute(
                    "DELETE FROM applications WHERE job_id = ?", (job_id,)
                )

        return ToolResult(
            ok=True,
            data={"purged_count": len(job_ids), "purged": job_ids},
        )
