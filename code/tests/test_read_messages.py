"""Unit tests for ReadMessages (W2 read-conversation-bubbles tool).

Pins the fail-fast contract: an open conversation that yields zero usable
messages is an INVALID state (navigation/render failure), not a valid empty
read, so it must return ok=False -- letting the per-conversation ReadStep fail
and the W2 loop move on to the next conversation.
"""
import pytest

import tools.browser.w2.read_messages as mod
from tools.browser.w2.read_messages import ReadMessages


class FakePage:
    """run_js dispatcher: the `.length` count probe returns a configured count,
    scroll scripts return None, and the extraction script returns a configured
    message list."""

    def __init__(self, count=0, messages=None):
        self._count = count
        self._messages = messages if messages is not None else []

    def run_js(self, script):
        if ".length" in script:
            return self._count
        if "scrollTop" in script:
            return None
        return self._messages


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(mod, "_human_pause", lambda *a, **k: None)


def test_empty_conversation_is_error():
    res = ReadMessages(browser=FakePage(count=0)).execute()
    assert not res.ok
    assert "no message bubbles" in res.error


def test_bubbles_present_but_none_extracted_is_error():
    res = ReadMessages(browser=FakePage(count=3, messages=[])).execute()
    assert not res.ok
    assert "0 messages extracted" in res.error


def test_messages_read_ok():
    msgs = [{"sender": "hr", "text": "hi", "time": "10:00"}]
    res = ReadMessages(browser=FakePage(count=1, messages=msgs)).execute()
    assert res.ok
    assert res.data["message_count"] == 1
    assert res.data["messages"] == msgs


def test_browser_not_initialized():
    res = ReadMessages(browser=None).execute()
    assert not res.ok
    assert res.error


def test_platform_tip_reclassified_to_system():
    # Boss nudge ("excellent competitors...") arrives with the item-friend DOM class
    # (sender='hr'); read_messages must retag it 'system' so it does not pollute
    # intent/reply-draft and renders as a centered notice, not an HR bubble.
    tip = "优秀竞争者会，建议你尽快沟通"
    msgs = [
        {"sender": "hr", "text": tip, "time": "10:00"},
        {"sender": "hr", "text": "real HR text", "time": "10:01"},
    ]
    res = ReadMessages(browser=FakePage(count=2, messages=msgs)).execute()
    assert res.ok
    out = res.data["messages"]
    assert out[0]["sender"] == "system"
    assert out[1]["sender"] == "hr"  # genuine HR text untouched
