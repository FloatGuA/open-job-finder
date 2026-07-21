from typing import List, Optional

from services.exceptions import LLMParseError
from services.llm_parser import safe_parse_json
from tools.base import BaseTool, ToolResult

_VALID_INTENTS = frozenset({
    "interview_invite", "offer", "rejection",
    "resume_request", "general", "unknown",
})

# JSON Schema for the model's answer. Passed to the LLM chain so providers that
# support structured output constrain their JSON: ollama via `format`. Others
# ignore it; safe_parse_json remains the safety net. Intent classification only —
# the reply draft is a separate think=True call (GenerateReply), so no
# suggested_reply here.
_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": sorted(_VALID_INTENTS)},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "needs_reply": {"type": "boolean"},
    },
    "required": ["intent"],
}


class AnalyzeHRIntent(BaseTool):
    name = "analyze_hr_intent"
    capability = "balanced"
    description = "Analyze HR messages to determine intent and suggest a reply."
    input_schema = {
        "type": "object",
        "properties": {
            "conv_id":   {"type": "string"},
            "messages":  {"type": "array"},
            "company":   {"type": "string"},
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
            "messages": "\n".join(msg_lines) if msg_lines else "(no messages)",
        }

        try:
            prompt = self._pm.render("analyze_intent", context)
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=f"prompt render error: {exc}")

        try:
            system = self._pm.load_system()
            response_text, provider_name = self._llm.complete(
                prompt, system=system,
                capability=self.capability,
                provider_name=self._provider_name,
                output_schema=_OUTPUT_SCHEMA,
            )
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=str(exc))

        try:
            parsed = safe_parse_json(response_text, required_fields={"intent": str})
        except LLMParseError as exc:
            return ToolResult(ok=False, data={}, error=f"JSON parse error: {exc}")

        intent = parsed.get("intent") or "unknown"
        if intent not in _VALID_INTENTS:
            intent = "unknown"

        confidence = parsed.get("confidence") or "low"
        needs_reply = bool(parsed.get("needs_reply", False))

        return ToolResult(
            ok=True,
            data={
                "intent": intent,
                "provider_used": provider_name,
                # Extra fields consumed by AnalyzeStep (also written to the file trace
                # by registry.call, since they are not in _LARGE_FIELDS). The reply
                # draft is produced separately by GenerateReply (think=True).
                "confidence": confidence,
                "needs_reply": needs_reply,
            },
        )
