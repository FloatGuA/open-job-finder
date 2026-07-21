from tools.base import BaseTool, ToolResult
from tools.browser.helpers import (
    _human_pause,
    count_resume_delivered_markers,
    wait_resume_delivered,
)


class ClickToolbarSendResume(BaseTool):
    name = "click_toolbar_send_resume"
    description = "Click the Send Resume toolbar button in Boss Zhipin chat"
    input_schema = {"type": "object", "properties": {}}

    def __init__(self, browser=None):
        self._browser = browser

    def execute(self) -> ToolResult:
        if self._browser is None:
            return ToolResult(
                ok=False,
                data={"button_found": False, "button_enabled": False, "sent": False},
                error="browser not initialized",
            )
        page = self._browser
        try:
            # JS \\uXXXX -> \uXXXX in JS -> send-resume button text (no CJK bytes in source).
            result = page.run_js(
                "var btn=document.querySelector('[d-c=\"62009\"]');"
                "if(btn){"
                "  return {found:true,enabled:!btn.classList.contains('unable')};"
                "}"
                "var all=document.querySelectorAll('button,span[class],div[class]');"
                "for(var i=0;i<all.length;i++){"
                "  var el=all[i];"
                "  if(el.children.length===0&&el.textContent.trim()==='\\u53d1\\u7b80\\u5386'){"
                "    return{found:true,enabled:!el.classList.contains('unable')&&!el.disabled};"
                "  }"
                "}"
                "return{found:false,enabled:false};"
            )

            if not isinstance(result, dict):
                result = {"found": False, "enabled": False}

            button_found = bool(result.get("found"))
            button_enabled = bool(result.get("enabled"))

            if not button_found:
                return ToolResult(ok=True, data={"button_found": False, "button_enabled": False, "sent": False})
            if not button_enabled:
                return ToolResult(ok=True, data={"button_found": True, "button_enabled": False, "sent": False})

            # Baseline BEFORE clicking: how many delivered-resume markers already exist.
            before = count_resume_delivered_markers(page)

            page.run_js(
                "var btn=document.querySelector('[d-c=\"62009\"]');"
                "if(btn&&!btn.classList.contains('unable')){btn.click();return;}"
                "var all=document.querySelectorAll('button,span[class],div[class]');"
                "for(var i=0;i<all.length;i++){"
                "  var el=all[i];"
                "  if(el.children.length===0&&el.textContent.trim()==='\\u53d1\\u7b80\\u5386'){"
                "    if(!el.classList.contains('unable')&&!el.disabled){el.click();return;}"
                "  }"
                "}"
            )
            _human_pause(1.0, 1.5)

            # Boss shows a SECOND-step cross-border confirm popover ONLY when the HR's
            # account is used outside mainland China (verified 2026-06-11:
            # div.panel-resume.sentence-popover, confirm button span.btn-sure-v2). For
            # mainland HRs the click sends directly with no popover. We click the confirm
            # if the popover is up, but success is NOT judged on the popover -- it is
            # judged on a NEW delivered-resume system bubble appearing (the single source
            # of truth, identical to the card-accept path). So a stuck/unrecognized
            # popover simply yields sent=False instead of a false success.
            popover_sel = ".panel-resume.sentence-popover"
            cross_border = bool(page.run_js(
                "var d=document.querySelector('" + popover_sel + "');"
                "if(!d)return false;var r=d.getBoundingClientRect();"
                "return r.width>0&&r.height>0;"
            ))
            if cross_border:
                page.run_js(
                    "var d=document.querySelector('" + popover_sel + "');"
                    "if(d){var b=d.querySelector('.btn-sure-v2');if(b){b.click();}}"
                )

            # Authoritative success check: a NEW delivered-resume system bubble appeared.
            sent = wait_resume_delivered(page, before)
            return ToolResult(
                ok=bool(sent),
                data={
                    "button_found": True, "button_enabled": True,
                    "cross_border_dialog": cross_border, "sent": sent,
                },
                error=None if sent else "resume send not confirmed (no new delivered-resume system message appeared)",
            )
        except Exception as exc:
            return ToolResult(
                ok=False,
                data={"button_found": False, "button_enabled": False, "sent": False},
                error=str(exc),
            )
