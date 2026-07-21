import re

from tools.base import BaseTool, ToolResult
from tools.browser.helpers import _human_pause

_CONTAINER_JS = "document.querySelector('.user-list-content') || document.querySelector('.user-list')"

# Generous safety net; the loop normally exits early on a match or once the list
# stops growing (true end). The chat list is virtual-scrolled + lazy-loaded, so a
# deep conversation can need many windows to reach.
_MAX_SCROLL_STEPS = 60


class NavigateToConversation(BaseTool):
    name = "navigate_to_conversation"
    description = "Navigate to a specific HR conversation in Boss Zhipin chat"
    input_schema = {
        "type": "object",
        "properties": {
            "conv_id": {"type": "string"},
            "company": {"type": "string"},
            "hr_name": {"type": "string"},
            "boss_conv_id": {"type": "string"},
            "job_id": {"type": "string"},
        },
        "required": ["conv_id", "company", "hr_name"],
    }

    def __init__(self, browser=None):
        self._browser = browser

    def execute(self, conv_id: str, company: str, hr_name: str, boss_conv_id: str = "", job_id: str = "") -> ToolResult:
        if self._browser is None:
            return ToolResult(
                ok=False,
                data={"method": "", "boss_conv_id_confirmed": ""},
                error="browser not initialized",
            )
        page = self._browser

        # Treatment D — direct-open via URL: O(1), no DOM scroll-search. Both ids are
        # STABLE and captured by getGeekFriendList: jobId=encryptJobId (== our job_id),
        # id=encryptBossId (== boss_conv_id from the API path — NOT the useless DOM `d-c`
        # value '62001'). Verified live: chat?id=..&jobId=.. selects the exact
        # conversation; the URL then reverts to /chat, but the chat EDITOR INPUT appears
        # only when a conversation is open (bare /chat with nothing selected has none),
        # so its presence is a reliable "opened" signal that also holds for empty stubs.
        # Missing ids / open didn't take -> fall through to the DOM scroll-search below.
        jid = (job_id or "").strip()
        boss = (boss_conv_id or "").strip()
        if jid and boss and boss != "62001":
            try:
                page.get(f"https://www.zhipin.com/web/geek/chat?id={boss}&jobId={jid}")
                _human_pause(2.0, 3.0)  # let the SPA select + load the conversation
                if page.run_js(
                    "return !!document.querySelector("
                    "'#boss-chat-editor-input, .chat-input, [contenteditable]');"
                ):
                    return ToolResult(ok=True, data={"method": "direct_url", "boss_conv_id_confirmed": boss})
            except Exception:
                pass  # fall through to DOM scroll-search

        # `boss_conv_id` (sourced from the .friend-content `d-c` attribute) is NOT a
        # per-conversation id. Verified 2026-06-01 against a live account: d-c is the
        # SAME value ('62001') on every conversation card -- it is the user's own/list
        # id, not a conversation id -- so a `?conversationId=<d-c>` URL would send every
        # conversation to the same wrong place. The param is kept for caller
        # compatibility but intentionally ignored; the only reliable navigation is to
        # find the card by hr_name + company in the list and click it.
        #
        # Match BOTH hr_name (.name-text) and company (name-box span[1]): company alone
        # picks the first card of that company, which is the wrong HR when the user has
        # several conversations at one company (conv identity is hr_name|company).
        # Built with concatenation, NOT an f-string, so the JS object literal keeps
        # single braces -- an earlier f-string version emitted `scrollIntoView({{...}})`
        # (literal double braces), invalid JS that made this fallback throw every time.
        company_esc = (company or "").replace("\\", "\\\\").replace("'", "\\'")
        hr_esc = (hr_name or "").replace("\\", "\\\\").replace("'", "\\'")
        match_js = (
            "var ws=document.querySelectorAll('.friend-content-warp');"
            "for(var i=0;i<ws.length;i++){"
            "  var nb=ws[i].querySelector('.name-box');"
            "  var spans=nb?nb.querySelectorAll('span'):[];"
            "  var company=spans.length>1?spans[1].textContent.trim():'';"
            "  var nameEl=ws[i].querySelector('.name-text');"
            "  var hr=nameEl?nameEl.textContent.trim():'';"
            "  if(company==='" + company_esc + "' && hr==='" + hr_esc + "'){"
            "    ws[i].scrollIntoView({block:'center',behavior:'instant'});"
            # The clickable element that actually opens the conversation is the INNER
            # .friend-content (verified 2026-06-02 live): clicking the outer
            # .friend-content-warp does nothing. Fall back to the warp defensively.
            "    var fc=ws[i].querySelector('.friend-content')||ws[i];"
            "    fc.click();"
            "    return i;"
            "  }"
            "}"
            "return -1;"
        )
        # Scroll the list down one window. When a plain increment stops making progress
        # (bottom of the currently-loaded batch), jump to scrollHeight -- THAT is what
        # triggers Boss's lazy-load of the next batch. The earlier `scrollTop+=600`
        # never jumped, so it got stuck at the first loaded window and every deeper
        # conversation returned "not found". Returns {top,h,advanced}: the caller treats
        # "still scrolling down (advanced) OR list grew (lazy-load)" as progress, and
        # only stops once BOTH stall -- the true bottom. (Stopping on `scrollHeight`
        # being flat alone is wrong: a list already fully loaded by scan never grows, so
        # that mis-detected "end" after ~2 scrolls and capped the search even shorter.)
        scroll_js = (
            "var c=" + _CONTAINER_JS + ";"
            "if(!c){window.scrollTo(0,document.body.scrollHeight);return null;}"
            "var before=c.scrollTop;"
            "c.scrollTop=before+Math.max(c.clientHeight-120,500);"
            "var advanced=c.scrollTop>before+5;"
            "if(!advanced){c.scrollTop=c.scrollHeight;}"
            "return {top:c.scrollTop, h:c.scrollHeight, advanced:advanced?1:0};"
        )
        reset_js = "var c=" + _CONTAINER_JS + "; if(c){c.scrollTop=0;} else {window.scrollTo(0,0);}"

        def _hit() -> ToolResult:
            _human_pause(1.5, 2.5)
            m = re.search(r"[?&]conversationId=([^&]+)", page.url or "")
            return ToolResult(ok=True, data={
                "method": "js_click",
                "boss_conv_id_confirmed": m.group(1) if m else "",
            })

        def _matched() -> bool:
            r = page.run_js(match_js)
            return r is not None and r >= 0

        def _search_down() -> bool:
            # Check the current window first (W2 processes conversations in list order,
            # so the next target is usually just below the previous one -> cheap match),
            # then scroll-load downward until found or the true bottom is reached.
            if _matched():
                return True
            prev_h, stuck = -1, 0
            for _ in range(_MAX_SCROLL_STEPS):
                info = page.run_js(scroll_js)
                # ~0.45s (was ~1.0s): enough for lazy-load + virtual-list re-render,
                # but halves search time. A not-found conversation exhausts 2 passes ×
                # 60 steps, so this pause dominates the ~100s failure cost (A).
                _human_pause(0.35, 0.55)  # let lazy-load + virtual list re-render
                if _matched():
                    return True
                if not isinstance(info, dict):
                    # No measurable container (e.g. unit-test mock): bounded fallback.
                    stuck += 1
                    if stuck >= 2:
                        break
                    continue
                h = info.get("h", 0)
                # Progress = scrolled further down OR the list grew (lazy-loaded more).
                # Only when BOTH stall are we genuinely at the bottom.
                if info.get("advanced") or h != prev_h:
                    stuck = 0
                else:
                    stuck += 1
                    if stuck >= 2:
                        break
                prev_h = h
            return False

        try:
            # Phase 1: scroll DOWN from current position (fast for ordered processing).
            if _search_down():
                return _hit()
            # Phase 2 (fallback): target was above current, or the list reordered while
            # processing -> reset to top and do a full downward pass.
            page.run_js(reset_js)
            _human_pause(0.8, 1.2)
            if _search_down():
                return _hit()
            return ToolResult(
                ok=False,
                data={"method": "js_click", "boss_conv_id_confirmed": ""},
                error=f"conversation not found for company={company!r}",
            )
        except Exception as exc:
            return ToolResult(ok=False, data={"method": "", "boss_conv_id_confirmed": ""}, error=str(exc))
