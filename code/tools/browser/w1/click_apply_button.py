import re

from tools.base import BaseTool, ToolResult
from tools.browser.helpers import _ele_any, _human_pause

# 立即沟通 button selectors (search panel and job detail page)
_APPLY_BTN_SELECTORS = [
    ".op-btn-chat",
    ".btn-startchat",
    "xpath://a[contains(text(),'立即沟通')]",
    "xpath://button[contains(text(),'立即沟通')]",
]

# 已向BOSS发送消息 success dialog
_APPLY_SUCCESS_DIALOG_SELECTORS = [
    "css:.greet-boss-dialog",
    "css:.greet-boss-container",
    "xpath://*[contains(text(),'已向Boss发送消息')]",
    "xpath://*[contains(text(),'已向BOSS发送消息')]",
]

# Boss risk-control quota reminder ("温馨提示 / 您今天已与N位BOSS沟通，还剩M次沟通机会").
# It pops IN PLACE OF the success dialog once we near the daily greeting cap. Its
# appearance right after our click means the greeting WAS processed -- Boss's own
# counter already includes it. Verified 2026-07-04: at 08:17 Boss's dialog reported
# 120 greetings sent while our DB had recorded only 34 for the day, i.e. ~86 real
# sends had been mis-recorded as `dialog_blocked` (its single success selector above
# missed them because this reminder covered the success dialog). So a FRESH post-click
# quota dialog counts as a successful apply; we stop the run only on the hard cap.
_QUOTA_DIALOG_SELECTORS = [
    "xpath://*[contains(text(),'沟通机会')]",
    "xpath://*[contains(text(),'您今天已与')]",
    "xpath://*[contains(text(),'达到上限')]",
    "xpath://*[contains(text(),'沟通次数')]",
]

# 好 / 我知道了 confirm button that dismisses the quota reminder. Dismissing is
# essential: an un-dismissed reminder lingers in the DOM and blocks EVERY following
# card (today it stayed frozen at "120/还剩30" across an hour of runs -> 456 phantom
# dialog_blocked failures because nothing ever closed it).
_QUOTA_CONFIRM_BTN_SELECTORS = [
    "xpath://*[contains(@class,'boss-btn')][normalize-space(text())='好']",
    "xpath://button[normalize-space(text())='好']",
    "xpath://a[normalize-space(text())='好']",
    "xpath://*[normalize-space(text())='我知道了']",
]

# Text markers of the HARD cap (no greetings left) -> stop the whole run.
_HARD_LIMIT_MARKERS = ("达到上限", "次数已用完", "已用完", "明天再来")

# quota dialog innerText probe (CJK as \uXXXX to keep CJK bytes out of the JS source,
# per the helpers.py / read_messages.py convention):
#   沟通机会 = 沟通机会   达到上限 = 达到上限   沟通次数 = 沟通次数
_QUOTA_TEXT_JS = (
    "var ns=document.querySelectorAll('div,p,span');var best='';"
    "for(var i=0;i<ns.length;i++){var t=(ns[i].innerText||'').trim();"
    "if(t.indexOf('\\u6c9f\\u901a\\u673a\\u4f1a')!==-1||"
    "t.indexOf('\\u8fbe\\u5230\\u4e0a\\u9650')!==-1||"
    "t.indexOf('\\u6c9f\\u901a\\u6b21\\u6570')!==-1){"
    "if(best===''||t.length<best.length)best=t;}}return best;"
)


def _read_quota_text(page) -> str:
    """Return the shortest element text mentioning the quota reminder, or ''."""
    try:
        return page.run_js(_QUOTA_TEXT_JS) or ""
    except Exception:
        return ""


def _is_hard_limit(text: str) -> bool:
    if not text:
        return False
    if any(m in text for m in _HARD_LIMIT_MARKERS):
        return True
    m = re.search(r"还剩\s*(\d+)", text)
    return bool(m) and int(m.group(1)) == 0


