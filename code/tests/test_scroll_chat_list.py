"""Unit tests for ScrollChatList (W2 chat-list virtual scroll tool).

Covers the contract that ScanStep relies on: returning new items continues the
scroll loop, while reaching the end is a NORMAL termination (ok=True,
reached_end=True) -- not a failure. A FakePage stands in for DrissionPage:
_LIST_JS (scroll) returns None, _ITEMS_JS (extract) returns a configured item
list. _human_pause is patched to a no-op so tests don't sleep.
"""
import hashlib

import pytest

from tools.browser.w2 import scroll_chat_list as mod
from tools.browser.w2.scroll_chat_list import ScrollChatList


def _cid(hr_name: str, company: str) -> str:
    return hashlib.sha256(f"{hr_name}|{company}".encode()).hexdigest()[:12]


class FakePage:
    """run_js dispatcher: scroll scripts return None, item scripts return the
    next configured item list (last list repeats once exhausted)."""

    def __init__(self, items_sequence):
        self._items_seq = items_sequence
        self._items_idx = 0
        self.scroll_calls = 0

    def run_js(self, script):
        if "scrollHeight" in script or "scrollTop" in script:
            self.scroll_calls += 1
            return None
        if self._items_idx < len(self._items_seq):
            items = self._items_seq[self._items_idx]
        else:
            items = self._items_seq[-1] if self._items_seq else []
        self._items_idx += 1
        return items


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(mod, "_human_pause", lambda *a, **k: None)


def test_new_items_first_scroll():
    """An unseen conversation on the first scroll -> continue (reached_end False)."""
    page = FakePage([[{"hr_name": "Alice", "company": "Acme"}]])
    res = ScrollChatList(browser=page).execute(seen_conv_ids=[])

    assert res.ok
    assert res.data["reached_end"] is False
    assert res.data["attempts"] == 1
    assert page.scroll_calls == 1


def test_reached_end_is_normal_success():
    """No new items after the retry == end of list: ok=True, reached_end=True,
    no error (regression guard for the former ok=False/error behavior)."""
    seen = [_cid("Alice", "Acme")]
    only_seen = [{"hr_name": "Alice", "company": "Acme"}]
    page = FakePage([only_seen, only_seen])

    res = ScrollChatList(browser=page).execute(seen_conv_ids=seen)

    assert res.ok is True
    assert res.data["reached_end"] is True
    assert res.data["attempts"] == 2
    assert res.error is None
    assert page.scroll_calls == 2  # scrolled, found nothing new, retried once


def test_new_on_second_attempt():
    """Nothing new on the first scroll but new on the retry -> continue."""
    seen = [_cid("Alice", "Acme")]
    only_seen = [{"hr_name": "Alice", "company": "Acme"}]
    with_new = [
        {"hr_name": "Alice", "company": "Acme"},
        {"hr_name": "Bob", "company": "Beta"},
    ]
    page = FakePage([only_seen, with_new])

    res = ScrollChatList(browser=page).execute(seen_conv_ids=seen)

    assert res.ok
    assert res.data["reached_end"] is False
    assert res.data["attempts"] == 2


def test_browser_not_initialized():
    res = ScrollChatList(browser=None).execute(seen_conv_ids=[])
    assert not res.ok
    assert res.error


def test_run_js_exception_is_caught():
    class BoomPage:
        def run_js(self, script):
            raise RuntimeError("boom")

    res = ScrollChatList(browser=BoomPage()).execute(seen_conv_ids=[])
    assert not res.ok
    assert "boom" in res.error
