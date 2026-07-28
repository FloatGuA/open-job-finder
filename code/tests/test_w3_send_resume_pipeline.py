"""W3 SendResumePipeline tests (manually queued resume delivery).

Contract:
- locate fails          -> never send, never clear
- already delivered      -> clear queue, DO NOT re-send (idempotent)
- dry_run               -> located, never send/clear
- send succeeds         -> clear queue + advance stage=resume_sent
Unlike the reply pipeline there is NO freshness gate (a resume doesn't go stale).
"""
from tools.base import ToolResult
from pipeline.w3.pipeline import W3Config
from pipeline.w3.send_resume_pipeline import SendResumePipeline

# No ids -> search-box locate path (keeps the fake simple).
_RCONV = {"conv_id": "c1", "company": "X公司", "hr_name": "李女士",
          "job_id": "", "boss_conv_id": ""}


class FakeLogger:
    def __init__(self):
        self.events = []

    def log(self, name, **kw):
        self.events.append(name)

    def log_step(self, **kw):
        pass

    def should_stop(self):
        return False


class FakeReg:
    def __init__(self, responses):
        self._responses = responses
        self.calls = []
        self.logger = None

    def set_context(self, step, scope):
        pass

    def call(self, name, **kwargs):
        self.calls.append((name, kwargs))
        resp = self._responses.get(name)
        return resp if resp is not None else ToolResult(ok=True, data={})

    def names(self):
        return [c[0] for c in self.calls]


def _run(responses, dry_run=False):
    reg = FakeReg(responses)
    out = SendResumePipeline(reg, logger=FakeLogger(), config=W3Config(dry_run=dry_run)).run(_RCONV)
    return reg, out


def test_locate_failed_never_sends_or_clears():
    reg, out = _run({"search_locate_conversation": ToolResult(ok=True, data={"located": False})})
    assert out.located is False and out.failure_reason == "locate_failed"
    assert "click_toolbar_send_resume" not in reg.names()
    assert "accept_resume_card" not in reg.names()
    assert "clear_resume_queue" not in reg.names()


def test_already_sent_clears_queue_without_resending():
    reg, out = _run({
        "search_locate_conversation": ToolResult(ok=True, data={"located": True}),
        "read_messages": ToolResult(ok=True, data={"messages": [{"sender": "system", "text": "附件简历"}]}),
        "detect_resume_request": ToolResult(ok=True, data={"already_sent": True}),
    })
    assert out.skipped_already_sent is True and out.delivered is False
    # Idempotent: queue cleared, but the send tools never fired.
    assert "clear_resume_queue" in reg.names()
    assert "click_toolbar_send_resume" not in reg.names()
    assert "accept_resume_card" not in reg.names()
    assert "upsert_hr_conversation" not in reg.names()


def test_dry_run_locates_but_does_not_send():
    reg, out = _run({
        "search_locate_conversation": ToolResult(ok=True, data={"located": True}),
    }, dry_run=True)
    assert out.located is True and out.failure_reason == "dry_run"
    assert "read_messages" not in reg.names()
    assert "clear_resume_queue" not in reg.names()


def test_successful_send_clears_queue_and_advances_stage():
    reg, out = _run({
        "search_locate_conversation": ToolResult(ok=True, data={"located": True}),
        "read_messages": ToolResult(ok=True, data={"messages": [{"sender": "hr", "text": "发个简历"}]}),
        "detect_resume_request": ToolResult(ok=True, data={"already_sent": False}),
        # ResumeStep: accept_card first (no card), then toolbar delivers.
        "accept_resume_card": ToolResult(ok=True, data={"sent": False}),
        "click_toolbar_send_resume": ToolResult(ok=True, data={"sent": True}),
    })
    assert out.delivered is True and out.failure_reason is None
    assert "clear_resume_queue" in reg.names()
    # stage advanced via upsert with stage=resume_sent
    upserts = [kw for (n, kw) in reg.calls if n == "upsert_hr_conversation"]
    assert upserts and upserts[0]["stage"] == "resume_sent"


def test_send_failure_keeps_queue():
    reg, out = _run({
        "search_locate_conversation": ToolResult(ok=True, data={"located": True}),
        "read_messages": ToolResult(ok=True, data={"messages": [{"sender": "hr", "text": "发个简历"}]}),
        "detect_resume_request": ToolResult(ok=True, data={"already_sent": False}),
        "accept_resume_card": ToolResult(ok=True, data={"sent": False}),
        "click_toolbar_send_resume": ToolResult(ok=True, data={"sent": False}),
    })
    assert out.delivered is False and out.failure_reason == "send_failed"
    # Not delivered -> queue NOT cleared (retry next W3 run).
    assert "clear_resume_queue" not in reg.names()
    assert "upsert_hr_conversation" not in reg.names()
