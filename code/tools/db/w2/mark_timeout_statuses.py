from tools.base import BaseTool, ToolResult


class MarkTimeoutStatuses(BaseTool):
    # Registry key kept as "mark_timeout_rejections" for back-compat; it no longer
    # rejects applications. Applying does not need an HR reply, so "no reply after
    # applying" is NOT a rejection — the application status is left untouched here.
    # This tool now only puts a soft STALL marker on conversations (stage='closed')
    # after `no_response_days` of no new message, purely as a reminder signal. closed
    # no longer drags the application to REJECTED (sync only rejects intent='rejection');
    # a stalled conversation revives (stage overwritten) when HR messages again, and the
    # whole job is cleaned up by the 30-day purge if nothing progresses.
    name = "mark_timeout_rejections"
    description = "Soft-mark conversations stalled after N days of no new message (stage='closed')."
    input_schema = {
        "type": "object",
        "properties": {
            "no_response_days": {"type": "integer"},
            "stale_conv_days":  {"type": "integer"},
        },
        "required": [],
    }

    def __init__(self, db) -> None:
        self._db = db

    def execute(
        self,
        *,
        no_response_days: int = 14,
        stale_conv_days: int = 30,
    ) -> ToolResult:
        # `stale_conv_days` is accepted for signature back-compat but unused here — the
        # 30-day threshold now drives the separate purge step, not conversation close.
        with self._db.conn:
            # Stall marker: a conversation with no new message for `no_response_days`
            # (keyed off the last recorded message; falls back to created_at when the
            # conversation has no messages) is moved to stage='closed'. Terminal stages
            # (already closed / offer) are left alone.
            cur_convs = self._db.conn.execute(
                """
                UPDATE hr_conversations
                SET stage = 'closed'
                WHERE stage NOT IN ('closed', 'offer')
                  AND COALESCE(
                        (SELECT MAX(m.created_at) FROM hr_messages m
                         WHERE m.conv_id = hr_conversations.conv_id),
                        created_at
                      ) <= datetime('now', ? || ' days')
                RETURNING conv_id
                """,
                (f"-{no_response_days}",),
            )
            stale_closed = [row[0] for row in cur_convs.fetchall()]

        return ToolResult(
            ok=True,
            data={
                "stale_closed_count": len(stale_closed),
                "stale_closed": stale_closed,
            },
        )
