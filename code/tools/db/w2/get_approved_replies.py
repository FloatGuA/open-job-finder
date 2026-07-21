from tools.base import BaseTool, ToolResult


class GetApprovedReplies(BaseTool):
    name = "get_approved_replies"
    description = "Fetch HR conversations whose reply is queued to send (approved or revision)."
    input_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, db) -> None:
        self._db = db

    def execute(self) -> ToolResult:
        rows = self._db.conn.execute(
            """
            SELECT conv_id, hr_name, company, reply_text, boss_conv_id
            FROM hr_conversations
            WHERE reply_status IN ('approved', 'revision')
            """,
        ).fetchall()
        conversations = [
            {
                "conv_id":      row[0],
                "hr_name":      row[1],
                "company":      row[2],
                "reply_text":   row[3],
                "boss_conv_id": row[4],
            }
            for row in rows
        ]
        return ToolResult(ok=True, data={"count": len(conversations), "conversations": conversations})
