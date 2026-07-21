from typing import Optional

from services.tracker import ALLOWED_REPLY_STATUSES
from tools.base import BaseTool, ToolResult


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
        # Guard belongs here, not in tracker: this tool is how the RE-ANALYSIS path
        # writes, and re-analysis must never be able to hand itself a decided status
        # (approved/dismissed/revision). Those are reached only through their own
        # explicit transitions. tracker stays unrestricted because approve/dismiss
        # flows and test fixtures legitimately set them.
        if reply_status not in ALLOWED_REPLY_STATUSES:
            return ToolResult(
                ok=False,
                data={},
                error=f"reply_status must be one of {ALLOWED_REPLY_STATUSES}, got: {reply_status!r}",
            )

        # The write itself (protected-status CASE, watermark MAX) lives in tracker,
        # which is the single owner of this transition. This tool adds the ToolResult
        # contract that gives registry.call its trace/SSE. Two implementations existed
        # before and had drifted -- the tracker copy lacked the last_analyzed_ts
        # watermark entirely, so wiring it up would have silently reverted #53.
        self._db.update_hr_analysis(
            conv_id,
            intent,
            reply_text=reply_text,
            reply_status=reply_status,
            last_analyzed_ts=last_analyzed_ts,
        )
        return ToolResult(ok=True, data={})
