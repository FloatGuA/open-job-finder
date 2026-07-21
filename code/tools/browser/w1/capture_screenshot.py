from datetime import datetime, timezone
from pathlib import Path

from tools.base import BaseTool, ToolResult

# Screenshots land in code/data/apply_failures/. parents: w1 → browser → tools → code.
_SHOT_DIR = Path(__file__).resolve().parents[3] / "data" / "apply_failures"


def _safe(label: str) -> str:
    keep = [c if c.isalnum() or c in "-_" else "_" for c in (label or "shot")]
    return "".join(keep)[:60] or "shot"


class CaptureScreenshot(BaseTool):
    name = "capture_screenshot"
    description = "Save a PNG of the current browser view (for diagnosing apply failures)."
    input_schema = {
        "type": "object",
        "properties": {"label": {"type": "string"}},
        "required": [],
    }

    def __init__(self, browser=None):
        self._browser = browser

    def execute(self, *, label: str = "shot") -> ToolResult:
        if self._browser is None:
            return ToolResult(ok=False, data={}, error="browser not initialized")
        _SHOT_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        name = f"{_safe(label)}_{ts}.png"
        # DrissionPage saves to path/name and returns the absolute path. Guard the whole
        # thing — a screenshot is diagnostic, never worth failing the pipeline over.
        try:
            self._browser.get_screenshot(path=str(_SHOT_DIR), name=name)
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=f"screenshot failed: {exc}")
        # Return just the filename; the dashboard serves it via /api/apply-failure/{name}.
        return ToolResult(ok=True, data={"screenshot": name})
