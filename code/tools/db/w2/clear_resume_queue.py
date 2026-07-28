from tools.base import BaseTool, ToolResult


class ClearResumeQueue(BaseTool):
    name = "clear_resume_queue"
    description = "Clear a conversation's manual resume-queue flag (resume_status -> NULL) after W3 delivered it."
    input_schema = {
        "type": "object",
        "properties": {"conv_id": {"type": "string"}},
        "required": ["conv_id"],
    }

    def __init__(self, db) -> None:
        self._db = db

    def execute(self, *, conv_id: str) -> ToolResult:
        # Thin shell over tracker.set_resume_status(conv_id, None) -- NULL is the
        # correct neutral after delivery (the sent fact is recorded by
        # stage=resume_sent, not here). Single SQL lives in tracker.
        rows = self._db.set_resume_status(conv_id, None)
        return ToolResult(ok=True, data={"cleared": rows})
