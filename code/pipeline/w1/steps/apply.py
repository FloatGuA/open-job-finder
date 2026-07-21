import time
from dataclasses import dataclass

from pipeline.base import StepOutput, StepStatus


@dataclass
class ApplyStepOutput(StepOutput):
    result: str = ""
    should_stop: bool = False
    message: str = ""
    quota_notice: str = ""  # Boss "还剩N次" reminder text on an applied card (near cap)


class ApplyStep:
    def __init__(self, registry):
        self._reg = registry

    def run(self, dry_run: bool, scope: dict = None) -> ApplyStepOutput:
        start_ts = time.time()
        step_scope = scope or {}
        self._reg.set_context("apply", step_scope)

        apply = self._reg.call("click_apply_button", dry_run=dry_run)
        if not apply.ok:
            out = ApplyStepOutput(status=StepStatus.DEGRADED, error=apply.error, result="error")
            self._log_step(step_scope, out, start_ts, {"result": "error"})
            return out

        result = apply.data.get("result", "")

        if result == "rate_limited":
            msg = apply.data.get("message", "")
            out = ApplyStepOutput(status=StepStatus.DEGRADED, result=result, should_stop=True, message=msg)
            self._log_step(step_scope, out, start_ts, {"result": result, "message": msg})
            return out

        # Always clear the success dialog after an apply attempt: on "applied" to
        # dismiss our own fresh dialog, on "dialog_blocked" to clear a stale/leftover
        # one so it cannot block or false-positive the next card. Without this, a
        # single un-dismissed dialog cascades into phantom "applied" results.
        if result in ("applied", "dialog_blocked"):
            self._reg.call("handle_apply_dialog", action="close_and_wait")

        out = ApplyStepOutput(
            status=StepStatus.SUCCESSFUL,
            result=result,
            should_stop=False,
            quota_notice=apply.data.get("quota_notice", ""),
        )
        self._log_step(step_scope, out, start_ts, {"result": result})
        return out

    def _log_step(self, scope, out, start_ts, data):
        logger = getattr(self._reg, "logger", None)
        if logger is None:
            return
        duration_ms = int((time.time() - start_ts) * 1000)
        logger.log_step(
            step="apply",
            scope=scope,
            status=out.status.value,
            duration_ms=duration_ms,
            data=data,
            error=out.error,
        )
