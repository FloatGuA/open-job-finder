from typing import List, Optional

from tools.base import BaseTool, ToolResult

# \u7b80\u5386 = \u7b80\u5386,  [\u5361\u7247] = [\u5361\u7247]
_RESUME_KW = "\u7b80\u5386"
_CARD_PFX = "[\u5361\u7247]"
# U+9644 U+4EF6 U+7B80 U+5386 -- the keyword Boss puts in the system bubble once a
# resume has actually been delivered (both send paths). This is the single source of
# truth shared with the send tools' success check (see helpers.count_resume_delivered_markers).
_DELIVERED_KW = "\u9644\u4ef6\u7b80\u5386"


class DetectResumeRequest(BaseTool):
    name = "detect_resume_request"
    description = "Detect if HR has requested a resume and whether one has already been sent."
    input_schema = {
        "type": "object",
        "properties": {
            "messages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "sender": {"type": "string"},
                        "text": {"type": "string"},
                    },
                    "required": ["sender", "text"],
                },
            },
        },
        "required": ["messages"],
    }

    def execute(self, *, messages: List[dict]) -> ToolResult:
        # already_sent is anchored on the SAME single source of truth the send tools use:
        # Boss posts a SYSTEM bubble containing _DELIVERED_KW once a resume is actually
        # delivered, on BOTH send paths (mainland "...delivered to Boss", cross-border
        # "request sent"/"preview ..."). Restricted to sender=="system" on purpose: an
        # HR's own card request ALSO contains _DELIVERED_KW ("I'd like your attachment-
        # resume"), and a "me" text like "here is my resume" is not proof of an actual
        # attachment delivery -- only the system bubble is.
        already_sent = any(
            msg.get("sender") == "system" and _DELIVERED_KW in msg.get("text", "")
            for msg in messages
        )

        request_type: Optional[str] = None
        for msg in messages:
            sender = msg.get("sender", "")
            text = msg.get("text", "")
            if sender == "system" and _RESUME_KW in text:
                request_type = "system_notification"
                break
            if sender == "hr" and text.startswith(_CARD_PFX) and _RESUME_KW in text:
                request_type = "hr_card"
                break
            if sender == "hr" and (_RESUME_KW in text or "resume" in text.lower()):
                request_type = "hr_text"
                break

        needs_resume = request_type is not None and not already_sent

        return ToolResult(
            ok=True,
            data={
                "needs_resume": needs_resume,
                "request_type": request_type,
                "already_sent": already_sent,
            },
        )
