import time

from tools.base import BaseTool, ToolResult
from tools.browser.helpers import _human_pause

_COUNT_JS = "return document.querySelectorAll('.job-card-wrap').length;"
_SCROLL_WAIT_SECS = 6


class ScrollSearchResults(BaseTool):
    name = "scroll_search_results"
    description = "Scroll down the search results page to trigger lazy-loading of more job cards"
    input_schema = {
        "type": "object",
        "properties": {"current_card_count": {"type": "integer"}},
        "required": ["current_card_count"],
    }

    def __init__(self, browser=None):
        self._browser = browser

    def _scroll_once(self, page, current_card_count: int) -> int:
        """Scroll to bottom and wait up to _SCROLL_WAIT_SECS for new cards.
        Returns the observed card count (unchanged if no new cards appeared)."""
        page.run_js("window.scrollTo(0, document.body.scrollHeight)")
        _human_pause(1.0, 2.0)
        deadline = time.time() + _SCROLL_WAIT_SECS
        while time.time() < deadline:
            count = page.run_js(_COUNT_JS) or 0
            if count > current_card_count:
                return count
            time.sleep(0.5)
        return current_card_count

    def execute(self, current_card_count: int = 0) -> ToolResult:
        if self._browser is None:
            return ToolResult(ok=False, data={}, error="browser not initialized")
        page = self._browser
        try:
            new_count = self._scroll_once(page, current_card_count)
            if new_count > current_card_count:
                return ToolResult(ok=True, data={
                    "new_card_count": new_count,
                    "reached_end": False,
                    "attempts": 1,
                })

            # No new cards on first attempt — retry once
            new_count = self._scroll_once(page, current_card_count)
            if new_count > current_card_count:
                return ToolResult(ok=True, data={
                    "new_card_count": new_count,
                    "reached_end": False,
                    "attempts": 2,
                })

            # Still no new cards after retry — signal stop
            return ToolResult(
                ok=False,
                data={"new_card_count": new_count, "attempts": 2},
                error="no_new_cards_after_retry",
            )
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=str(exc))
