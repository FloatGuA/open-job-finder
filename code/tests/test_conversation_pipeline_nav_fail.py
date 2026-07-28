"""W2 locate-failure diagnostics: when W2NavigateStep fails to open the
conversation, ConversationPipeline must capture a screenshot and emit a visible
``conv_navigate_failed`` event (mirroring W1's apply-failure screenshot), then
abort the conversation — it must NOT go on to read/analyze a page it never
opened. The screenshot filename is what the monitor links to via
/api/apply-failure/{name}.
"""
from pipeline.base import StepStatus
import pipeline.w2.conversation_pipeline as mod
from pipeline.w2.conversation_pipeline import ConvBasic, ConversationPipeline
from tools.base import ToolResult


class _Out:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FailNavigate:
    """Navigate that fails to locate the conversation (scroll-search miss)."""

    def __init__(self, reg):
        pass

    def run(self, conv):
        return _Out(
            status=StepStatus.FAILED,
            error="conversation not found for company='Acme'",
            method="js_click",
            boss_conv_id_confirmed="",
        )


class _ExplodingRead:
    """Downstream steps must never run after a failed navigate."""

    def __init__(self, reg):
        pass

    def run(self, conv_id):
        raise AssertionError("ReadStep ran despite navigate failure")


class _FakeRegistry:
    def __init__(self):
        self.calls = []

    def set_context(self, *a, **k):
        pass

    def call(self, name, **kwargs):
        self.calls.append((name, kwargs))
        if name == "capture_screenshot":
            return ToolResult(ok=True, data={"screenshot": "run1_c1_20260728.png"})
        raise AssertionError(f"unexpected tool call after nav failure: {name}")


class _FakeLogger:
    run_id = "run1"

    def __init__(self):
        self.events = []

    def log(self, event, scope=None, data=None, visible=False):
        self.events.append({"event": event, "scope": scope or {}, "data": data or {}, "visible": visible})

    def log_step(self, *a, **k):
        pass


def test_navigate_failure_captures_screenshot_and_aborts(monkeypatch):
    monkeypatch.setattr(mod, "W2NavigateStep", _FailNavigate)
    monkeypatch.setattr(mod, "ReadStep", _ExplodingRead)

    reg = _FakeRegistry()
    logger = _FakeLogger()
    pipeline = ConversationPipeline(reg, profile=None, logger=logger, config=_Out(dry_run=False))
    conv = ConvBasic(conv_id="c1", hr_name="Alice", company="Acme", boss_conv_id="b1", job_id="c1")

    out = pipeline.run(conv, approved_reply=None)

    # Aborted with the navigate_failed marker (no read/analyze/upsert ran).
    assert out.error == "navigate_failed"
    # A screenshot was captured, labelled {run_id}_{conv_id}.
    shot_calls = [kw for name, kw in reg.calls if name == "capture_screenshot"]
    assert len(shot_calls) == 1
    assert shot_calls[0]["label"] == "run1_c1"
    # A visible conv_navigate_failed event carries the screenshot + method + job_id.
    fail = [e for e in logger.events if e["event"] == "conv_navigate_failed"]
    assert len(fail) == 1
    assert fail[0]["visible"] is True
    assert fail[0]["data"]["screenshot"] == "run1_c1_20260728.png"
    assert fail[0]["data"]["method"] == "js_click"
    assert fail[0]["scope"]["job_id"] == "c1"
