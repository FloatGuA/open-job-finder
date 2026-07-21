from tools.base import BaseTool, ToolResult
from tools.browser.helpers import _human_pause

_BASE_URL = "https://www.zhipin.com"


class NavigateSearchUrl(BaseTool):
    name = "navigate_search_url"
    description = "Open Boss Zhipin search URL and wait for the page to stabilize"
    input_schema = {
        "type": "object",
        "properties": {"url": {"type": "string"}},
        "required": ["url"],
    }

    def __init__(self, browser=None):
        self._browser = browser

    def execute(self, url: str = "") -> ToolResult:
        if self._browser is None:
            return ToolResult(ok=False, data={}, error="browser not initialized")
        page = self._browser
        try:
            # Establish a realistic Referer chain via homepage before navigating to search
            current_url = page.url or ""
            if _BASE_URL not in current_url:
                page.get(_BASE_URL, timeout=30)
                _human_pause(2.0, 4.0)
            page.get(url, timeout=20)
            _human_pause(3.0, 6.0)
            loaded_url = page.url or url
            return ToolResult(ok=True, data={"loaded_url": loaded_url})
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=str(exc))
