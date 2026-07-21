"""Unit tests for AcceptWechatCard (W2 auto-agree to an HR exchange-WeChat card).

The tool issues a single run_js that clicks 同意 on an active `.dialog-icon.weixin`
card and returns whether a click landed. It is idempotent by construction: once
agreed, Boss removes/disables the button, so run_js returns False and the tool is a
no-op (clicked=False), never re-clicking.
"""
import pytest

import tools.browser.w2.accept_wechat_card as mod
from tools.browser.w2.accept_wechat_card import AcceptWechatCard


class FakePage:
    def __init__(self, clicked):
        self._clicked = clicked

    def run_js(self, script):
        return self._clicked


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(mod, "_human_pause", lambda *a, **k: None)


def test_no_browser_is_error():
    res = AcceptWechatCard(browser=None).execute()
    assert not res.ok
    assert res.data["clicked"] is False


def test_active_card_gets_clicked():
    res = AcceptWechatCard(browser=FakePage(clicked=True)).execute()
    assert res.ok
    assert res.data == {"card_found": True, "clicked": True}


def test_no_active_card_is_noop():
    # No weixin card, or already agreed (button gone/disabled) -> run_js returns False.
    res = AcceptWechatCard(browser=FakePage(clicked=False)).execute()
    assert res.ok
    assert res.data == {"card_found": False, "clicked": False}
