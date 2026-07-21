import time
from dataclasses import dataclass
from typing import Optional

from pipeline.base import StepOutput, StepStatus


@dataclass
class ResumeStepOutput(StepOutput):
    sent: bool = False
    strategy_used: str = ""


class ResumeStep:
    def __init__(self, registry):
        self._reg = registry

    def run(self, request_type: Optional[str], scope: dict = None) -> ResumeStepOutput:
        start_ts = time.time()
        step_scope = scope or {}
        self._reg.set_context("resume", step_scope)

        # Two strategies tried in order; first success wins.
        #   1. accept_card -- click "agree" on an HR resume-exchange card
        #   2. toolbar     -- click the "send resume" toolbar button (both sides
        #                     must have replied, else it stays disabled)
        # Card requests start at strategy 1; hr_text requests go straight to the
        # toolbar -- the gap that previously left text-based requests unanswered.
        #
        # The toolbar button selector [d-c="62009"] is CONFIRMED correct (verified
        # 2026-06-04 on the live page: the send-resume button is a
        # <div class="toolbar-btn tooltip tooltip-top" d-c="62009">). d-c is a stable
        # Boss widget-type id (e.g. 62001=conversation card, 62009=send-resume button),
        # which is why it is constant across conversations rather than per-conversation.
        # STILL UNVERIFIED: the disabled-state class (only ever observed enabled, so the
        # `unable` check in the tool is a guess).
        # VERIFIED 2026-06-11: a toolbar click on a CROSS-BORDER HR (account used outside
        # mainland China) opens a second-step confirm popover (.panel-resume.sentence-
        # popover) that must be accepted (确定) before anything is delivered; mainland HRs
        # send directly with no popover. The tool now handles the popover and only reports
        # sent=True once delivery is real -- see click_toolbar_send_resume.

        if request_type in ("system_notification", "hr_card"):
            res = self._reg.call("accept_resume_card")
            # `sent` (a new delivered-resume system bubble appeared) is the authoritative
            # signal for BOTH paths now -- not card_found (which only means the agree
            # button was clicked, not that the resume was delivered).
            if res.ok and res.data.get("sent"):
                return self._done(step_scope, start_ts, "accept_card")

        toolbar = self._reg.call("click_toolbar_send_resume")
        # `sent` is the authoritative signal: the tool sets it True only after the
        # send actually went through (mainland: direct; cross-border: 确定 clicked and
        # the confirm popover dismissed). "button found + enabled" is NOT enough -- a
        # cross-border send stuck on the unconfirmed popover has both True yet delivers
        # nothing, which previously caused false resume_sent records.
        if toolbar.ok and toolbar.data.get("sent"):
            return self._done(step_scope, start_ts, "toolbar")

        out = ResumeStepOutput(status=StepStatus.DEGRADED, sent=False, strategy_used="")
        self._log_step(step_scope, out, start_ts, {"strategy_used": ""})
        return out

    def _done(self, scope, start_ts, strategy: str) -> ResumeStepOutput:
        out = ResumeStepOutput(status=StepStatus.SUCCESSFUL, sent=True, strategy_used=strategy)
        self._log_step(scope, out, start_ts, {"strategy_used": strategy})
        return out

    def _log_step(self, scope, out, start_ts, data):
        logger = getattr(self._reg, "logger", None)
        if logger is None:
            return
        duration_ms = int((time.time() - start_ts) * 1000)
        # Surface WHICH send method was used on the SSE stream as a normal (non-debug)
        # signal: the frontend LiveLog renders the step message (not detail), so encode
        # the strategy into the message rather than leaving it only in data.strategy_used.
        if out.sent:
            message = f"resume sent via {out.strategy_used}"
        else:
            message = "resume not sent (no available method)"
        logger.log_step(
            step="resume",
            scope=scope,
            status=out.status.value,
            duration_ms=duration_ms,
            data=data,
            message=message,
            error=out.error,
        )
