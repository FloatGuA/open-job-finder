from typing import List, Optional

from tools.base import BaseTool, ToolResult


class GenerateReply(BaseTool):
    """Draft a reply to HR. Runs with think=True so the model deliberates over
    wording — unlike intent classification (analyze_hr_intent), which uses
    think=False for speed and direct judgment. Only called when analysis says a
    reply is needed."""

    name = "generate_reply"
    capability = "balanced"
    description = "Draft a reply to HR, deliberating over wording (think=true)."
    input_schema = {
        "type": "object",
        "properties": {
            "conv_id":   {"type": "string"},
            "messages":  {"type": "array"},
            "company":   {"type": "string"},
            "intent":    {"type": "string"},
            "job_title": {"type": "string"},
        },
        "required": ["conv_id", "messages", "company"],
    }

    def __init__(self, llm_client, prompt_manager, provider_name: str = None) -> None:
        self._llm = llm_client
        self._pm = prompt_manager
        self._provider_name = provider_name

    def execute(
        self,
        *,
        conv_id: str,
        messages: List[dict],
        company: str,
        intent: str = "unknown",
        job_title: Optional[str] = None,
    ) -> ToolResult:
        recent = messages[-5:]
        msg_lines = [
            f"[{m.get('sender', '')}] {m.get('text', '')}"
            for m in recent
        ]
        context = {
            "company": company,
            "job_title": job_title or "",
            "intent": intent or "unknown",
            "messages": "\n".join(msg_lines) if msg_lines else "(no messages)",
        }

        try:
            prompt = self._pm.render("generate_reply", context)
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=f"prompt render error: {exc}")

        try:
            # think=True: reply drafting deliberates over wording. No system prompt —
            # the template is self-contained and the job-agent system ("return ONLY
            # JSON") would fight this plain-text reply. No output_schema: the reply is
            # free text, not a JSON shape.
            reply_text, provider_name = self._llm.complete(
                prompt,
                system="",
                capability=self.capability,
                provider_name=self._provider_name,
                think=True,
            )
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=str(exc))

        reply_text = (reply_text or "").strip()
        if not reply_text:
            return ToolResult(ok=False, data={}, error="empty reply generated")

        return ToolResult(
            ok=True,
            data={
                "suggested_reply": reply_text,
                "provider_used": provider_name,
            },
        )
