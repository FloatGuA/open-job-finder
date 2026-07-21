from typing import Optional

from tools.base import BaseTool, ToolResult

# Statuses that reflect a user/system decision and must NOT be clobbered when W2
# re-analyzes a conversation: 'approved' (user OK'd the reply), 'revision' (user
# edited it), 'dismissed' (user declined), 'sent' (already delivered). Only null/
# 'pending' are freely refreshed by re-analysis. Both reply_text AND reply_status
# are protected for these statuses (an earlier version omitted 'approved' and left
# reply_text unprotected, so re-analysis could downgrade approved->pending and
# overwrite a user-revised draft).
_PROTECTED_STATUSES = frozenset({"approved", "sent", "dismissed", "revision"})
_PROTECTED_SQL = ", ".join(f"'{s}'" for s in sorted(_PROTECTED_STATUSES))
_ALLOWED_REPLY_STATUSES = frozenset({None, "pending", "sent"})


class UpdateHRAnalysis(BaseTool):
    name = "update_hr_analysis"
    description = "Write LLM analysis results back to hr_conversations; never overwrites terminal reply_status."
    input_schema = {
        "type": "object",
        "properties": {
            "conv_id":      {"type": "string"},
            "intent":       {"type": "string"},
            "reply_text":   {"type": ["string", "null"]},
            "reply_status": {"type": ["string", "null"]},
            "last_analyzed_ts": {"type": ["integer", "null"]},
        },
        "required": ["conv_id", "intent"],
    }

    def __init__(self, db) -> None:
        self._db = db

    def execute(
        self,
        *,
        conv_id: str,
        intent: str,
        reply_text: Optional[str] = None,
        reply_status: Optional[str] = None,
        last_analyzed_ts: Optional[int] = None,
    ) -> ToolResult:
        if reply_status not in _ALLOWED_REPLY_STATUSES:
            return ToolResult(
                ok=False,
                data={},
                error=f"reply_status must be one of {_ALLOWED_REPLY_STATUSES}, got: {reply_status!r}",
            )

        # NOTE: hr_conversations has no `updated_at` column (T030 schema keeps only
        # created_at). An earlier version wrote `updated_at = ?` here, which made
        # every call raise "no such column: updated_at" -- so analysis results were
        # never persisted. Do not re-add it without adding the column.
        # last_analyzed_ts: the dirty-check watermark. Advanced ONLY when this is
        # called (i.e. analyze succeeded / concluded) -- a DEGRADED analyze never
        # reaches update_hr_analysis, so the watermark stays behind and
        # filter_conversations re-selects the conversation next run. MAX guards
        # against an out-of-order regress; NULL leaves it untouched.
        with self._db.conn:
            self._db.conn.execute(
                f"""
                UPDATE hr_conversations SET
                    intent       = ?,
                    reply_text   = CASE
                        WHEN reply_status IN ({_PROTECTED_SQL}) THEN reply_text
                        WHEN ? IS NOT NULL THEN ?
                        ELSE reply_text
                    END,
                    reply_status = CASE
                        WHEN reply_status IN ({_PROTECTED_SQL}) THEN reply_status
                        WHEN ? IS NOT NULL THEN ?
                        ELSE reply_status
                    END,
                    last_analyzed_ts = CASE
                        WHEN ? IS NULL THEN last_analyzed_ts
                        ELSE MAX(last_analyzed_ts, ?)
                    END
                WHERE conv_id = ?
                """,
                (intent, reply_text, reply_text, reply_status, reply_status,
                 last_analyzed_ts, last_analyzed_ts, conv_id),
            )
        return ToolResult(ok=True, data={})
