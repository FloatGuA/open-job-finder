import time
from typing import Dict, List

from tools.base import BaseTool, ToolResult

_TERMINAL_STAGES = frozenset({"closed", "offer"})


class FilterConversations(BaseTool):
    name = "filter_conversations"
    description = "Filter a list of HR conversations to only those that need processing."
    input_schema = {
        "type": "object",
        "properties": {
            "current_convs": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "conv_id": {"type": "string"},
                        "has_unread": {"type": "boolean"},
                        "last_msg_preview": {"type": "string"},
                        "last_msg_ts": {"type": "integer"},
                    },
                    "required": ["conv_id"],
                },
            },
            "stored_states": {
                "type": "object",
                "additionalProperties": {
                    "type": "object",
                    "properties": {
                        "last_msg_preview": {"type": "string"},
                        "stage": {"type": "string"},
                        "last_msg_ts": {"type": "integer"},
                        "intent": {"type": "string"},
                        "last_analyzed_ts": {"type": "integer"},
                    },
                },
            },
            "approved_reply_ids": {
                "type": "array",
                "items": {"type": "string"},
            },
            "active_window_days": {"type": "integer"},
        },
        "required": ["current_convs", "stored_states", "approved_reply_ids"],
    }

    def execute(
        self,
        *,
        current_convs: List[dict],
        stored_states: Dict[str, dict],
        approved_reply_ids: List[str],
        active_window_days: int = 0,
    ) -> ToolResult:
        approved_set = set(approved_reply_ids)
        # Activity window: a conversation whose last message is older than this
        # cutoff is stale and skipped (see the too_old branch). 0 disables the gate.
        cutoff_ms = (
            int((time.time() - active_window_days * 86400) * 1000)
            if active_window_days and active_window_days > 0
            else 0
        )
        result = []
        decisions: List[dict] = []
        summary: Dict[str, int] = {}

        for conv in current_convs:
            conv_id = conv.get("conv_id", "")
            state = stored_states.get(conv_id, {})
            stage = state.get("stage", "")
            has_unread = bool(conv.get("has_unread", False))
            conv_ts = int(conv.get("last_msg_ts", 0) or 0)
            # Dirty check compares against last_analyzed_ts (the last message we
            # SUCCESSFULLY analyzed up to), NOT last_msg_ts (last message we saw) --
            # this is what decouples read from analyze: a failed analyze never advances
            # last_analyzed_ts, so the conversation is retried next run.
            analyzed_ts = int(state.get("last_analyzed_ts", 0) or 0)

            # The "process" signals are evaluated first; the terminal-stage skip is
            # checked LAST, so a closed/offer conversation with genuine new activity
            # (an approved reply to send, an unread badge, never-seen-before, or a
            # changed preview) is still processed. Terminal therefore only suppresses
            # conversations that have nothing new -- it no longer preempts real
            # HR re-engagement. Each branch records a reason for observability.
            if conv_id in approved_set:
                action, reason = "process", "approved"
            elif has_unread:
                action, reason = "process", "unread"
            elif cutoff_ms and conv_ts and conv_ts < cutoff_ms:
                # Activity-window gate: last message older than the window and no
                # unread badge / approved reply -> stale, skip instead of navigating
                # in + LLM-analyzing a months-old thread. Placed AFTER unread/approved
                # (those must always be handled) but BEFORE new/unanalyzed/preview so
                # an old conversation can't slip through on any of those. conv_ts == 0
                # (DOM-fallback / pre-migration rows with no real timestamp) is exempt:
                # unknown time falls through to the normal signals rather than being
                # wrongly judged old.
                #
                # DELIBERATE: this OUTRANKS `unanalyzed`, so a stale row whose analyze
                # once failed is NOT revived. That does mean #53's "a failed analyze is
                # retried next run" only holds inside the activity window -- a real
                # trade-off, reviewed and kept. Analysing a thread whose last message is
                # two months old buys nothing (FinalizeStep soft-closes it anyway) and
                # costs an LLM call per corpse; on real data the window is what turned
                # 909 conversations into the ~12 live ones worth processing (#51).
                # An HR who re-engages brings an unread badge or a newer timestamp,
                # both of which are checked before this. Do not "fix" this ordering
                # without also answering what the analysis of a dead thread is for.
                action, reason = "skip", "too_old"
            elif conv_id not in stored_states:
                action, reason = "process", "new"
            elif conv_ts and conv_ts > analyzed_ts:
                # Primary dirty signal (read/analyze decoupled): the chat-list real
                # millisecond timestamp (getGeekFriendList.lastTS) is newer than the
                # last message we SUCCESSFULLY analyzed (last_analyzed_ts). This catches
                # BOTH genuine new activity AND a prior read-ok/analyze-failed round
                # (last_analyzed_ts stayed behind), and never-analyzed rows
                # (last_analyzed_ts=0). It replaces the old newer_ts (which compared
                # against last_msg_ts and so was masked once upsert advanced that).
                action, reason = "process", "unanalyzed"
            elif conv.get("last_msg_preview", "") != state.get("last_msg_preview", ""):
                action, reason = "process", "preview_changed"
            elif conv_id in stored_states and not (state.get("intent") or "").strip():
                # conv_ts==0 fallback (DOM-fallback / pre-migration rows with no real
                # timestamp): a stored row whose intent was never persisted -- read
                # succeeded but analyze failed. With a real timestamp the unanalyzed
                # branch above already covers this; this catches the no-timestamp case
                # so it is still re-analyzed instead of masked as no_change. Self-
                # limiting: AnalyzeStep persists intent='unknown' even for no-HR threads.
                action, reason = "process", "never_analyzed"
            elif stage in _TERMINAL_STAGES:
                action, reason = "skip", "terminal"
            else:
                action, reason = "skip", "no_change"

            decisions.append({
                "conv_id": conv_id,
                "action": action,
                "reason": reason,
                "stage": stage,
                "has_unread": has_unread,
            })
            summary[reason] = summary.get(reason, 0) + 1
            if action == "process":
                result.append(conv)

        return ToolResult(
            ok=True,
            data={
                "input_count": len(current_convs),
                "output_count": len(result),
                "conversations_to_process": result,
                # Per-conversation decisions (scan_step logs these to the file trace);
                # summary = counts by reason (scan_step pushes this to the SSE stream).
                "decisions": decisions,
                "summary": summary,
            },
        )
