import re

from tools.base import BaseTool, ToolResult
from tools.browser.helpers import CHAT_INPUT_QUERY_JS, _human_pause

# Chat-list search box (verified live): placeholder「搜索30天内的联系人」.
_SEARCH_INPUT = "css:input.boss-search-input"
# Editor that appears once a conversation is actually open — the completion signal.
# Uses the SHARED input resolver so this "opened" probe can't drift from send/navigate
# (a stale #chat-input here reported "editor did not open" for a conversation that DID).
_OPEN_PROBE_JS = "return !!" + CHAT_INPUT_QUERY_JS + ";"
# Search RESULTS render in a separate dropdown (.boss-search-result > .search-ul > li.search-list),
# NOT by filtering the main .friend-content-warp list. Each result item:
#   .boss-name      -> HR name   (chars may be wrapped in <u class="h"> highlights → textContent ok)
#   .company-name   -> company
# Match by company + hr (contains, to tolerate highlight markup) and click the item.
_MATCH_CLICK_JS = (
    "var company = arguments[0], hr = arguments[1];"
    "var items = document.querySelectorAll('.search-ul li, .boss-search-result li');"
    "var matched = 0, clicked = false;"
    "for (var i = 0; i < items.length; i++) {"
    "  var bn = items[i].querySelector('.boss-name');"
    "  var cn = items[i].querySelector('.company-name');"
    "  var h = bn ? bn.textContent.trim() : '';"
    "  var c = cn ? cn.textContent.trim() : '';"
    "  if (h.indexOf(hr) !== -1 && c.indexOf(company) !== -1) {"
    "    matched++;"
    "    if (!clicked) { items[i].scrollIntoView({block:'center'}); items[i].click(); clicked = true; }"
    "  }"
    "}"
    "return matched;"
)


class SearchLocateConversation(BaseTool):
    name = "search_locate_conversation"
    description = "Locate and open an HR conversation via the chat-list search box (robust vs scroll-traversal)."
    input_schema = {
        "type": "object",
        "properties": {
            "conv_id": {"type": "string"},
            "company": {"type": "string"},
            "hr_name": {"type": "string"},
        },
        "required": ["conv_id", "company", "hr_name"],
    }

    def __init__(self, browser=None):
        self._browser = browser

    def _type_search(self, term: str) -> bool:
        """Type into the search box with REAL keystrokes (ele.input) — a JS value
        setter does NOT trigger Boss's search. Returns False if the input is gone."""
        ele = self._browser.ele(_SEARCH_INPUT, timeout=3)
        if not ele:
            return False
        try:
            ele.clear()
        except Exception:
            pass
        _human_pause(0.3, 0.5)
        ele.input(term)
        return True

    def _try_term(self, term: str, company: str, hr_name: str) -> int:
        """Type `term`, wait for the results dropdown, match+click. Returns matched count."""
        if not self._type_search(term):
            return 0
        page = self._browser
        for _ in range(8):
            _human_pause(0.4, 0.7)  # search is async (debounced + server round-trip)
            matched = page.run_js(_MATCH_CLICK_JS, company, hr_name) or 0
            if matched:
                return int(matched)
        return 0

    def execute(self, conv_id: str, company: str, hr_name: str) -> ToolResult:
        if self._browser is None:
            return ToolResult(ok=False, data={"located": False, "boss_conv_id_confirmed": "", "matched_count": 0}, error="browser not initialized")
        page = self._browser
        try:
            matched = 0
            # Search by HR NAME first: the box is a contact search, and the HR name
            # is exact, whereas a stored company name may not match Boss's searchable
            # form (suffix/format differences) and return nothing. Then match within
            # the results by COMPANY (+hr) to pick the right conversation. Company is
            # kept as a fallback search term.
            for term in (hr_name, company):
                term = (term or "").strip()
                if not term:
                    continue
                matched = self._try_term(term, company, hr_name)
                if matched:
                    break

            if not matched:
                return ToolResult(ok=True, data={"located": False, "boss_conv_id_confirmed": "", "matched_count": 0})

            # Completion check: the conversation actually OPENED (editor present).
            opened = False
            for _ in range(6):
                _human_pause(0.5, 0.8)
                if page.run_js(_OPEN_PROBE_JS):
                    opened = True
                    break
            m = re.search(r"[?&]conversationId=([^&]+)", page.url or "")
            return ToolResult(
                ok=True,
                data={
                    "located": opened,
                    "boss_conv_id_confirmed": m.group(1) if m else "",
                    "matched_count": matched,
                },
                error=None if opened else "matched a search result but conversation editor did not open",
            )
        except Exception as exc:
            return ToolResult(ok=False, data={"located": False, "boss_conv_id_confirmed": "", "matched_count": 0}, error=str(exc))
