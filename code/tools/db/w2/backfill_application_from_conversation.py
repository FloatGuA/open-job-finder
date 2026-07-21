from datetime import datetime, timezone

from tools.base import BaseTool, ToolResult

_JOB_URL = "https://www.zhipin.com/job_detail/"


class BackfillApplicationFromConversation(BaseTool):
    """Create an application row for every conversation that has a job_id but no
    matching application.

    The W2→W1 half of the two-table reconcile. A conversation with a job_id but no
    application means one of: the HR contacted us first (we never applied); we DID
    apply but the row was lost (the 150-applied/63-recorded undercount bug); or the
    application was purged. In every case we started (or are in) a real conversation
    for that job, so materialising an APPLIED application makes the two tables
    consistent and surfaces the job in the dashboard. APPLIED is correct here:
    APPLIED means "in conversation, up to INTERVIEW".

    Stub fields we can trust: job_id (the hard key), company + hr_name (from the
    conversation), and a url reconstructed from job_id. title is left empty (the
    friend-list API title isn't persisted on the conversation) and score NULL — a
    natural marker that this row was reconstructed, not scored-and-applied by W1.
    """

    name = "backfill_application_from_conversation"
    description = "Create APPLIED application rows for conversations that have a job_id but no application."
    input_schema = {"type": "object", "properties": {}, "required": []}

    def __init__(self, db) -> None:
        self._db = db

    def execute(self) -> ToolResult:
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._db.conn:
                cur = self._db.conn.execute(
                    """
                    INSERT INTO applications
                        (job_id, title, company, hr_name, url, status,
                         city, salary, score, applied_at, created_at)
                    SELECT hc.job_id, '', hc.company, hc.hr_name,
                           ? || hc.job_id || '.html', 'APPLIED',
                           '', '', NULL, ?, ?
                    FROM hr_conversations hc
                    WHERE hc.job_id IS NOT NULL AND hc.job_id != ''
                      AND NOT EXISTS (
                          SELECT 1 FROM applications a WHERE a.job_id = hc.job_id
                      )
                    """,
                    (_JOB_URL, now, now),
                )
            return ToolResult(ok=True, data={"backfilled_count": cur.rowcount})
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=str(exc))
