import hashlib
from typing import List

from tools.base import BaseTool, ToolResult
from tools.browser.helpers import _human_pause


def _conv_id(hr_name: str, company: str) -> str:
    return hashlib.sha256(f"{hr_name}|{company}".encode()).hexdigest()[:12]


_LIST_JS = """
    var c = document.querySelector('.user-list-content') || document.querySelector('.user-list');
    if (c) { c.scrollTop = c.scrollHeight; }
    else { window.scrollTo(0, document.body.scrollHeight); }
"""

_ITEMS_JS = """
    var items = document.querySelectorAll('.friend-content-warp');
    if (!items.length) items = document.querySelectorAll('li[role="listitem"]');
    var result = [];
    items.forEach(function(item) {
        var nameEl = item.querySelector('.name-text');
        var hr_name = nameEl ? nameEl.textContent.trim() : '';
        var company = '';
        var nameBox = item.querySelector('.name-box');
        if (nameBox) {
            var spans = nameBox.querySelectorAll('span');
            if (spans.length > 1) company = spans[1].textContent.trim();
        }
        result.push({hr_name: hr_name, company: company});
    });
    return result;
"""


class ScrollChatList(BaseTool):
    name = "scroll_chat_list"
    description = "Scroll Boss Zhipin virtual-scroll chat list to load more conversations"
    input_schema = {
        "type": "object",
        "properties": {
            "seen_conv_ids": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["seen_conv_ids"],
    }

    def __init__(self, browser=None):
        self._browser = browser

    def _has_new(self, page, seen_set: set) -> bool:
        items = page.run_js(_ITEMS_JS)
        if not isinstance(items, list):
            return False
        return any(
            _conv_id(item.get("hr_name", ""), item.get("company", "")) not in seen_set
            for item in items
        )

    def execute(self, seen_conv_ids: List[str] = None) -> ToolResult:
        if self._browser is None:
            return ToolResult(ok=False, data={}, error="browser not initialized")
        seen_set = set(seen_conv_ids) if seen_conv_ids else set()
        page = self._browser
        try:
            page.run_js(_LIST_JS)
            _human_pause(1.5, 2.5)

            if self._has_new(page, seen_set):
                return ToolResult(ok=True, data={"reached_end": False, "attempts": 1})

            # No new items — retry once
            page.run_js(_LIST_JS)
            _human_pause(1.5, 2.5)

            if self._has_new(page, seen_set):
                return ToolResult(ok=True, data={"reached_end": False, "attempts": 2})

            # No new items after retry == reached the end of the list. This is a
            # normal, expected termination, not a failure -- signal it via
            # reached_end so ScanStep stops cleanly and the tool log stays green.
            return ToolResult(ok=True, data={"reached_end": True, "attempts": 2})
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=str(exc))
