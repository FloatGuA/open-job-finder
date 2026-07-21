"""W1 HR-name capture fix (2026-07-05).

The detail panel's boss card (div.job-boss-info h2.name) carries the HR name, but it
renders async — a timeout=0 read caught an empty node, so applications.hr_name stayed
blank and sync_application_status could never JOIN to hr_conversations.hr_name.

Covers: read_panel_jd waits for the boss card then extracts the name via JS; fetch_jd
threads that hr_name into FetchJDStepOutput (previously it went only to the log trace).
"""
import pytest

from pipeline.base import StepStatus
from pipeline.w1.steps.fetch_jd import FetchJDStep
from tools.base import ToolResult
import tools.browser.w1.read_panel_jd as rpj_mod
from tools.browser.w1.read_panel_jd import ReadPanelJD


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(rpj_mod.time, "sleep", lambda *a, **k: None)


# --- read_panel_jd -----------------------------------------------------------

class _Ele:
    def __init__(self, text=""):
        self.text = text


class _Page:
    """Minimal DrissionPage stand-in. Routes ele() by selector family and run_js()
    by whether the HR-name script (contains 'job-boss-info') is requested."""

    def __init__(self, jd="a valid job description text over twenty chars", hr_present=True, hr_js="王美雪"):
        self._jd = jd
        self._hr_present = hr_present
        self._hr_js = hr_js

    def ele(self, selector, timeout=0):
        s = selector
        if "boss-info" in s:            # HR wait selectors
            return _Ele() if self._hr_present else None
        if "salary" in s or s == ".red":
            return None                  # keep salary out of the way
        return _Ele(self._jd) if self._jd else None  # JD selectors

    def run_js(self, script):
        if "job-boss-info" in script:  # _HR_NAME_JS (querySelector returns "" if absent)
            return self._hr_js if self._hr_present else ""
        return {"found": None, "text": ""}  # JD fallback (unused here)


def test_read_panel_jd_extracts_hr_name_when_card_present():
    res = ReadPanelJD(browser=_Page(hr_present=True, hr_js="王美雪")).execute()
    assert res.ok
    assert res.data["hr_name"] == "王美雪"


def test_read_panel_jd_hr_name_blank_when_card_absent():
    res = ReadPanelJD(browser=_Page(hr_present=False)).execute()
    assert res.ok
    assert res.data["hr_name"] == ""


def test_read_panel_jd_strips_whitespace_from_hr_name():
    # The JS already strips the activity-suffix span; execute() must also .strip().
    res = ReadPanelJD(browser=_Page(hr_present=True, hr_js="  王美雪  ")).execute()
    assert res.data["hr_name"] == "王美雪"


# --- fetch_jd threads hr_name into the step output ---------------------------

class _Logger:
    def log_step(self, *a, **k):
        pass


class _Registry:
    def __init__(self, hr_name):
        self._hr = hr_name
        self.logger = _Logger()

    def set_context(self, *a, **k):
        pass

    def call(self, name, **kwargs):
        if name == "click_card_open_panel":
            return ToolResult(ok=True, data={"panel_loaded": True, "matched_selector": ".job-sec"})
        if name == "read_panel_jd":
            return ToolResult(ok=True, data={"jd_text": "jd", "hr_name": self._hr, "salary_raw": ""})
        if name == "decode_job_salary":
            return ToolResult(ok=True, data={"decoded_salary": ""})
        raise AssertionError(f"unexpected tool call: {name}")


def test_fetch_jd_threads_hr_name_into_output():
    out = FetchJDStep(_Registry(hr_name="王美雪")).run(card_dom_index=0, job_id="J1")
    assert out.status == StepStatus.SUCCESSFUL
    assert out.hr_name == "王美雪"


def test_fetch_jd_empty_hr_name_passes_through():
    out = FetchJDStep(_Registry(hr_name="")).run(card_dom_index=0, job_id="J1")
    assert out.status == StepStatus.SUCCESSFUL
    assert out.hr_name == ""
