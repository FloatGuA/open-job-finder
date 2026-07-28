from tools.base import BaseTool, ToolResult


class GetQueuedResumes(BaseTool):
    name = "get_queued_resumes"
    description = "Fetch HR conversations the user manually staged for a resume send (resume_status='queued')."
    input_schema = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, db) -> None:
        self._db = db

    def execute(self) -> ToolResult:
        # Thin shell over tracker.get_queued_resumes() -- the ONE place this SELECT
        # lives. job_id + boss_conv_id let W3 direct-open (navigate_to_conversation
        # Treatment D, O(1)) instead of the slow search-box locate.
        rows = self._db.get_queued_resumes()
        conversations = [
            {
                "conv_id":      c.conv_id,
                "hr_name":      c.hr_name,
                "company":      c.company,
                "boss_conv_id": c.boss_conv_id,
                "job_id":       c.job_id or "",
                "hr_title":     c.hr_title or "",
                "last_msg_preview": c.last_msg_preview or "",
            }
            for c in rows
        ]
        return ToolResult(ok=True, data={"count": len(conversations), "conversations": conversations})
