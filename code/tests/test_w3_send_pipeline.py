"""W3 SendReplyPipeline completion-check tests.

The whole point of W3 is that a reply is only marked sent when delivery is
*verified*. Verification = re-scan the thread (read_messages), persist it
(write_hr_messages), and confirm OUR reply now exists as a 'me' bubble.
These tests pin that contract with a fake registry:
- locate fails             -> never send, never mark
- conversation moved on    -> void draft, skip send (pre-send freshness gate)
- freshness read fails      -> skip send, KEEP draft (no void)
- re-scan lacks reply      -> never mark (reply stays approved, text intact)
- re-scan has reply        -> persisted + mark_reply_sent called
- dry_run                  -> never send

read_messages is called twice per healthy send (pre-send freshness, then verify);
FakeReg supports a LIST of responses per tool to model the two distinct reads.
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
        resp = self._responses.get(name)
        if isinstance(resp, list):
            # Sequenced responses (read_messages: pre-send freshness read, then the
            # verify re-scans). The last entry repeats once the list is drained.
            if len(resp) > 1:
                return resp.pop(0)
            return resp[0] if resp else ToolResult(ok=True, data={})
        return resp if resp is not None else ToolResult(ok=True, data={})

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
    # Pre-send: HR is waiting (fresh). Post-send re-scan still shows only HR
    # messages — our reply never landed.
    reg, out = _run({
        "search_locate_conversation": ToolResult(ok=True, data={"located": True}),
        "send_chat_message": ToolResult(ok=True, data={"input_cleared": True}),
        "read_messages": [
            ToolResult(ok=True, data={"messages": [{"sender": "hr", "text": "在吗"}]}),
            ToolResult(ok=True, data={"messages": [{"sender": "hr", "text": "在吗"}]}),
        ],
    })
    assert out.submitted is True and out.delivered is False
    assert out.failure_reason == "deliver_unverified" and out.marked_sent is False
    assert "mark_reply_sent" not in reg.names()


def test_verified_delivery_persists_and_marks_sent():
    # Pre-send: HR is waiting (fresh) -> send. Post-send re-scan shows our reply as
    # a 'me' bubble -> persist + mark sent.
    reg, out = _run({
        "search_locate_conversation": ToolResult(ok=True, data={"located": True}),
        "send_chat_message": ToolResult(ok=True, data={"input_cleared": True}),
        "read_messages": [
            ToolResult(ok=True, data={"messages": [{"sender": "hr", "text": "在吗"}]}),
            ToolResult(ok=True, data={"messages": [
                {"sender": "hr", "text": "在吗"},
                {"sender": "me", "text": "你好，方便聊聊吗"},
            ]}),
        ],
    })
    assert out.delivered is True and out.marked_sent is True and out.failure_reason is None
    # The fresh scan is persisted to hr_messages...
    assert any(n == "write_hr_messages" for n in reg.names())
    # ...and only then is the reply marked sent.
    assert ("mark_reply_sent", {"conv_id": "c1"}) in reg.calls


def test_stale_conversation_voids_draft_and_skips_send():
    # Pre-send re-scan shows the LAST bubble is now ours -> someone (the user, a
    # resume card, a prior send) spoke after the HR message this draft answers.
    # Refuse to blind-send; void the draft so W2 re-decides intent next run.
    reg, out = _run({
        "search_locate_conversation": ToolResult(ok=True, data={"located": True}),
        "read_messages": ToolResult(ok=True, data={"messages": [
            {"sender": "hr", "text": "在吗"},
            {"sender": "me", "text": "用户手动回复的内容"},
        ]}),
    })
    assert out.failure_reason == "stale_superseded"
    assert out.submitted is False and out.marked_sent is False
    assert "send_chat_message" not in reg.names()
    assert ("invalidate_stale_reply", {"conv_id": "c1"}) in reg.calls


def test_not_delivered_when_only_an_identical_old_bubble_predates_send():
    # Edge B: an OLD 'me' bubble identical to our draft already exists, but HR spoke
    # last (fresh -> we send). The send SILENTLY FAILS (nothing appended). The old
    # substring probe would match that historical bubble and falsely mark delivered
    # (dropping the reply). Count-delta sees no NEW match -> not delivered, draft kept.
    reg, out = _run({
        "search_locate_conversation": ToolResult(ok=True, data={"located": True}),
        "send_chat_message": ToolResult(ok=True, data={"input_cleared": True}),
        "read_messages": [
            ToolResult(ok=True, data={"messages": [
                {"sender": "me", "text": "你好，方便聊聊吗"},  # old identical send
                {"sender": "hr", "text": "在吗"},              # HR spoke last -> fresh
            ]}),
            ToolResult(ok=True, data={"messages": [           # post: nothing appended
                {"sender": "me", "text": "你好，方便聊聊吗"},
                {"sender": "hr", "text": "在吗"},
            ]}),
        ],
    })
    assert out.submitted is True and out.delivered is False
    assert out.failure_reason == "deliver_unverified" and out.marked_sent is False
    assert "mark_reply_sent" not in reg.names()


def test_delivered_even_when_hr_interleaves_a_reply_in_verify_window():
    # Edge A: HR sends another message in the ~5s verify window, so the LAST bubble
    # is HR's, not ours. A "last message == sent" check would false-negative here;
    # count-delta still sees our new 'me' bubble -> delivered.
    reg, out = _run({
        "search_locate_conversation": ToolResult(ok=True, data={"located": True}),
        "send_chat_message": ToolResult(ok=True, data={"input_cleared": True}),
        "read_messages": [
            ToolResult(ok=True, data={"messages": [{"sender": "hr", "text": "在吗"}]}),
            ToolResult(ok=True, data={"messages": [
                {"sender": "hr", "text": "在吗"},
                {"sender": "me", "text": "你好，方便聊聊吗"},  # our reply landed
                {"sender": "hr", "text": "好的"},              # HR replied right after
            ]}),
        ],
    })
    assert out.delivered is True and out.marked_sent is True and out.failure_reason is None
    assert ("mark_reply_sent", {"conv_id": "c1"}) in reg.calls


def test_freshness_read_failure_keeps_draft():
    # Cannot re-scan -> cannot verify freshness -> skip WITHOUT voiding, so a
    # transient render glitch never destroys an approved reply (retries next run).
    reg, out = _run({
        "search_locate_conversation": ToolResult(ok=True, data={"located": True}),
        "read_messages": ToolResult(ok=False, data={"messages": []}, error="no bubbles rendered"),
    })
    assert out.failure_reason == "freshness_read_failed"
    assert "send_chat_message" not in reg.names()
    assert "invalidate_stale_reply" not in reg.names()


_REPLY_WITH_IDS = {**_REPLY, "job_id": "encJob1", "boss_conv_id": "encBoss1"}


def test_locate_prefers_direct_open_when_ids_present():
    # job_id + boss_conv_id present -> navigate_to_conversation (O(1) direct-open) is
    # used; the slow search box is NOT touched. dry_run short-circuits after locate.
    reg = FakeReg({"navigate_to_conversation": ToolResult(ok=True, data={"method": "direct_url"})})
    out = SendReplyPipeline(reg, logger=None, config=W3Config(dry_run=True)).run(_REPLY_WITH_IDS)
    assert out.located is True and out.failure_reason == "dry_run"
    assert "navigate_to_conversation" in reg.names()
    assert "search_locate_conversation" not in reg.names()


def test_locate_falls_back_to_search_when_direct_open_fails():
    # Direct-open failed (e.g. ids stale) -> fall back to the search box, which locates
    # it. Both are attempted, in order.
    reg = FakeReg({
        "navigate_to_conversation": ToolResult(ok=False, data={}, error="open didn't take"),
        "search_locate_conversation": ToolResult(ok=True, data={"located": True}),
    })
    out = SendReplyPipeline(reg, logger=None, config=W3Config(dry_run=True)).run(_REPLY_WITH_IDS)
    assert out.located is True and out.failure_reason == "dry_run"
    assert reg.names().index("navigate_to_conversation") < reg.names().index("search_locate_conversation")


def test_dry_run_locates_but_never_sends():
    reg, out = _run(
        {"search_locate_conversation": ToolResult(ok=True, data={"located": True})},
        dry_run=True,
    )
    assert out.located is True and out.failure_reason == "dry_run"
    assert "send_chat_message" not in reg.names()
