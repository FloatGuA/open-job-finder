import time

from tools.base import BaseTool, ToolResult
from tools.browser.helpers import _ele_any, _human_pause

# 已向BOSS发送消息 success dialog
_APPLY_SUCCESS_DIALOG_SELECTORS = [
    "css:.greet-boss-dialog",
    "css:.greet-boss-container",
    "xpath://*[contains(text(),'已向Boss发送消息')]",
    "xpath://*[contains(text(),'已向BOSS发送消息')]",
]

# 留在此页 button inside the success dialog footer. Match by class AND by visible
# text so a tag/class rename can't silently break dismissal. Text targets 留在此页
# specifically and never 继续沟通 (boss-btn-primary), which would navigate into the
# chat page. (The class-scoped `a.boss-btn-cancel` was observed to miss when the
# button is not an <a>; the tag-agnostic and text selectors cover that.)
_STAY_ON_PAGE_BTN_SELECTORS = [
    "css:.greet-boss-dialog a.boss-btn-cancel",
    "css:.greet-boss-dialog .boss-btn-cancel",
    "xpath://div[contains(@class,'greet-boss-dialog')]//a[contains(@class,'boss-btn-cancel')]",
    "xpath://div[contains(@class,'greet-boss-dialog')]//*[contains(text(),'留在此页')]",
]

_DIALOG_CLOSE_TIMEOUT = 2.0


class HandleApplyDialog(BaseTool):
    name = "handle_apply_dialog"
    description = "Detect and optionally close the post-apply success dialog, waiting for DOM unmount"
    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["close_and_wait", "check_only"]},
        },
        "required": ["action"],
    }

    def __init__(self, browser=None):
        self._browser = browser

    def execute(self, action: str = "check_only") -> ToolResult:
        if self._browser is None:
            return ToolResult(ok=False, data={}, error="browser not initialized")
        page = self._browser
        try:
            dialog = _ele_any(page, _APPLY_SUCCESS_DIALOG_SELECTORS, timeout=0)
            dialog_was_present = bool(dialog)

            if action == "check_only":
                return ToolResult(ok=True, data={
                    "dialog_was_present": dialog_was_present,
                    "dialog_closed": False,
                })

            # close_and_wait: dismiss dialog and wait for React async unmount
            dialog_closed = not dialog_was_present  # vacuously closed when absent
            button_clicked = "none"
            stay_button_found = False
            dialog_buttons = ""  # captured DOM when the stay button is missing

            if dialog_was_present:
                stay_btn = _ele_any(page, _STAY_ON_PAGE_BTN_SELECTORS, timeout=3)
                if stay_btn:
                    stay_button_found = True
                    stay_btn.click()
                    button_clicked = "stay_on_page"
                else:
                    # Stay button not found. Capture the dialog's button DOM so the
                    # failure reveals the real structure instead of guessing, then
                    # dismiss via a REAL keyboard Escape: a synthetic JS KeyboardEvent
                    # does NOT trigger Boss's framework handlers (verified pitfall),
                    # which is why the old dispatchEvent fallback left the dialog open.
                    # page.actions is the only working keyboard entry point.
                    try:
                        dialog_buttons = page.run_js(
                            "var d=document.querySelector('.greet-boss-dialog');"
                            "return d?Array.from(d.querySelectorAll('a,button')).map("
                            "function(e){return e.tagName+'.'+e.className+':'+((e.innerText||'').trim())}"
                            ").join(' | '):''"
                        )
                    except Exception:
                        dialog_buttons = ""
                    try:
                        page.actions.key_down("Escape").key_up("Escape")
                    except Exception:
                        pass
                    button_clicked = "escape_fallback"
                _human_pause(0.5, 1.0)

                # Poll until .greet-boss-dialog disappears (React async DOM unmount)
                deadline = time.time() + _DIALOG_CLOSE_TIMEOUT
                while time.time() < deadline:
                    if not page.ele("css:.greet-boss-dialog", timeout=0):
                        dialog_closed = True
                        break
                    time.sleep(0.2)

            return ToolResult(ok=True, data={
                "dialog_was_present": dialog_was_present,
                "stay_button_found": stay_button_found,
                "button_clicked": button_clicked,
                "dialog_closed": dialog_closed,
                "dialog_buttons": dialog_buttons,
            })
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=str(exc))
