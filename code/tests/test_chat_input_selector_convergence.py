"""Guard against chat-input selector drift.

Root cause of a class of silent W3 send failures: navigate_to_conversation's
"is a conversation open?" probe listed the newer `#boss-chat-editor-input`, while
send_chat_message + search_locate_conversation still hard-coded the older
`#chat-input`. When Boss renamed the id, locate reported LOCATED (probe matched the
generic contenteditable) but send typed into a null element → "text not set" →
submit_failed. The reply looked attempted but never left.

Fix: all three consumers resolve the input through the ONE shared expression
helpers.CHAT_INPUT_QUERY_JS. These tests pin that convergence so it can't silently
re-diverge: the shared resolver must cover BOTH ids, and each consumer must use it
instead of an inline hard-coded id.
"""
import re
from pathlib import Path

from tools.browser.helpers import CHAT_INPUT_QUERY_JS, CHAT_INPUT_SELECTORS

_SRC = Path(__file__).resolve().parent.parent / "tools" / "browser"


def test_shared_resolver_covers_both_ids():
    # Both the legacy and current editor ids must be in the shared resolver, or a
    # future Boss markup flip silently breaks locate-or-send again.
    assert "#chat-input" in CHAT_INPUT_QUERY_JS
    assert "#boss-chat-editor-input" in CHAT_INPUT_QUERY_JS
    joined = " ".join(CHAT_INPUT_SELECTORS)
    assert "#chat-input" in joined and "#boss-chat-editor-input" in joined


def _reads(rel: str) -> str:
    return (_SRC / rel).read_text(encoding="utf-8")


def test_consumers_use_shared_resolver_not_inline_id():
    """send / search-locate / navigate probe all import + use the shared resolver."""
    for rel in (
        "w2/send_chat_message.py",
        "w2/navigate_to_conversation.py",
        "w3/search_locate_conversation.py",
    ):
        src = _reads(rel)
        assert "CHAT_INPUT_QUERY_JS" in src, f"{rel} must use the shared resolver"
        # No consumer may re-introduce a bare inline `querySelector('#chat-input')`
        # (that is exactly the drift this convergence removed).
        assert not re.search(r"querySelector\(\s*'#chat-input'", src), (
            f"{rel} still has an inline hard-coded #chat-input query"
        )
