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

    def run(self, request_type: Optional[str], scope: dict = None,
            adapted_resume: str = "") -> ResumeStepOutput:
        start_ts = time.time()
        step_scope = scope or {}
        self._reg.set_context("resume", step_scope)

        # 开关开启且这个岗位匹配到了简历：先试发它的**已导出 PDF**附件。
        # 用已导出存档而不是让后端再渲染一份，是为了避免 A4 排版出现第二套实现
        # （唯一实现在前端 src/lib/resumeHtml.ts）——代价是用户得先导出过该简历。
        # 任何一步不成（没导出过 / 找不到上传控件 / 没出现送达气泡）都**继续往下走**
        # 原有策略，绝不因为"想发适配版"而漏发简历。
        if adapted_resume:
            path = self._adapted_pdf_path(adapted_resume)
            if path:
                up = self._reg.call("upload_resume_file", resume_path=path)
                if up.ok and up.data.get("sent"):
                    return self._done(step_scope, start_ts, "adapted_pdf")
                self._log_fallback(step_scope, adapted_resume,
                                   up.error or "upload not confirmed")
            else:
                self._log_fallback(step_scope, adapted_resume,
                                   "no exported PDF for this resume")

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

    def _adapted_pdf_path(self, name: str) -> str:
        """按简历名从**简历库**回查 PDF；查不到返回 ""（调用方回退站内简历）。

        库＝`data/resumes/library/`，装所有能往外发的 PDF（系统导出的 + 你自己
        放进去的）。`path_for_name` 在没勾「允许发送」或**重名**时返回空——
        重名不猜，猜错的后果是给这个 HR 发了另一份简历。
        """
        try:
            from services.resume_library import ResumeLibrary
            return ResumeLibrary().path_for_name(name)
        except Exception:
            return ""

    def _log_fallback(self, scope: dict, name: str, reason: str) -> None:
        """适配版没发成 → 明确记一笔再回退，别让"为什么发的是站内简历"变成哑谜。"""
        logger = getattr(self._reg, "logger", None)
        if logger is None:
            return
        logger.log(
            "adapted_resume_fallback",
            scope=scope,
            data={"resume": name, "reason": reason},
        )

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
