import time

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
        # Staleness is measured from when the HR last SPOKE (last_msg_ts, the real
        # millisecond timestamp from getGeekFriendList), not from when we happened to
        # write the message to our DB. hr_messages.created_at is insert time: the
        # first time we scan a months-old thread every one of its messages gets
        # today's created_at, so the thread looked freshly active and was never
        # soft-closed.
        #
        # This also aligns the two clocks. filter_conversations' too_old gate already
        # uses last_msg_ts to decide "don't process"; using a different clock here to
        # decide "soft-close" left conversations that were skipped as stale yet never
        # marked as such -- permanently pending, invisible to both.
        #
        # last_msg_ts == 0 (DOM-fallback / pre-migration rows) keeps the old
        # insert-time behaviour: an unknown real time is better served by a rough
        # signal than by treating the row as infinitely old.
        cutoff_ms = int((time.time() - no_response_days * 86400) * 1000)
        with self._db.conn:
            cur_convs = self._db.conn.execute(
                """
                UPDATE hr_conversations
                SET stage = 'closed'
                WHERE stage NOT IN ('closed', 'offer')
                  AND CASE
                        WHEN COALESCE(last_msg_ts, 0) > 0 THEN last_msg_ts <= ?
                        ELSE COALESCE(
                               (SELECT MAX(m.created_at) FROM hr_messages m
                                WHERE m.conv_id = hr_conversations.conv_id),
                               created_at
                             ) <= datetime('now', ? || ' days')
                      END
                RETURNING conv_id
                """,
                (cutoff_ms, f"-{no_response_days}"),
            )
            stale_closed = [row[0] for row in cur_convs.fetchall()]

        return ToolResult(
            ok=True,
            data={
                "stale_closed_count": len(stale_closed),
                "stale_closed": stale_closed,
            },
        )
