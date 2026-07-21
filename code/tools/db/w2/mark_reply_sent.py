from tools.base import BaseTool, ToolResult


class MarkReplySent(BaseTool):
    name = "mark_reply_sent"
    description = "Mark a conversation's reply as sent (reply_status='sent', clears the draft)."
    input_schema = {
        "type": "object",
        "properties": {"conv_id": {"type": "string"}},
        "required": ["conv_id"],
    }

    def __init__(self, db) -> None:
        self._db = db

    def execute(self, *, conv_id: str) -> ToolResult:
        # An authoritative state transition after a successful send -- NOT the
        # re-analysis path. It must force reply_status to 'sent' regardless of the
        # current status (update_hr_analysis intentionally protects 'approved' and
        # other decided states from re-analysis, so it cannot be used here). 'sent'
        # is itself a protected status, so later re-analysis won't revive the reply.
        with self._db.conn:
            cur = self._db.conn.execute(
                "UPDATE hr_conversations SET reply_status = 'sent', reply_text = '' WHERE conv_id = ?",
                (conv_id,),
            )
        return ToolResult(ok=True, data={"updated": cur.rowcount})
