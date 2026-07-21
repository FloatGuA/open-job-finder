"""Regression test for the W2 increment-detection source fix.

filter_conversations decides whether a conversation changed by comparing the
chat-list preview (from extract_conversation_list) against the value stored in
the DB. For that comparison to be meaningful, BOTH sides must come from the
SAME source -- the chat-list row preview. ConversationPipeline must therefore
persist ``conv.last_msg_preview`` (the scan-time list preview), NOT
``messages[-1]["text"]``, which is a different DOM source (the in-conversation
last message) captured before reply/resume. If the two sources diverge the
comparison never matches and every non-terminal conversation is reprocessed
each run. This test pins the upsert call to the list-preview source.
"""
from pipeline.base import StepStatus
import pipeline.w2.conversation_pipeline as mod
from pipeline.w2.conversation_pipeline import ConvBasic, ConversationPipeline
from tools.base import ToolResult

# Deliberately distinct strings: the chat-list preview vs the in-conversation
# last message. The fix must store the former.
_LIST_PREVIEW = "[img] short list-row snippet"
_INNER_LAST_MSG = "full inner last message body, longer and from a different DOM node"


class _Out:
    """Minimal attribute bag standing in for a StepOutput."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FakeNavigate:
    def __init__(self, reg):
        pass

    def run(self, conv):
        return _Out(status=StepStatus.SUCCESSFUL, boss_conv_id_confirmed="boss_xyz")


class _FakeRead:
    def __init__(self, reg):
        pass

    def run(self, conv_id):
        return _Out(
            status=StepStatus.SUCCESSFUL,
            messages=[{"sender": "hr", "text": _INNER_LAST_MSG}],
        )


class _FakeAnalyze:
    def __init__(self, reg):
        pass

    def run(self, conv, messages):
        # intent 'unknown' keeps it off the resume/reply branches; needs_resume
        # False + approved_reply None means ResumeStep/ReplyStep are never built.
        return _Out(
            status=StepStatus.SUCCESSFUL,
            intent="unknown",
            request_type=None,
            provider_used="test",
            needs_resume=False,
            already_sent_resume=False,
        )


class _FakeWechat:
    """No-op WeChat auto-agree step (orthogonal to this test's upsert assertion)."""

    def __init__(self, reg):
        pass

    def run(self, scope=None):
        return _Out(status=StepStatus.SKIPPED, agreed=False)


class _FakeRegistry:
    """Captures the single upsert_hr_conversation call the pipeline makes."""

    def __init__(self):
        self.upsert_kwargs = None

    def call(self, name, **kwargs):
        assert name == "upsert_hr_conversation", f"unexpected tool call: {name}"
        self.upsert_kwargs = kwargs
        return ToolResult(
            ok=True,
            data={"stage_changed": False, "prev_stage": "new", "stage": "active"},
        )


class _FakeLogger:
    def log(self, *a, **k):
        pass

    def log_step(self, *a, **k):
        pass


def test_pipeline_stores_list_preview_not_inner_message(monkeypatch):
    monkeypatch.setattr(mod, "W2NavigateStep", _FakeNavigate)
    monkeypatch.setattr(mod, "ReadStep", _FakeRead)
    monkeypatch.setattr(mod, "AnalyzeStep", _FakeAnalyze)
    monkeypatch.setattr(mod, "WechatStep", _FakeWechat)

    reg = _FakeRegistry()
    pipeline = ConversationPipeline(
        reg, profile=None, logger=_FakeLogger(), config=_Out(dry_run=False)
    )
    conv = ConvBasic(
        conv_id="c1",
        hr_name="Alice",
        company="Acme",
        boss_conv_id="b1",
        hr_title="HR",
        last_msg_preview=_LIST_PREVIEW,
    )

    pipeline.run(conv, approved_reply=None)

    assert reg.upsert_kwargs is not None, "pipeline never called upsert_hr_conversation"
    # The stored preview must be the scan-time list preview...
    assert reg.upsert_kwargs["last_msg_preview"] == _LIST_PREVIEW
    # ...and explicitly NOT the in-conversation last message (the old, buggy source).
    assert reg.upsert_kwargs["last_msg_preview"] != _INNER_LAST_MSG
