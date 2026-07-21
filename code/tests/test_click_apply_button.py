"""Unit tests for ClickApplyButton (W1 apply-click + result classification).

Focus: the 2026-07-04 undercount fix. Boss's daily-cap "温馨提示 / 您今天已与N位
BOSS沟通，还剩M次沟通机会" reminder pops IN PLACE OF the success dialog once we near
the greeting cap. The old tool only recognized the success dialog, so these real
sends were mis-recorded as dialog_blocked (Boss counted 120 while our DB had 34).

These tests drive the tool with a FakePage that flips from a pre-click to a post-click
DOM state when the apply button is clicked, and assert each result classification.
"""
import pytest

import tools.browser.w1.click_apply_button as mod
from tools.browser.w1.click_apply_button import ClickApplyButton


def _group(selector: str) -> str:
    s = selector
    if any(k in s for k in ("沟通机会", "您今天已与", "达到上限", "沟通次数")):
        return "quota"
    if ("greet-boss" in s) or ("已向Boss" in s) or ("已向BOSS" in s):
        return "success"
    if ("好" in s) or ("我知道了" in s):
        return "quota_confirm"
    if ("立即沟通" in s) or ("op-btn-chat" in s) or ("btn-startchat" in s):
        return "apply_btn"
    return "other"


class FakeEle:
    def __init__(self, text="", page=None, is_apply=False):
        self.text = text
        self._page = page
        self._is_apply = is_apply
        self.clicked = False

    def click(self):
        self.clicked = True
        if self._is_apply and self._page is not None:
            self._page.mode = "after"


class FakeActions:
    def __init__(self):
        self.escaped = False

    def key_down(self, k):
        return self

    def key_up(self, k):
        self.escaped = True
        return self


class FakePage:
    def __init__(
        self,
        *,
        apply_text="立即沟通",
        apply_text_after=None,
        button_found=True,
        success_before=False,
        success_after=False,
        quota_before="",
        quota_after="",
        quota_confirm=True,
    ):
        self.mode = "before"
        self.apply_text = apply_text
        self.apply_text_after = apply_text_after
        self.button_found = button_found
        self.success_before = success_before
        self.success_after = success_after
        self.quota_before = quota_before
        self.quota_after = quota_after
        self.quota_confirm = quota_confirm
        self.actions = FakeActions()

    def _after(self):
        return self.mode == "after"

    def ele(self, selector, timeout=0):
        g = _group(selector)
        if g == "apply_btn":
            if not self.button_found:
                return None
            txt = self.apply_text_after if (self._after() and self.apply_text_after is not None) else self.apply_text
            return FakeEle(text=txt, page=self, is_apply=True)
        if g == "success":
            present = self.success_after if self._after() else self.success_before
            return FakeEle() if present else None
        if g == "quota":
            text = self.quota_after if self._after() else self.quota_before
            return FakeEle() if text else None
        if g == "quota_confirm":
            return FakeEle() if self.quota_confirm else None
        return None

    def run_js(self, script):
        return self.quota_after if self._after() else self.quota_before


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(mod, "_human_pause", lambda *a, **k: None)


def test_dry_run_no_browser_needed():
    res = ClickApplyButton(browser=None).execute(dry_run=True)
    assert res.ok and res.data["result"] == "dry_run"


def test_no_browser_is_error():
    res = ClickApplyButton(browser=None).execute(dry_run=False)
    assert not res.ok


def test_success_dialog_is_applied():
    page = FakePage(success_after=True)
    res = ClickApplyButton(browser=page).execute(dry_run=False)
    assert res.ok and res.data["result"] == "applied"


def test_button_not_found():
    page = FakePage(button_found=False)
    res = ClickApplyButton(browser=page).execute(dry_run=False)
    assert res.ok and res.data["result"] == "button_not_found"


def test_already_chatting_when_button_says_continue():
    page = FakePage(apply_text="继续沟通")
    res = ClickApplyButton(browser=page).execute(dry_run=False)
    assert res.ok and res.data["result"] == "already_chatting"


def test_post_click_quota_warning_counts_as_applied():
    # The greeting WAS sent; Boss's reminder just covered the success dialog.
    page = FakePage(quota_after="您今天已与120位BOSS沟通，还剩30次沟通机会哦")
    res = ClickApplyButton(browser=page).execute(dry_run=False)
    assert res.ok
    assert res.data["result"] == "applied"
    assert "quota_notice" in res.data


def test_post_click_hard_cap_is_rate_limited():
    page = FakePage(quota_after="今日沟通次数已达到上限，明天再来")
    res = ClickApplyButton(browser=page).execute(dry_run=False)
    assert res.ok and res.data["result"] == "rate_limited"
    assert res.data["message"]


def test_hard_cap_by_zero_remaining_is_rate_limited():
    page = FakePage(quota_after="您今天已与150位BOSS沟通，还剩0次沟通机会")
    res = ClickApplyButton(browser=page).execute(dry_run=False)
    assert res.ok and res.data["result"] == "rate_limited"


def test_stale_quota_dialog_pre_click_is_blocked_not_counted():
    # A leftover reminder from a PREVIOUS card: this card was never clicked, so it is
    # not a send. Bail as blocked (and it gets dismissed so it stops covering cards).
    page = FakePage(quota_before="您今天已与120位BOSS沟通，还剩30次沟通机会哦")
    res = ClickApplyButton(browser=page).execute(dry_run=False)
    assert res.ok
    assert res.data["result"] == "dialog_blocked"
    assert res.data.get("reason") == "stale_quota_dialog"


def test_stale_quota_dialog_hard_cap_pre_click_stops_run():
    page = FakePage(quota_before="今日沟通次数已达到上限")
    res = ClickApplyButton(browser=page).execute(dry_run=False)
    assert res.ok and res.data["result"] == "rate_limited"


def test_button_flip_confirms_send_without_dialog():
    # No success dialog, no quota reminder, but the button flipped to 继续沟通 -> an
    # active conversation now exists, so the greeting landed.
    page = FakePage(apply_text="立即沟通", apply_text_after="继续沟通")
    res = ClickApplyButton(browser=page).execute(dry_run=False)
    assert res.ok and res.data["result"] == "applied"
    assert res.data.get("confirmed_by") == "button_flip"


def test_no_signal_is_dialog_blocked():
    # Silent post-cap no-op: button stays 立即沟通, nothing pops. Genuinely not sent.
    page = FakePage(apply_text="立即沟通", apply_text_after="立即沟通")
    res = ClickApplyButton(browser=page).execute(dry_run=False)
    assert res.ok and res.data["result"] == "dialog_blocked"
    assert "reason" not in res.data
