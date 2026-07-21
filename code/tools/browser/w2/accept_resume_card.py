from tools.base import BaseTool, ToolResult
from tools.browser.helpers import (
    _ele_any,
    _human_pause,
    count_resume_delivered_markers,
    wait_resume_delivered,
)

_BOSS_DIALOG_CONFIRM = [
    "css:.boss-dialog__button:not(.button-outline)",
    "xpath://span[contains(@class,'boss-dialog__button')"
    " and not(contains(@class,'button-outline'))]",
]

# Python \uXXXX expands to actual chars at runtime; source stays ASCII-only.
# Text matched: confirm-resume-exchange dialog (overseas positions).
_XBORDER_XPATH = (
    "xpath://*[contains(text(),"
    "'\\u786e\\u5b9a\\u4e0e\\u5bf9\\u65b9\\u4ea4\\u6362\\u7b80\\u5386\\u5417')]"
)


class AcceptResumeCard(BaseTool):
    name = "accept_resume_card"
    description = "Click the Accept button on a Boss Zhipin resume exchange card"
    input_schema = {"type": "object", "properties": {}}

    def __init__(self, browser=None):
        self._browser = browser

    def execute(self) -> ToolResult:
        if self._browser is None:
            return ToolResult(
                ok=False,
                data={"card_found": False, "cross_border_dialog": False, "sent": False},
                error="browser not initialized",
            )
        page = self._browser
        try:
            # Baseline BEFORE accepting: existing delivered-resume markers.
            before = count_resume_delivered_markers(page)

            # JS \\uXXXX in Python string literal -> \uXXXX in JS -> agree button text.
            clicked = page.run_js(
                "var cards=document.querySelectorAll('.message-card-wrap');"
                "for(var i=cards.length-1;i>=0;i--){"
                "  var c=cards[i];"
                "  if(!c.querySelector('.dialog-icon.resume'))continue;"
                "  var btns=c.querySelectorAll('.card-btn:not(.disabled)');"
                "  for(var b of btns){"
                "    if(b.textContent.trim()==='\\u540c\\u610f'){b.click();return true;}"
                "  }"
                "}"
                "return false;"
            )

            if not clicked:
                return ToolResult(ok=True, data={"card_found": False, "cross_border_dialog": False, "sent": False})

            _human_pause(1.0, 1.5)

            # Cross-border confirm (overseas HR). We click confirm if present, but success
            # is judged on the delivered-resume system bubble, not on this dialog -- same
            # single source of truth as the toolbar path.
            cross_border = False
            if page.ele(_XBORDER_XPATH, timeout=3):
                cross_border = True
                confirm = _ele_any(page, _BOSS_DIALOG_CONFIRM, timeout=4)
                if confirm:
                    confirm.click()

            sent = wait_resume_delivered(page, before)
            return ToolResult(
                ok=bool(sent),
                data={"card_found": True, "cross_border_dialog": cross_border, "sent": sent},
                error=None if sent else "resume accept not confirmed (no new delivered-resume system message appeared)",
            )
        except Exception as exc:
            return ToolResult(
                ok=False,
                data={"card_found": False, "cross_border_dialog": False, "sent": False},
                error=str(exc),
            )
