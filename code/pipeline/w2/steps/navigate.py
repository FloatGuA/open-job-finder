import time
from dataclasses import dataclass

from pipeline.base import StepOutput, StepStatus


@dataclass
class W2NavigateStepOutput(StepOutput):
    boss_conv_id_confirmed: str = ""
    method: str = ""


class W2NavigateStep:
    def __init__(self, registry):
        self._reg = registry

    def run(self, conv) -> W2NavigateStepOutput:
        start_ts = time.time()
        # job_id on the scope lets the monitor link this conversation to its Boss job
        # posting (open-job button); it never changes instance grouping (conv_id stays
        # the key). Empty for sha256 soft-key conversations with no job_id.
        scope = {"conv_id": conv.conv_id, "company": conv.company, "job_id": conv.job_id or ""}
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

        # `method` records HOW we located: direct_url (Treatment D O(1) open) vs
        # js_click (the slow DOM scroll-search fallback). A run full of js_click means
        # the getGeekFriendList ids were missing (scan fell back to DOM, or the conv
        # lacked encryptJobId/encryptBossId) and direct-open never fired — the single
        # most useful signal when diagnosing "why is W2 locating so slowly / failing".
        if not res.ok:
            out = W2NavigateStepOutput(
                status=StepStatus.FAILED,
                error=res.error,
                method=(res.data or {}).get("method", ""),
            )
        else:
            out = W2NavigateStepOutput(
                status=StepStatus.SUCCESSFUL,
                boss_conv_id_confirmed=res.data.get("boss_conv_id_confirmed", ""),
                method=res.data.get("method", ""),
            )

        logger = getattr(self._reg, "logger", None)
        if logger is not None:
            logger.log_step(
                step="navigate",
                scope=scope,
                status=out.status.value,
                duration_ms=duration_ms,
                data={"boss_conv_id_confirmed": out.boss_conv_id_confirmed, "method": out.method},
                error=out.error,
            )
        return out
