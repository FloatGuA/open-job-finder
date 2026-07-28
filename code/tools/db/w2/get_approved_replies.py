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
        # Thin shell over tracker.get_approved_replies() -- the ONE place this SELECT
        # lives (was a divergent inline copy that also dropped job_id). Serializing
        # job_id + boss_conv_id lets W3 direct-open the conversation
        # (navigate_to_conversation Treatment D, O(1)) instead of the slow search-box locate.
        rows = self._db.get_approved_replies()
        conversations = [
            {
                "conv_id":      c.conv_id,
                "hr_name":      c.hr_name,
                "company":      c.company,
                "reply_text":   c.reply_text,
                "boss_conv_id": c.boss_conv_id,
                "job_id":       c.job_id or "",
            }
            for c in rows
        ]
        return ToolResult(ok=True, data={"count": len(conversations), "conversations": conversations})
