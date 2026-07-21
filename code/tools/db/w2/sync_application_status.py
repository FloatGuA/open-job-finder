from tools.base import BaseTool, ToolResult


class SyncApplicationStatusFromConversations(BaseTool):
    name = "sync_application_status_from_conversations"
    description = "Batch-update application statuses based on hr_conversations.stage."
    input_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, db) -> None:
        self._db = db

    def execute(self) -> ToolResult:
        # Hard association: join on job_id (== Boss encryptJobId, shared by both
        # tables) whenever the conversation carries one — this is the reliable key.
        # Fall back to the legacy hr_name + company soft join ONLY for conversations
        # that still have no job_id (rare: DOM-fallback scans / pre-migration rows).
        #
        # REJECTED means only an EXPLICIT HR rejection (intent='rejection'): a merely
        # stalled/soft-closed conversation (mark_timeout sets stage='closed' without
        # touching intent) must NOT reject the application — applying needs no HR reply.
        #
        # Revival: if the application is already REJECTED but its conversation is active
        # again (HR re-engaged → stage overwritten back to a non-terminal value), restore
        # it to APPLIED so the two state machines stay consistent. sync is raw SQL, so it
        # can move REJECTED→APPLIED without the transition guard.
        with self._db.conn:
            cur = self._db.conn.execute(
                """
                UPDATE applications
                SET status = CASE
                    WHEN hc.stage = 'interview' THEN 'INTERVIEWING'
                    WHEN hc.stage = 'offer'     THEN 'OFFER'
                    WHEN hc.stage = 'closed' AND hc.intent = 'rejection' THEN 'REJECTED'
                    WHEN applications.status = 'REJECTED'
                         AND hc.stage NOT IN ('closed', 'offer') THEN 'APPLIED'
                    ELSE applications.status
                END
                FROM hr_conversations hc
                WHERE (
                        (hc.job_id IS NOT NULL AND hc.job_id != ''
                         AND applications.job_id = hc.job_id)
                        OR
                        ((hc.job_id IS NULL OR hc.job_id = '')
                         AND applications.hr_name = hc.hr_name
                         AND applications.company = hc.company)
                      )
                  AND (
                        hc.stage IN ('interview', 'offer')
                        OR (hc.stage = 'closed' AND hc.intent = 'rejection')
                        OR (applications.status = 'REJECTED'
                            AND hc.stage NOT IN ('closed', 'offer'))
                      )
                """
            )
        return ToolResult(ok=True, data={"updated_count": cur.rowcount})
