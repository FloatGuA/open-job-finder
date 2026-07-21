"""Guard test: AnalyzeStep must NOT draft a reply when the thread has zero HR
messages.

A conversation that contains only our own outbound intro (optionally plus a Boss
platform nudge reclassified to 'system') gives the HR-intent LLM nothing to judge.
Handed only those, the LLM hallucinates an HR "acknowledgement" and drafts a bogus
reply to an HR who never spoke. Whether HR has spoken is deterministic, so
AnalyzeStep short-circuits: it skips the analyze_hr_intent LLM call entirely and
returns needs_reply=False with no suggested_reply.
"""
from pipeline.base import StepStatus
from pipeline.w2.steps.analyze import AnalyzeStep
from tools.base import ToolResult


class _Conv:
    conv_id = "c1"
    company = "Acme"


class _Logger:
    def log_step(self, *a, **k):
        pass


class _Registry:
    """Records tool calls; returns canned data for detect_resume_request."""

    def __init__(self):
        self.calls = []
        self.logger = _Logger()

    def set_context(self, *a, **k):
        pass

    def call(self, name, **kwargs):
        self.calls.append(name)
        self.call_kwargs = getattr(self, "call_kwargs", {})
        self.call_kwargs[name] = kwargs
        if name == "detect_resume_request":
            return ToolResult(
                ok=True,
                data={"needs_resume": False, "request_type": None, "already_sent": False},
            )
        if name == "update_hr_analysis":
            # The no-HR path persists intent='unknown' (see below); allow it.
            return ToolResult(ok=True, data={})
        # The LLM intent call must NOT be hit in the no-HR path -- fail loudly.
        raise AssertionError(f"unexpected tool call in no-HR path: {name}")


def test_no_hr_message_skips_llm_and_drafts_nothing():
    reg = _Registry()
    messages = [
        {"sender": "me", "text": "hi I'm a candidate"},
        {"sender": "system", "text": "platform nudge"},
    ]
    out = AnalyzeStep(reg).run(conv=_Conv(), messages=messages)

    assert out.status == StepStatus.SUCCESSFUL
    assert out.needs_reply is False
    assert out.suggested_reply is None
    assert out.intent == "unknown"
    # LLM intent must be skipped (HR hasn't spoken); resume detection still runs.
    assert "analyze_hr_intent" not in reg.calls
    assert "generate_reply" not in reg.calls
    # But intent='unknown' IS persisted so the row stops matching filter's
    # never_analyzed recovery branch every round (self-limiting).
    assert reg.calls == ["detect_resume_request", "update_hr_analysis"]
    assert reg.call_kwargs["update_hr_analysis"]["intent"] == "unknown"
    assert reg.call_kwargs["update_hr_analysis"]["reply_status"] is None


def test_hr_message_present_runs_llm():
    """Sanity counterpart: with a real HR message, the LLM path is taken."""
    reg = _Registry()

    # Re-point the registry to allow the LLM + write calls for this case.
    def call(name, **kwargs):
        reg.calls.append(name)
        if name == "detect_resume_request":
            return ToolResult(ok=True, data={"needs_resume": False, "request_type": None, "already_sent": False})
        if name == "analyze_hr_intent":
            # Intent classification (think=False) — no suggested_reply here anymore.
            return ToolResult(ok=True, data={
                "intent": "general", "needs_reply": True, "provider_used": "test",
            })
        if name == "generate_reply":
            # Reply drafting (think=True) — the separate step that produces the draft.
            return ToolResult(ok=True, data={
                "suggested_reply": "thanks!", "provider_used": "test",
            })
        if name == "update_hr_analysis":
            return ToolResult(ok=True, data={})
        raise AssertionError(f"unexpected: {name}")

    reg.call = call
    messages = [{"sender": "hr", "text": "are you available?"}]
    out = AnalyzeStep(reg).run(conv=_Conv(), messages=messages)

    assert out.status == StepStatus.SUCCESSFUL
    assert out.needs_reply is True
    assert out.suggested_reply == "thanks!"
    assert "analyze_hr_intent" in reg.calls
    assert "generate_reply" in reg.calls
    assert "update_hr_analysis" in reg.calls
