from typing import List

from tools.base import BaseTool, ToolResult


class GetConversationStates(BaseTool):
    name = "get_conversation_states"
    description = "Batch-fetch last_msg_preview, stage and last_msg_ts for a list of conversation IDs."
    input_schema = {
        "type": "object",
        "properties": {
            "conv_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["conv_ids"],
    }

    def __init__(self, db) -> None:
        self._db = db

    def execute(self, *, conv_ids: List[str]) -> ToolResult:
        if not conv_ids:
            return ToolResult(ok=True, data={"state_count": 0, "states": {}})

        placeholders = ",".join("?" for _ in conv_ids)
        rows = self._db.conn.execute(
            f"SELECT conv_id, last_msg_preview, stage, last_msg_ts, intent, last_analyzed_ts "
            f"FROM hr_conversations WHERE conv_id IN ({placeholders})",
            conv_ids,
        ).fetchall()

        states = {
            row[0]: {
                "last_msg_preview": row[1] or "",
                "stage": row[2] or "",
                "last_msg_ts": row[3] or 0,
                "intent": row[4] or "",
                "last_analyzed_ts": row[5] or 0,
            }
            for row in rows
        }
        return ToolResult(ok=True, data={"state_count": len(states), "states": states})
