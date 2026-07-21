"""ApplyStep must thread Boss quota signals out of click_apply_button:
- a near-cap "还剩N次" notice on an applied card -> quota_notice (drives w1_quota_warning)
- the hard cap -> should_stop + message (drives w1_rate_limited + scheduler pause)
"""
from pipeline.base import StepStatus
from pipeline.w1.steps.apply import ApplyStep
from tools.base import ToolResult


class _Reg:
    def __init__(self, apply_data):
        self._apply_data = apply_data
        self.logger = None  # _log_step no-ops when logger is None

    def set_context(self, *a, **k):
        pass

    def call(self, name, **kwargs):
        if name == "click_apply_button":
            return ToolResult(ok=True, data=self._apply_data)
        if name == "handle_apply_dialog":
            return ToolResult(ok=True, data={})
        raise AssertionError(f"unexpected tool call: {name}")


def test_apply_threads_quota_notice_on_applied():
    out = ApplyStep(_Reg({"result": "applied", "quota_notice": "还剩30次沟通机会"})).run(dry_run=False)
    assert out.status == StepStatus.SUCCESSFUL
    assert out.result == "applied"
    assert out.quota_notice == "还剩30次沟通机会"


def test_apply_no_quota_notice_is_empty():
    out = ApplyStep(_Reg({"result": "applied"})).run(dry_run=False)
    assert out.result == "applied"
    assert out.quota_notice == ""


def test_apply_rate_limited_stops_with_message():
    out = ApplyStep(_Reg({"result": "rate_limited", "message": "达到上限"})).run(dry_run=False)
    assert out.status == StepStatus.DEGRADED
    assert out.should_stop is True
    assert out.message == "达到上限"
