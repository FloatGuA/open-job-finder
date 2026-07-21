from urllib.parse import urlparse

from tools.base import BaseTool, ToolResult
from tools.browser.helpers import _human_pause


def _path_matches(current_url: str, expected_url: str) -> bool:
    exp = urlparse(expected_url)
    cur = urlparse(current_url)
    return cur.scheme == exp.scheme and cur.netloc == exp.netloc and cur.path == exp.path


class VerifyCurrentUrl(BaseTool):
    name = "verify_current_url"
    description = (
        "Verify the browser is on the expected URL (scheme+host+path). "
        "If drifted, attempt one re-navigation and return whether recovery succeeded."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "expected_url": {"type": "string"},
        },
        "required": ["expected_url"],
    }

    def __init__(self, browser=None):
        self._browser = browser

    def execute(self, expected_url: str) -> ToolResult:
        if self._browser is None:
            return ToolResult(ok=False, data={}, error="browser not initialized")
        try:
            current_url = self._browser.url or ""

            if not current_url:
                return ToolResult(
                    ok=False,
                    data={"current_url": "", "expected_url": expected_url},
                    error="page_url_unavailable",
                )

            if _path_matches(current_url, expected_url):
                return ToolResult(ok=True, data={
                    "current_url": current_url,
                    "expected_url": expected_url,
                    "drift_detected": False,
                    "recovered": False,
                })

            # Page drift — attempt recovery by re-navigating
            self._browser.get(expected_url, timeout=20)
            _human_pause(3.0, 5.0)

            recovered_url = self._browser.url or ""
            recovered = bool(recovered_url) and _path_matches(recovered_url, expected_url)

            return ToolResult(
                ok=recovered,
                data={
                    "current_url": recovered_url,
                    "expected_url": expected_url,
                    "drift_detected": True,
                    "recovered": recovered,
                },
                error=None if recovered else f"recovery_failed: ended up at {urlparse(recovered_url).path!r}",
            )
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=str(exc))
