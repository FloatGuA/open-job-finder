import time
from dataclasses import dataclass

from pipeline.base import StepOutput, StepStatus


@dataclass
class W2NavigateStepOutput(StepOutput):
    boss_conv_id_confirmed: str = ""


class W2NavigateStep:
    def __init__(self, registry):
        self._reg = registry

    def run(self, conv) -> W2NavigateStepOutput:
        start_ts = time.time()
        scope = {"conv_id": conv.conv_id, "company": conv.company}
        self._reg.set_context("navigate", scope)

        res = self._reg.call(
            "navigate_to_conversation",
            conv_id=conv.conv_id,
            company=conv.company,
            hr_name=conv.hr_name,
            boss_conv_id=conv.boss_conv_id,
            job_id=conv.job_id or "",
        )
        duration_ms = int((time.time() - start_ts) * 1000)

        if not res.ok:
            out = W2NavigateStepOutput(status=StepStatus.FAILED, error=res.error)
        else:
            out = W2NavigateStepOutput(
                status=StepStatus.SUCCESSFUL,
                boss_conv_id_confirmed=res.data.get("boss_conv_id_confirmed", ""),
            )

        logger = getattr(self._reg, "logger", None)
        if logger is not None:
            logger.log_step(
                step="navigate",
                scope=scope,
                status=out.status.value,
                duration_ms=duration_ms,
                data={"boss_conv_id_confirmed": out.boss_conv_id_confirmed},
                error=out.error,
            )
        return out
