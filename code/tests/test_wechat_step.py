"""Unit tests for WechatStep (W2 auto-agree to an exchange-WeChat card).

Pins the two behaviours that matter:
- No active card -> silent skip, and crucially NO re-scan/persist side effects.
- Agreed -> re-read the conversation and persist, so HR's just-sent WeChat message
  (which the pre-agree ReadStep could not have seen) lands this same run.
"""
import pytest

import pipeline.w2.steps.wechat as mod
from pipeline.base import StepStatus
from pipeline.w2.steps.wechat import WechatStep
from tools.base import ToolResult


class _FakeRegistry:
    def __init__(self, clicked, read_messages=None, inserted=0):
        self._clicked = clicked
        self._read_messages = read_messages or []
        self._inserted = inserted
        self.calls = []

    def set_context(self, *a, **k):
        pass

    def call(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if name == "accept_wechat_card":
            return ToolResult(ok=True, data={"card_found": self._clicked, "clicked": self._clicked})
        if name == "read_messages":
            return ToolResult(ok=True, data={"messages": self._read_messages})
        if name == "write_hr_messages":
            return ToolResult(ok=True, data={"inserted_count": self._inserted})
        raise AssertionError(f"unexpected tool call: {name}")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(mod.time, "sleep", lambda *a, **k: None)


def test_no_card_is_silent_skip_no_side_effects():
    reg = _FakeRegistry(clicked=False)
    out = WechatStep(reg).run(scope={"conv_id": "c1"})
    assert out.status == StepStatus.SKIPPED
    assert out.agreed is False
    # Must NOT re-scan or write when there was nothing to agree to.
    assert [c[0] for c in reg.calls] == ["accept_wechat_card"]


def test_agree_rescans_and_persists_new_message():
    hr_wx = [{"sender": "hr", "text": "wx: alice_hr_123"}]
    reg = _FakeRegistry(clicked=True, read_messages=hr_wx, inserted=1)
    out = WechatStep(reg).run(scope={"conv_id": "c1"})
    assert out.status == StepStatus.SUCCESSFUL
    assert out.agreed is True
    assert out.new_messages == 1
    called = [c[0] for c in reg.calls]
    assert "read_messages" in called and "write_hr_messages" in called
    # write must carry the conv_id so the new HR message is attributed correctly.
    write_call = next(c for c in reg.calls if c[0] == "write_hr_messages")
    assert write_call[1]["conv_id"] == "c1"


def test_agree_stops_retrying_once_a_new_message_lands():
    reg = _FakeRegistry(clicked=True, read_messages=[{"sender": "hr", "text": "x"}], inserted=1)
    WechatStep(reg).run(scope={"conv_id": "c1"})
    # One successful insert -> exactly one read/write pair (no wasted extra polls).
    assert [c[0] for c in reg.calls].count("read_messages") == 1
    assert [c[0] for c in reg.calls].count("write_hr_messages") == 1
