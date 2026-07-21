from tools.base import BaseTool, ToolResult
from tools.browser.helpers import _human_pause

_JD_SELECTORS = [
    ".job-detail-section",
    ".job-sec-text",
    ".job-sec-inner",
    ".job-sec",
    ".detail-content",
    ".job-detail-content",
    ".job-detail-box",
    ".desc-content",
    ".text-desc",
    ".job-description",
    "[class*='job-sec']",
    "[class*='job-detail']",
    "[class*='detail-content']",
    "[class*='job-desc']",
]


class ClickCardOpenPanel(BaseTool):
    name = "click_card_open_panel"
    description = "Click a job card by job_id to open the JD detail panel on the right"
    input_schema = {
        "type": "object",
        "properties": {
            "card_dom_index": {"type": "integer"},
            "job_id": {"type": "string"},
        },
        "required": ["card_dom_index", "job_id"],
    }

    def __init__(self, browser=None):
        self._browser = browser

    def execute(self, card_dom_index: int = 0, job_id: str = "") -> ToolResult:
        if self._browser is None:
            return ToolResult(ok=False, data={}, error="browser not initialized")
        page = self._browser
        try:
            # Find card by job_id fragment in href and dispatch a trusted CDP click.
            # page.ele() cannot locate SPA-rendered children; JS + CDP mouse events
            # produce isTrusted=true which Boss直聘's React SPA requires.
            job_id_fragment = job_id.replace("'", "").replace('"', "")
            rect_data = page.run_js(f"""
                var frag = '{job_id_fragment}';
                var cards = document.querySelectorAll('.job-card-wrap');
                for (var i = 0; i < cards.length; i++) {{
                    var a = cards[i].querySelector('a.job-name') || cards[i].querySelector('a[href*="/job_detail/"]');
                    if (a && a.getAttribute('href') && a.getAttribute('href').indexOf(frag) !== -1) {{
                        cards[i].scrollIntoView({{block: 'center', behavior: 'instant'}});
                        var r = cards[i].getBoundingClientRect();
                        return {{found: true, x: r.left + r.width / 2, y: r.top + r.height / 2}};
                    }}
                }}
                return {{found: false}};
            """)

            if not rect_data or not rect_data.get("found"):
                return ToolResult(ok=False, data={}, error=f"card not found for job_id={job_id!r}")

            cx = float(rect_data["x"])
            cy = float(rect_data["y"])
            page.run_cdp("Input.dispatchMouseEvent",
                         type="mouseMoved", x=cx, y=cy, button="none", modifiers=0)
            page.run_cdp("Input.dispatchMouseEvent",
                         type="mousePressed", x=cx, y=cy, button="left", clickCount=1, modifiers=0)
            page.run_cdp("Input.dispatchMouseEvent",
                         type="mouseReleased", x=cx, y=cy, button="left", clickCount=1, modifiers=0)

            _human_pause(1.5, 2.5)

            # Find panel and record which selector matched
            matched_selector = None
            panel_el = None
            for i, sel in enumerate(_JD_SELECTORS):
                try:
                    el = page.ele(sel, timeout=6 if i == 0 else 0)
                    if el:
                        panel_el = el
                        matched_selector = sel
                        break
                except Exception:
                    continue

            if not panel_el:
                return ToolResult(ok=True, data={
                    "panel_loaded": False,
                    "matched_selector": None,
                })

            return ToolResult(ok=True, data={
                "panel_loaded": True,
                "matched_selector": matched_selector,
            })
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=str(exc))
