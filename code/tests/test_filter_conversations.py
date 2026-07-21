"""Unit tests for FilterConversations (W2 incremental filter + decision trace).

Covers the decision tree and its per-conversation `decisions` / `summary`
observability output. Key behavior pinned here: the terminal-stage skip is
evaluated LAST, so a closed/offer conversation with genuine new activity
(approved reply, unread, never-seen, or a changed preview) is still processed;
terminal only suppresses conversations that have nothing new.
"""
import time

from tools.biz_logic.filter_conversations import FilterConversations


def _run(current_convs, stored_states, approved_reply_ids=None, active_window_days=0):
    return FilterConversations().execute(
        current_convs=current_convs,
        stored_states=stored_states,
        approved_reply_ids=approved_reply_ids or [],
        active_window_days=active_window_days,
    )


def _days_ago_ms(days: float) -> int:
    return int((time.time() - days * 86400) * 1000)


def _reason_of(decisions, conv_id):
    return next(d["reason"] for d in decisions if d["conv_id"] == conv_id)


def test_terminal_with_unread_is_processed():
    """Regression: a closed conversation with a new unread message must NOT be
    skipped just because it is terminal (terminal is now checked last)."""
    res = _run(
        current_convs=[{"conv_id": "c1", "has_unread": True, "last_msg_preview": "hi"}],
        stored_states={"c1": {"stage": "closed", "last_msg_preview": "old"}},
    )
    assert res.ok
    assert [c["conv_id"] for c in res.data["conversations_to_process"]] == ["c1"]
    assert _reason_of(res.data["decisions"], "c1") == "unread"


def test_terminal_with_changed_preview_is_processed():
    """A closed conversation whose list preview changed (HR re-engaged, unread
    already cleared) is processed -- terminal no longer preempts preview change."""
    res = _run(
        current_convs=[{"conv_id": "c1", "has_unread": False, "last_msg_preview": "new text"}],
        stored_states={"c1": {"stage": "offer", "last_msg_preview": "old text"}},
    )
    assert res.data["output_count"] == 1
    assert _reason_of(res.data["decisions"], "c1") == "preview_changed"


def test_terminal_with_no_change_is_skipped():
    res = _run(
        current_convs=[{"conv_id": "c1", "has_unread": False, "last_msg_preview": "same"}],
        stored_states={"c1": {"stage": "closed", "last_msg_preview": "same", "intent": "rejection"}},
    )
    assert res.data["conversations_to_process"] == []
    assert _reason_of(res.data["decisions"], "c1") == "terminal"


def test_approved_reply_processed_even_when_terminal():
    res = _run(
        current_convs=[{"conv_id": "c1", "has_unread": False, "last_msg_preview": "same"}],
        stored_states={"c1": {"stage": "closed", "last_msg_preview": "same"}},
        approved_reply_ids=["c1"],
    )
    assert res.data["output_count"] == 1
    assert _reason_of(res.data["decisions"], "c1") == "approved"


def test_unchanged_active_conversation_is_skipped_as_no_change():
    res = _run(
        current_convs=[{"conv_id": "c1", "has_unread": False, "last_msg_preview": "same"}],
        stored_states={"c1": {"stage": "active", "last_msg_preview": "same", "intent": "general"}},
    )
    assert res.data["conversations_to_process"] == []
    assert _reason_of(res.data["decisions"], "c1") == "no_change"


def test_stored_row_with_empty_intent_is_never_analyzed():
    """Recovery branch: a conversation with a stored row but no persisted intent
    (read + upserted, but AnalyzeStep never succeeded) is re-processed instead of
    being swallowed as no_change -- otherwise it stays invisible forever."""
    res = _run(
        current_convs=[{"conv_id": "c1", "has_unread": False, "last_msg_preview": "same"}],
        stored_states={"c1": {"stage": "active", "last_msg_preview": "same", "intent": ""}},
    )
    assert res.data["output_count"] == 1
    assert _reason_of(res.data["decisions"], "c1") == "never_analyzed"


def test_empty_intent_but_too_old_stays_skipped():
    """too_old is checked before never_analyzed: a stale stuck row is NOT revived
    (we don't chew on months-old threads even if their intent is empty)."""
    res = _run(
        current_convs=[{"conv_id": "c1", "has_unread": False, "last_msg_preview": "same",
                        "last_msg_ts": _days_ago_ms(60)}],
        stored_states={"c1": {"stage": "active", "last_msg_preview": "same", "intent": ""}},
        active_window_days=14,
    )
    assert res.data["conversations_to_process"] == []
    assert _reason_of(res.data["decisions"], "c1") == "too_old"


