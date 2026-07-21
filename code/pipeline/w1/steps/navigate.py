import time
from dataclasses import dataclass

from pipeline.base import StepOutput, StepStatus


@dataclass
class NavigateStepOutput(StepOutput):
    loaded_url: str = ""


class NavigateStep:
    def __init__(self, registry):
        self._reg = registry

    def run(self, url: str) -> NavigateStepOutput:
        start_ts = time.time()
        scope = {"url": url}
        self._reg.set_context("navigate", scope)
        result = self._reg.call("navigate_search_url", url=url)
        duration_ms = int((time.time() - start_ts) * 1000)

        if not result.ok:
            out = NavigateStepOutput(status=StepStatus.FAILED, error=result.error)
        else:
            out = NavigateStepOutput(
                status=StepStatus.SUCCESSFUL,
                loaded_url=result.data.get("loaded_url", url),
            )

        logger = getattr(self._reg, "logger", None)
        if logger is not None:
            logger.log_step(
                step="navigate",
                scope=scope,
                status=out.status.value,
                duration_ms=duration_ms,
                data={"loaded_url": out.loaded_url},
                error=out.error,
            )
        return out
