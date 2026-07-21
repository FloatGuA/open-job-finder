"""Unit tests for NavigateToConversation (W2 open-a-conversation tool).

Guards two fixes:
- the find-by-click fallback JS must be valid (an earlier f-string version
  emitted `scrollIntoView({{...}})` -- literal double braces -- which is a JS
  SyntaxError that made the whole fallback throw every time);
- the card match must use BOTH hr_name and company (company alone selects the
  first card of that company, i.e. the wrong HR when several conversations share
  a company).
"""
import pytest

import tools.browser.w2.navigate_to_conversation as mod
from tools.browser.w2.navigate_to_conversation import NavigateToConversation

_URL = "https://www.zhipin.com/web/geek/chat?conversationId=XYZ"


class FakePage:
    def __init__(self, found_idx=0, url=_URL):
        self.scripts = []
        self.got = None
        self._found = found_idx
        self.url = url

    def get(self, url, timeout=None):
        self.got = url

    def run_js(self, script):
        self.scripts.append(script)
        # The card-find script returns the matched index; scroll scripts return None.
        if "friend-content-warp" in script:
            return self._found
        return None


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(mod, "_human_pause", lambda *a, **k: None)


def test_find_js_is_valid_and_matches_hr_and_company():
    page = FakePage(found_idx=0)
    res = NavigateToConversation(browser=page).execute(
        conv_id="c1", company="Acme", hr_name="Zhang",
    )
    assert res.ok
    assert res.data["method"] == "js_click"
    assert res.data["boss_conv_id_confirmed"] == "XYZ"

    find_js = next(s for s in page.scripts if "friend-content-warp" in s)
    # regression: no double-open-brace (the old invalid `scrollIntoView({{...}})`)
    assert "{{" not in find_js
    # match keys on BOTH hr_name and company
    assert "'Acme'" in find_js and "'Zhang'" in find_js
    assert "&& hr===" in find_js
    # the click must target the inner .friend-content (clicking the outer
    # .friend-content-warp does not open the conversation)
    assert "querySelector('.friend-content')" in find_js


def test_not_found_returns_error():
    page = FakePage(found_idx=-1)  # card never matches
    res = NavigateToConversation(browser=page).execute(
        conv_id="c1", company="Ghost", hr_name="Nobody",
    )
    assert not res.ok
    assert "not found" in res.error


def test_boss_conv_id_is_ignored_and_click_is_used():
    # d-c (the boss_conv_id source) is a constant, not a per-conversation id, so the
    # tool must NOT navigate by URL even when a boss_conv_id is supplied -- it should
    # still find the card by hr_name + company and click it.
    page = FakePage(found_idx=0)
    res = NavigateToConversation(browser=page).execute(
        conv_id="c1", company="Acme", hr_name="Zhang", boss_conv_id="62001",
    )
    assert res.ok
    assert res.data["method"] == "js_click"
    assert page.got is None  # no URL-direct navigation happened
    assert any("friend-content-warp" in s for s in page.scripts)


def test_browser_not_initialized():
    res = NavigateToConversation(browser=None).execute(
        conv_id="c1", company="A", hr_name="B",
    )
    assert not res.ok
    assert res.error