def test_never_seen_conversation_is_new():
    res = _run(
        current_convs=[{"conv_id": "c1", "has_unread": False, "last_msg_preview": "hi"}],
        stored_states={},
    )
    assert res.data["output_count"] == 1
    assert _reason_of(res.data["decisions"], "c1") == "new"


def test_old_conversation_skipped_as_too_old():
    """A never-seen conversation whose last message predates the active window and
    has no unread / approved reply is skipped as too_old -- not navigated into +
    LLM-analyzed. This is the core fix: W2 no longer chews on months-old threads."""
    res = _run(
        current_convs=[{"conv_id": "c1", "has_unread": False, "last_msg_preview": "hi",
                        "last_msg_ts": _days_ago_ms(60)}],
        stored_states={},
        active_window_days=14,
    )
    assert res.data["conversations_to_process"] == []
    assert _reason_of(res.data["decisions"], "c1") == "too_old"


def test_old_conversation_with_unread_still_processed():
    """Older than the window but with an unread badge (HR just messaged) -> processed.
    The window gate is checked AFTER unread precisely so this can't be skipped."""
    res = _run(
        current_convs=[{"conv_id": "c1", "has_unread": True, "last_msg_preview": "hi",
                        "last_msg_ts": _days_ago_ms(60)}],
        stored_states={},
        active_window_days=14,
    )
    assert _reason_of(res.data["decisions"], "c1") == "unread"


def test_old_conversation_with_approved_reply_still_processed():
    """An approved reply must be handled even on an old conversation (reply_text is
    protected for W3); the window gate must not swallow it."""
    res = _run(
        current_convs=[{"conv_id": "c1", "has_unread": False, "last_msg_preview": "hi",
                        "last_msg_ts": _days_ago_ms(60)}],
        stored_states={"c1": {"stage": "active", "last_msg_preview": "hi"}},
        approved_reply_ids=["c1"],
        active_window_days=14,
    )
    assert _reason_of(res.data["decisions"], "c1") == "approved"


def test_recent_conversation_within_window_is_new():
    """A recent (within window) never-seen conversation is still processed as new."""
    res = _run(
        current_convs=[{"conv_id": "c1", "has_unread": False, "last_msg_preview": "hi",
                        "last_msg_ts": _days_ago_ms(2)}],
        stored_states={},
        active_window_days=14,
    )
    assert _reason_of(res.data["decisions"], "c1") == "new"


def test_no_timestamp_exempt_from_window_gate():
    """conv_ts == 0 (DOM-fallback / pre-migration rows with no real timestamp) is
    exempt from the gate: unknown time falls through to the normal signals (new)."""
    res = _run(
        current_convs=[{"conv_id": "c1", "has_unread": False, "last_msg_preview": "hi"}],
        stored_states={},
        active_window_days=14,
    )
    assert _reason_of(res.data["decisions"], "c1") == "new"


def test_window_disabled_processes_old_conversation():
    """active_window_days=0 disables the gate: an old conversation is processed as
    before (backward-compatible default)."""
    res = _run(
        current_convs=[{"conv_id": "c1", "has_unread": False, "last_msg_preview": "hi",
                        "last_msg_ts": _days_ago_ms(60)}],
        stored_states={},
        active_window_days=0,
    )
    assert _reason_of(res.data["decisions"], "c1") == "new"


def test_summary_counts_by_reason():
    res = _run(
        current_convs=[
            {"conv_id": "a", "has_unread": True, "last_msg_preview": "x"},   # unread
            {"conv_id": "b", "has_unread": False, "last_msg_preview": "x"},  # new
            {"conv_id": "c", "has_unread": False, "last_msg_preview": "same"},  # no_change
            {"conv_id": "d", "has_unread": False, "last_msg_preview": "same"},  # terminal
        ],
        stored_states={
            "c": {"stage": "active", "last_msg_preview": "same", "intent": "general"},
            "d": {"stage": "closed", "last_msg_preview": "same", "intent": "rejection"},
        },
    )
    assert res.data["summary"] == {
        "unread": 1,
        "new": 1,
        "no_change": 1,
        "terminal": 1,
    }
    assert res.data["input_count"] == 4
    assert res.data["output_count"] == 2  # unread + new
