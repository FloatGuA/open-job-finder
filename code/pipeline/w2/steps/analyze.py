import time
from dataclasses import dataclass
from typing import Optional

from pipeline.base import StepOutput, StepStatus


@dataclass
class AnalyzeStepOutput(StepOutput):
    needs_resume: bool = False
    request_type: Optional[str] = None
    already_sent_resume: bool = False
    intent: str = "unknown"
    needs_reply: bool = False
    suggested_reply: Optional[str] = None
    provider_used: str = ""


class AnalyzeStep:
    def __init__(self, registry):
        self._reg = registry

    def run(self, conv, messages: list) -> AnalyzeStepOutput:
        start_ts = time.time()
        scope = {"conv_id": conv.conv_id, "company": conv.company}
        self._reg.set_context("analyze", scope)

        det = self._reg.call("detect_resume_request", messages=messages)
        needs_resume = det.data.get("needs_resume", False)
        request_type = det.data.get("request_type")
        already_sent = det.data.get("already_sent", False)

        # No HR message in the thread = there is nothing for HR-intent analysis to
        # judge and nothing to reply to (only our own outbound intro, possibly plus
        # a Boss platform nudge). Whether HR has spoken is a deterministic fact, so
        # code decides it: skip the LLM call entirely (saves tokens) and never
        # draft a reply. Otherwise the LLM, handed only our message or a platform
        # nudge, hallucinates an HR "acknowledgement" and drafts a bogus reply to
        # an HR who has not said a word. Resume detection above still runs -- it
        # keys on system bubbles, and a genuine HR resume request is an HR message
        # (so has_hr_message would be True and we would not be here).
        has_hr_message = any(m.get("sender") == "hr" for m in messages)
        if not has_hr_message:
            # Persist intent='unknown' even though there's nothing to reply to. This
            # is what we actually concluded (analysis ran, HR hasn't spoken), and it
            # gives the row a non-empty intent so filter_conversations' never_analyzed
            # recovery branch doesn't keep re-selecting it every round. If HR later
            # speaks, unread/newer_ts re-processes it ahead of that branch anyway.
            # reply_status stays None -> update_hr_analysis preserves any user action.
            self._reg.call(
                "update_hr_analysis",
                conv_id=conv.conv_id,
                intent="unknown",
                reply_text=None,
                reply_status=None,
                last_analyzed_ts=getattr(conv, "last_msg_ts", 0) or 0,
            )
            out = AnalyzeStepOutput(
                status=StepStatus.SUCCESSFUL,
                needs_resume=needs_resume,
                request_type=request_type,
                already_sent_resume=already_sent,
                intent="unknown",
                needs_reply=False,
                suggested_reply=None,
                provider_used="",
            )
            self._log_step(scope, out, start_ts, {
                "intent": "unknown",
                "needs_resume": needs_resume,
                "skipped_llm": "no_hr_message",
            })
            return out

        intent_res = self._reg.call(
            "analyze_hr_intent",
            conv_id=conv.conv_id,
            messages=messages,
            company=conv.company,
        )
        if not intent_res.ok:
            out = AnalyzeStepOutput(
                status=StepStatus.DEGRADED,
                error=intent_res.error,
                needs_resume=needs_resume,
                already_sent_resume=already_sent,
            )
            self._log_step(scope, out, start_ts, {})
            return out

        intent = intent_res.data.get("intent", "unknown")
        # needs_reply 是 intent 的确定性函数（analyze_hr_intent 已按 default_needs_reply 查表）。
        needs_reply = intent_res.data.get("needs_reply", False)
        provider_used = intent_res.data.get("provider_used", "")

        # resume_request 的 needs_reply 不看查表默认值，完全由运行时检测派生：一份简历 IS
        # 对「索要简历」的完整回应，所以只要本轮发得出/已发过简历（needs_resume or already_sent）
        # 就不额外起草文字回复（避免审批队列冗余噪声）；只有检测不到可发的简历（漏判）时才
        # 破例起草文字回复兜底，让 HR 不至于收到沉默。是不是漏判是确定性事实，code decides。
        resume_reply_fallback = False
        if intent == "resume_request":
            needs_reply = not (needs_resume or already_sent)
            resume_reply_fallback = needs_reply

        # Reply drafting is a separate step: intent classification ran think=False
        # (fast + direct); the reply is drafted think=True (deliberates over wording)
        # and only when a reply is actually needed. If drafting fails, keep the intent
        # result and surface needs_reply with no draft (reviewer can write one) rather
        # than dropping the whole analysis.
        suggested_reply = None
        if needs_reply:
            reply_res = self._reg.call(
                "generate_reply",
                conv_id=conv.conv_id,
                messages=messages,
                company=conv.company,
                intent=intent,
            )
            if reply_res.ok:
                suggested_reply = reply_res.data.get("suggested_reply")

        self._reg.call(
            "update_hr_analysis",
            conv_id=conv.conv_id,
            intent=intent,
            reply_text=suggested_reply,
            reply_status="pending" if needs_reply else None,
            last_analyzed_ts=getattr(conv, "last_msg_ts", 0) or 0,
        )

        out = AnalyzeStepOutput(
            status=StepStatus.SUCCESSFUL,
            needs_resume=needs_resume,
            request_type=request_type,
            already_sent_resume=already_sent,
            intent=intent,
            needs_reply=needs_reply,
            suggested_reply=suggested_reply,
            provider_used=provider_used,
        )
        self._log_step(scope, out, start_ts, {
            "intent": intent,
            "needs_resume": needs_resume,
            "provider_used": provider_used,
            "resume_reply_fallback": resume_reply_fallback,
        })
        return out

    def _log_step(self, scope, out, start_ts, data):
        logger = getattr(self._reg, "logger", None)
        if logger is None:
            return
        duration_ms = int((time.time() - start_ts) * 1000)
        logger.log_step(
            step="analyze",
            scope=scope,
            status=out.status.value,
            duration_ms=duration_ms,
            data=data,
            error=out.error,
        )
