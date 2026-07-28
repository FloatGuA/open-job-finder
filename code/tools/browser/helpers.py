import random
import time


def _ele_any(page, selectors, timeout=0):
    """Return the first element found by trying each selector in order.

    First selector uses the given timeout; subsequent selectors use timeout=0
    to match the wait-for-primary-then-fallback pattern from browser_agent.py.
    """
    for i, selector in enumerate(selectors):
        try:
            el = page.ele(selector, timeout=timeout if i == 0 else 0)
            if el:
                return el
        except Exception:
            continue
    return None


def _human_pause(min_sec: float = 2.0, max_sec: float = 5.0) -> None:
    time.sleep(random.uniform(min_sec, max_sec))


# ── Boss chat message input — ONE source of selectors ─────────────────────────
# The message input's DOM id DRIFTED: older markup used `#chat-input`, newer uses
# `#boss-chat-editor-input`. When locate/probe and the actual send disagree on the
# id, a nasty split appears: navigate's "is a conversation open?" probe matches the
# generic contenteditable and reports LOCATED, but send_chat_message's hard-coded
# `#chat-input` resolves to null → it types nothing → "text not set" → submit_failed.
# The reply looks sent-attempted but never leaves. Keep every consumer (navigate
# probe, search-locate probe, send) on the SAME set so they can never diverge again.
CHAT_INPUT_SELECTORS = (
    "css:#chat-input[contenteditable='true']",
    "css:#boss-chat-editor-input[contenteditable='true']",
    "css:.chat-input[contenteditable='true']",
    "css:.chat-editor [contenteditable='true']",
    "css:div[contenteditable='true']",
)

# JS expression resolving the input element with ORDERED fallbacks. Uses `||` (not a
# single comma-list querySelector, which returns document order, not selector order)
# so the specific ids win over the generic contenteditable. Yields the element or
# null. Wrap with `!!(...)` for a presence probe, or `var el = (...);` to act on it.
CHAT_INPUT_QUERY_JS = (
    "(document.querySelector('#chat-input')"
    " || document.querySelector('#boss-chat-editor-input')"
    " || document.querySelector(\".chat-input[contenteditable='true']\")"
    " || document.querySelector('.chat-editor [contenteditable=\"true\"]'))"
)


# Boss inserts an item-system bubble whose text contains the 4-char keyword below
# ONLY after a resume is actually delivered. Verified 2026-06-11 across 15 sends on
# both send paths: a mainland "...<kw>... delivered to Boss" bubble, and a cross-
# border "<kw> request sent" + "...preview <kw>" bubble. This system bubble is the
# single source of truth that a resume went out -- shared by BOTH send paths (toolbar
# + card-accept) and by detect_resume_request's already_sent check. An HR's own
# request says "resume" but never this 4-char keyword, so it never
# false-positives on a request.
# Keyword as a JS \uXXXX escape (no CJK bytes in source, per read_messages.py):
#   U+9644 U+4EF6 U+7B80 U+5386  ==  "attachment-resume"
_RESUME_DELIVERED_KW_JS = "\\u9644\\u4ef6\\u7b80\\u5386"


def count_resume_delivered_markers(page) -> int:
    """Count delivered-resume system bubbles in the currently open conversation."""
    n = page.run_js(
        "var els=document.querySelectorAll('.message-item.item-system');var n=0;"
        "for(var i=0;i<els.length;i++){"
        "if((els[i].innerText||'').indexOf('" + _RESUME_DELIVERED_KW_JS + "')!==-1)n++;"
        "}return n;"
    )
    return n or 0


def wait_resume_delivered(page, before: int, attempts: int = 6, pause: float = 1.0) -> bool:
    """Poll until a NEW delivered-resume system bubble appears (count > before).

    Boss renders the confirmation bubble asynchronously a beat after the click, so a
    single immediate check is unreliable. Returns True only once a new marker shows up.
    """
    for _ in range(attempts):
        time.sleep(pause)
        if count_resume_delivered_markers(page) > before:
            return True
    return False
