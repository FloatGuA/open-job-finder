from tools.base import BaseTool, ToolResult
from tools.browser.helpers import _ele_any, _human_pause

_CHAT_INPUT_SELECTORS = [
    "css:#chat-input[contenteditable='true']",
    "css:.chat-input[contenteditable='true']",
    "css:.chat-editor [contenteditable='true']",
    "css:div[contenteditable='true']",
]


class SendChatMessage(BaseTool):
    name = "send_chat_message"
    description = "Type and send a text message in the currently open Boss Zhipin conversation"
    input_schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    }

    def __init__(self, browser=None):
        self._browser = browser

    def execute(self, text: str) -> ToolResult:
        if self._browser is None:
            return ToolResult(ok=False, data={}, error="browser not initialized")
        page = self._browser
        try:
            inp = _ele_any(page, _CHAT_INPUT_SELECTORS, timeout=3)
            if not inp:
                return ToolResult(ok=False, data={}, error="chat input not found")

            inp.click()
            # Boss direct uses a React contenteditable div; keyboard simulation fails for
            # CJK because IME composition cannot be reproduced via keydown/keyup. Use
            # execCommand('insertText') instead, which React's reconciler intercepts.
            # Note: execCommand is deprecated per spec but still supported in Chrome 2025.
            page.run_js(
                "var el = document.querySelector('#chat-input')"
                "  || document.querySelector('.chat-input[contenteditable]');"
                "if (!el) return;"
                "el.focus();"
                "el.innerHTML = '';"
                "document.execCommand('selectAll', false, null);"
                "document.execCommand('insertText', false, arguments[0]);"
                "if (!el.textContent) {"
                "  el.innerText = arguments[0];"
                "  el.dispatchEvent(new Event('input', {bubbles: true}));"
                "}",
                text,
            )
            _human_pause(0.5, 1.0)

            actual = page.run_js(
                "var el = document.querySelector('#chat-input')"
                "  || document.querySelector('.chat-input[contenteditable]');"
                "return el ? el.textContent : '';"
            )
            if not actual or not actual.strip():
                return ToolResult(ok=False, data={}, error="text not set in input field")

            # Submit via the explicit 发送 button. A bare Enter in the
            # contenteditable inserts a NEWLINE for multi-line replies instead of
            # sending (root of the "marked sent but never delivered" false success).
            # Button is `button.btn-send`, carries `disabled` class until non-empty.
            clicked = page.run_js(
                "var b = document.querySelector('button.btn-send');"
                "if (b && b.className.indexOf('disabled') === -1 && !b.disabled) { b.click(); return true; }"
                "return false;"
            )
            if not clicked:
                # Fallback for layouts without the button (DrissionPage 4.1.x:
                # page.actions is the only correct keyboard entry point).
                page.actions.key_down("Enter").key_up("Enter")
            _human_pause(1.0, 1.5)

            # Proxy completion check: the input clears after a successful submit.
            # Authoritative delivery confirmation is the caller's VerifyReplyDelivered.
            after = page.run_js(
                "var el = document.querySelector('#chat-input')"
                "  || document.querySelector('.chat-input[contenteditable]');"
                "return el ? el.textContent : '';"
            )
            input_cleared = not (after or "").strip()
            return ToolResult(ok=True, data={
                "submit": "button" if clicked else "enter",
                "input_cleared": input_cleared,
            })
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=str(exc))
