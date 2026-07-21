from tools.base import BaseTool, ToolResult
from tools.browser.helpers import _ele_any, _human_pause

_BASE_URL = "https://www.zhipin.com"
_CHAT_URL = f"{_BASE_URL}/web/geek/chat"
_LIST_CONTAINER_SELECTORS = [".user-list-content", ".user-list"]


class NavigateToChatList(BaseTool):
    name = "navigate_to_chat_list"
    description = "Navigate to Boss Zhipin chat list page and wait for the list container to appear"
    input_schema = {
        "type": "object",
        "properties": {
            "force": {
                "type": "boolean",
                "description": "Force a full reload even if already on the chat page (used by scan retry).",
            },
        },
    }

    def __init__(self, browser=None):
        self._browser = browser

    def execute(self, force: bool = False) -> ToolResult:
        if self._browser is None:
            return ToolResult(ok=False, data={}, error="browser not initialized")
        page = self._browser
        try:
            current_url = page.url or ""
            if not force and _CHAT_URL in current_url:
                # Already on chat page — verify container is present
                container = _ele_any(page, _LIST_CONTAINER_SELECTORS, timeout=3)
                if container:
                    return ToolResult(ok=True, data={"loaded_url": current_url, "navigated": False})
            page.get(_CHAT_URL, timeout=30)
            _human_pause(3.0, 6.0)
            container = _ele_any(page, _LIST_CONTAINER_SELECTORS, timeout=10)
            if container is None:
                return ToolResult(ok=False, data={}, error="chat list container not found after navigation")
            loaded_url = page.url or _CHAT_URL
            return ToolResult(ok=True, data={"loaded_url": loaded_url, "navigated": True})
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=str(exc))
