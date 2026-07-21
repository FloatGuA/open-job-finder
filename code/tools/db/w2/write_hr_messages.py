from typing import List

from tools.base import BaseTool, ToolResult


class WriteHRMessages(BaseTool):
    name = "write_hr_messages"
    description = "Persist a batch of HR conversation messages, skipping duplicates."
    input_schema = {
        "type": "object",
        "properties": {
            "conv_id": {"type": "string"},
            "messages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "sender": {"type": "string"},
                        "text":   {"type": "string"},
                        "time":   {"type": "string"},
                    },
                    "required": ["sender", "text"],
                },
            },
        },
        "required": ["conv_id", "messages"],
    }

    def __init__(self, db) -> None:
        self._db = db

    def execute(self, *, conv_id: str, messages: List[dict]) -> ToolResult:
        # Delegate to the tracker's single source of truth. The previous inline
        # INSERT omitted the NOT NULL `created_at` column, so every row was
        # silently dropped by INSERT OR IGNORE (inserted_count always 0).
        inserted = self._db.insert_hr_messages(conv_id, messages)
        return ToolResult(ok=True, data={"inserted_count": inserted})
