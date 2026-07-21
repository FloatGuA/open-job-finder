"""W3 SendReplyPipeline completion-check tests.

The whole point of W3 is that a reply is only marked sent when delivery is
*verified*. Verification = re-scan the thread (read_messages), persist it
(write_hr_messages), and confirm OUR reply now exists as a 'me' bubble.
These tests pin that contract with a fake registry:
- locate fails        -> never send, never mark
- re-scan lacks reply -> never mark (reply stays approved, text intact)
- re-scan has reply   -> persisted + mark_reply_sent called
- dry_run             -> never send
"""
import pytest

from tools.base import ToolResult
from pipeline.w3.pipeline import W3Config
from pipeline.w3.send_pipeline import SendReplyPipeline

_REPLY = {"conv_id": "c1", "company": "X公司", "hr_name": "李女士", "reply_text": "你好，方便聊聊吗"}


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    # Verify retries with time.sleep between re-scans; skip the real waits.
    monkeypatch.setattr("pipeline.w3.send_pipeline.time.sleep", lambda *a, **k: None)


class FakeReg:
    def __init__(self, responses):
        self._responses = responses
        self.calls = []
        self.logger = None

    def set_context(self, step, scope):
        pass

    def call(self, name, **kwargs):
        self.calls.append((name, kwargs))
        return self._responses.get(name, ToolResult(ok=True, data={}))

    def names(self):
        return [c[0] for c in self.calls]


def _run(responses, dry_run=False):
    reg = FakeReg(responses)
    out = SendReplyPipeline(reg, logger=None, config=W3Config(dry_run=dry_run)).run(_REPLY)
    return reg, out


def test_locate_failed_never_sends_or_marks():
    reg, out = _run({"search_locate_conversation": ToolResult(ok=True, data={"located": False})})
    assert out.located is False and out.failure_reason == "locate_failed"
    assert "send_chat_message" not in reg.names()
    assert "mark_reply_sent" not in reg.names()


def test_unverified_delivery_does_not_mark_sent():
    # Re-scan returns only HR messages — our reply never landed.
    reg, out = _run({
        "search_locate_conversation": ToolResult(ok=True, data={"located": True}),
        "send_chat_message": ToolResult(ok=True, data={"input_cleared": True}),
        "read_messages": ToolResult(ok=True, data={"messages": [
            {"sender": "hr", "text": "在吗"},
        ]}),
    })
    assert out.submitted is True and out.delivered is False
    assert out.failure_reason == "deliver_unverified" and out.marked_sent is False
    assert "mark_reply_sent" not in reg.names()


def test_verified_delivery_persists_and_marks_sent():
    # Re-scan shows our reply as a 'me' bubble -> persist + mark sent.
    reg, out = _run({
        "search_locate_conversation": ToolResult(ok=True, data={"located": True}),
        "send_chat_message": ToolResult(ok=True, data={"input_cleared": True}),
        "read_messages": ToolResult(ok=True, data={"messages": [
            {"sender": "hr", "text": "在吗"},
            {"sender": "me", "text": "你好，方便聊聊吗"},
        ]}),
    })
    assert out.delivered is True and out.marked_sent is True and out.failure_reason is None
    # The fresh scan is persisted to hr_messages...
    assert any(n == "write_hr_messages" for n in reg.names())
    # ...and only then is the reply marked sent.
    assert ("mark_reply_sent", {"conv_id": "c1"}) in reg.calls


def test_dry_run_locates_but_never_sends():
    reg, out = _run(
        {"search_locate_conversation": ToolResult(ok=True, data={"located": True})},
        dry_run=True,
    )
    assert out.located is True and out.failure_reason == "dry_run"
    assert "send_chat_message" not in reg.names()
