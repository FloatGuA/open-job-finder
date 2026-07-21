"""W1 card pipeline: a dry-run must not look like an apply failure.

ApplyStep already logs the apply step as SUCCESSFUL for result='dry_run'. The
card pipeline then re-dispatched on the result string, and because dry_run had no
branch it fell through to the technical-failure tail: a second, contradictory
'apply failed' step for the same card, a job_apply_failed event (rendered as a red
投递失败 in the monitor) and a wasted failure screenshot -- on every dry run.
Caught by run-log diagnostics: the smoke reported PASS while its own log said
"投递失败 × 1".
"""
from pipeline.base import StepStatus
from pipeline.w1.card_pipeline import CardInput, CardPipeline


class _Res:
    def __init__(self, ok=True, data=None, error=None):
        self.ok = ok
        self.data = data or {}
        self.error = error


class _Reg:
    """Registry stub driving the card down the happy path to apply."""

    def __init__(self, apply_result="dry_run"):
        self._apply_result = apply_result
        self.calls = []

    def set_context(self, *a, **kw):
        pass

    def call(self, tool, **kw):
        self.calls.append(tool)
        if tool == "classify_job_for_w1":
            return _Res(data={"action": "process"})
        if tool == "check_content_duplicate":
            return _Res(data={"duplicate": False})
        if tool == "score_job":
            return _Res(data={"score": 90, "reason": "fit", "dimensions": {}})
        if tool == "click_card_open_panel":
            return _Res(data={"panel_loaded": True, "matched_selector": ".job-detail"})
        if tool == "read_panel_jd":
            return _Res(data={"jd_text": "job description", "hr_name": "HR",
                              "salary_raw": "20-30K"})
        if tool == "decode_job_salary":
            return _Res(data={"decoded_salary": "20-30K"})
        if tool == "click_apply_button":
            return _Res(data={"result": self._apply_result})
        if tool == "handle_apply_dialog":
            return _Res(data={})
        if tool == "capture_screenshot":
            return _Res(data={"screenshot": "shot.png"})
        if tool in ("upsert_application", "upsert_hr_conversation"):
            return _Res(data={})
        return _Res(data={})


class _Logger:
    def __init__(self):
        self.steps = []   # (step, status)
        self.events = []  # event names

    def log_step(self, step, scope=None, status=None, duration_ms=0, data=None,
                 error=None, message=None):
        self.steps.append((step, status))

    def log(self, event, scope=None, data=None, visible=True):
        self.events.append(event)

    def emit_step_running(self, *a, **kw):
        pass


class _Config:
    def __init__(self, dry_run=True):
        self.dry_run = dry_run
        self.score_threshold = 60
        self.url = ""
        self.max_cards = None


def _card():
    return CardInput(job_id="j1", title="Engineer", company="Co", salary_raw="20-30K",
                     city="Shenzhen", hr_name="", card_dom_index=0)


def _run(apply_result, dry_run):
    reg, log = _Reg(apply_result), _Logger()
    out, stop, scored = CardPipeline(reg, {}, log, _Config(dry_run=dry_run)).run(_card())
    return out, reg, log


def test_dry_run_is_not_reported_as_apply_failure():
    out, reg, log = _run("dry_run", dry_run=True)

    assert "job_apply_failed" not in log.events, "dry-run must not emit an apply-failure event"
    assert "capture_screenshot" not in reg.calls, "dry-run must not burn a failure screenshot"
    # No contradictory second apply step claiming failure.
    assert ("apply", "failed") not in log.steps
    assert out.status != StepStatus.FAILED


def test_real_apply_failure_still_reports_and_screenshots():
    """The guard above must not mute genuine failures."""
    out, reg, log = _run("button_not_found", dry_run=False)

    assert "job_apply_failed" in log.events
    assert "capture_screenshot" in reg.calls
    assert ("apply", "failed") in log.steps
    assert out.status == StepStatus.FAILED
