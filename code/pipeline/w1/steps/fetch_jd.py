import time
from dataclasses import dataclass

from pipeline.base import StepOutput, StepStatus


@dataclass
class FetchJDStepOutput(StepOutput):
    jd_text: str = ""
    salary_decoded: str = ""
    hr_name: str = ""


class FetchJDStep:
    def __init__(self, registry):
        self._reg = registry

    def run(self, card_dom_index: int, job_id: str) -> FetchJDStepOutput:
        start_ts = time.time()
        scope = {"job_id": job_id}
        self._reg.set_context("fetch_jd", scope)

        click = self._reg.call("click_card_open_panel", card_dom_index=card_dom_index, job_id=job_id)
        if not click.ok:
            out = FetchJDStepOutput(status=StepStatus.SKIPPED, error="card_not_found")
            self._log_step(scope, out, start_ts, {"failure_reason": "card_not_found"})
            return out
        if not click.data.get("panel_loaded"):
            out = FetchJDStepOutput(status=StepStatus.DEGRADED, error="panel_load_failed")
            self._log_step(scope, out, start_ts, {"failure_reason": "panel_load_failed"})
            return out
        matched_selector = click.data.get("matched_selector")
        jd = self._reg.call("read_panel_jd", matched_selector=matched_selector)
        if not jd.ok:
            # jd.error is "jd_empty" or a read exception string
            out = FetchJDStepOutput(status=StepStatus.DEGRADED, error=jd.error)
            self._log_step(scope, out, start_ts, {
                "failure_reason": jd.error,
                "matched_selector": matched_selector,
            })
            return out

        salary_raw = jd.data.get("salary_raw", "")
        dec = self._reg.call("decode_job_salary", raw_salary=salary_raw)
        salary_decoded = dec.data.get("decoded_salary", "") if dec.ok else ""

        out = FetchJDStepOutput(
            status=StepStatus.SUCCESSFUL,
            jd_text=jd.data.get("jd_text", ""),
            salary_decoded=salary_decoded,
            hr_name=jd.data.get("hr_name", ""),
        )
        self._log_step(scope, out, start_ts, {
            "salary_decoded": salary_decoded,
            "hr_name": jd.data.get("hr_name", ""),
            "matched_selector": matched_selector,
        })
        return out

    def _log_step(self, scope, out, start_ts, data):
        logger = getattr(self._reg, "logger", None)
        if logger is None:
            return
        duration_ms = int((time.time() - start_ts) * 1000)
        logger.log_step(
            step="fetch_jd",
            scope=scope,
            status=out.status.value,
            duration_ms=duration_ms,
            data=data,
            error=out.error,
        )