def _dismiss_quota_dialog(page) -> None:
    btn = _ele_any(page, _QUOTA_CONFIRM_BTN_SELECTORS, timeout=1)
    if btn:
        try:
            btn.click()
        except Exception:
            pass
    else:
        # No 好 button matched: fall back to a real keyboard Escape (a synthetic JS
        # event does not trigger Boss's handlers -- verified pitfall).
        try:
            page.actions.key_down("Escape").key_up("Escape")
        except Exception:
            pass
    _human_pause(0.4, 0.8)


class ClickApplyButton(BaseTool):
    name = "click_apply_button"
    description = "Click the apply button (立即沟通) in the job detail panel"
    input_schema = {
        "type": "object",
        "properties": {"dry_run": {"type": "boolean"}},
        "required": ["dry_run"],
    }

    def __init__(self, browser=None):
        self._browser = browser

    def execute(self, dry_run: bool = False) -> ToolResult:
        # dry_run requires no browser interaction — check before the browser guard
        if dry_run:
            return ToolResult(ok=True, data={"result": "dry_run"})

        if self._browser is None:
            return ToolResult(ok=False, data={}, error="browser not initialized")

        page = self._browser
        try:
            # A quota reminder left over from a PREVIOUS card is stale: this card was
            # never clicked, so it is NOT a send -- do not count it. Dismiss it and
            # bail as blocked so it stops covering the next card's success dialog. If
            # it is the hard cap, stop the whole run.
            if _ele_any(page, _QUOTA_DIALOG_SELECTORS, timeout=0):
                text = _read_quota_text(page)
                _dismiss_quota_dialog(page)
                if _is_hard_limit(text):
                    return ToolResult(ok=True, data={"result": "rate_limited", "message": text})
                return ToolResult(ok=True, data={"result": "dialog_blocked", "reason": "stale_quota_dialog"})

            apply_btn = _ele_any(page, _APPLY_BTN_SELECTORS, timeout=3)
            if not apply_btn:
                return ToolResult(ok=True, data={"result": "button_not_found"})

            btn_text = (apply_btn.text or "").strip()
            # 继续沟通 means an active conversation already exists;
            # clicking would navigate away from the search page.
            if "继续沟通" in btn_text:
                return ToolResult(ok=True, data={"result": "already_chatting"})

            # A success dialog still showing BEFORE we click means the previous
            # card's dialog was never dismissed. If we clicked now, the post-click
            # success check below would match this STALE dialog and falsely report
            # "applied" without any real greeting being sent (the actual bug: a run
            # recorded 10 applies but only 1 greeting went out). Bail as blocked so
            # the caller records no phantom application and clears the dialog.
            if _ele_any(page, _APPLY_SUCCESS_DIALOG_SELECTORS, timeout=0):
                return ToolResult(ok=True, data={"result": "dialog_blocked", "reason": "stale_success_dialog"})

            apply_btn.click()
            _human_pause(1.5, 2.5)

            # 1) explicit success dialog — the unambiguous confirmation.
            if _ele_any(page, _APPLY_SUCCESS_DIALOG_SELECTORS, timeout=5):
                return ToolResult(ok=True, data={"result": "applied"})

            # 2) quota reminder popped instead of the success dialog: the greeting WAS
            #    sent (Boss's counter includes it). Dismiss it so it can't block the
            #    next card, and stop the run only if it is the hard cap.
            if _ele_any(page, _QUOTA_DIALOG_SELECTORS, timeout=0):
                text = _read_quota_text(page)
                hard = _is_hard_limit(text)
                _dismiss_quota_dialog(page)
                if hard:
                    return ToolResult(ok=True, data={"result": "rate_limited", "message": text})
                return ToolResult(ok=True, data={"result": "applied", "quota_notice": text})

            # 3) the apply button flipped 立即沟通 -> 继续沟通: an active conversation
            #    now exists, so the greeting landed even though no dialog was detected.
            after_btn = _ele_any(page, _APPLY_BTN_SELECTORS, timeout=0)
            if after_btn and "继续沟通" in (after_btn.text or ""):
                return ToolResult(ok=True, data={"result": "applied", "confirmed_by": "button_flip"})

            # 4) no success signal at all (e.g. a silent post-cap no-op where the
            #    button stays 立即沟通) -> genuinely not sent.
            return ToolResult(ok=True, data={"result": "dialog_blocked"})
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=str(exc))
