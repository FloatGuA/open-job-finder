"""W3 per-reply send pipeline: Locate -> Freshness -> Send -> Verify -> mark.

Each step has an explicit completion check (not "action performed"):
- Locate    : the conversation actually OPENED (search_locate_conversation.located).
- Freshness : re-scan the OPEN thread and confirm we are still the ones being
              waited on (last non-system bubble is the HR's). If anyone spoke since
              the reply was approved — the user replied by hand, a resume card went
              out, or a prior send landed unmarked — the draft is stale; we refuse
              to send it, void it, and reset the conversation so the next W2 run
              re-decides intent (see invalidate_stale_reply). This is the guard
              against blind-sending an outdated draft to a real HR.
- Send      : the submit action ran (send_chat_message.ok) — proxy only.
- Verify    : RE-SCAN the open thread with W2's read_messages, persist it with
              write_hr_messages, and confirm our reply now exists as a 'me' bubble
              in the freshly-read messages. This shares W2's read/write path and
              leaves a DB record of the sent message (root-cause fix: the old
              DOM-prefix probe was unreliable and never wrote to hr_messages).
Only a passing Verify calls mark_reply_sent; otherwise the reply stays 'approved'
with its text intact (no false success, no draft loss).
"""
import re
import time
from dataclasses import dataclass
from typing import Optional


def _norm(s: str) -> str:
    """Whitespace-insensitive normalize (Boss reflows newlines/spaces on render)."""
    return re.sub(r"\s+", "", s or "")


def _last_nonsystem_sender(messages: list) -> Optional[str]:
    """Sender of the last non-system bubble ('me' | 'hr'), or None if there is none.

    System bubbles (Boss platform nudges, place cards) are not conversation turns,
    so they don't count as "someone replied since we drafted". We are still owed a
    reply only when the HR spoke last.
    """
    for m in reversed(messages or []):
        s = m.get("sender")
        if s in ("me", "hr"):
            return s
    return None


@dataclass
class SendReplyOutput:
    conv_id: str
    located: bool = False
    submitted: bool = False
    delivered: bool = False
    marked_sent: bool = False
    # locate_failed | locate_gave_up | stale_superseded | freshness_read_failed
    # | submit_failed | deliver_unverified | dry_run | null
    failure_reason: Optional[str] = None


class SendReplyPipeline:
    def __init__(self, registry, logger, config):
        self._reg = registry
        self._logger = logger
        self._cfg = config

    def _log(self, step, scope, status, start_ts, data=None, error=None):
        lg = getattr(self._reg, "logger", None) or self._logger
        if lg is None:
            return
        lg.log_step(
            step=step,
            scope=scope,
            status=status,
            duration_ms=int((time.time() - start_ts) * 1000),
            data=data or {},
            error=error,
        )

    def run(self, reply: dict) -> SendReplyOutput:
        conv_id = reply.get("conv_id", "")
        company = reply.get("company", "")
        hr_name = reply.get("hr_name", "")
        text = reply.get("reply_text", "") or ""
        scope = {"conv_id": conv_id, "company": company}
        out = SendReplyOutput(conv_id=conv_id)

        # ── Locate ──────────────────────────────────────────────────────────
        ts = time.time()
        self._reg.set_context("locate", scope)
        loc = self._reg.call("search_locate_conversation", conv_id=conv_id, company=company, hr_name=hr_name)
        out.located = bool(loc.ok and loc.data.get("located"))
        self._log("locate", scope, "successful" if out.located else "failed", ts,
                  data={"matched_count": loc.data.get("matched_count", 0)}, error=loc.error)
        # Track consecutive misses; locating resets the count. After 3 the conversation
        # is treated as gone from Boss (e.g. the user rejected it) and its reply is
        # auto-dismissed so W3 stops retrying an unreachable conversation forever.
        rec = self._reg.call("record_locate_attempt", conv_id=conv_id, located=out.located)
        if not out.located:
            if rec.ok and rec.data.get("given_up"):
                self._logger.log(
                    "reply_locate_gave_up",
                    scope=scope,
                    data={"fail_count": rec.data.get("count"),
                          "reason": "conversation not found 3 times; reply dismissed"},
                    visible=True,
                )
                out.failure_reason = "locate_gave_up"
            else:
                out.failure_reason = "locate_failed"
            return out

        # ── Dry run: located, but do nothing else ───────────────────────────
        # Short-circuit BEFORE the freshness gate: a dry run must never read/mutate
        # (the gate can void a draft), so it stops right after confirming we located.
        if self._cfg.dry_run:
            ts = time.time()
            self._reg.set_context("send", scope)
            self._log("send", scope, "skipped", ts, data={"dry_run": True})
            out.failure_reason = "dry_run"
            return out

        # ── Freshness (before Send) ─────────────────────────────────────────
        # The draft was approved against the conversation as it stood then. Re-scan
        # the now-open thread: if the last non-system bubble is no longer the HR's,
        # someone spoke after the message this draft answers (the user replied by
        # hand, a resume card went out, or a prior send landed unmarked). Sending the
        # approved text now would double-message or answer an already-handled turn,
        # so we void the draft + reset the conversation to unanalyzed (the next W2
        # run re-decides intent and re-drafts into the queue iff still due) instead
        # of blind-sending. A read FAILURE means we cannot verify freshness -> skip
        # this run but KEEP the draft: a transient render glitch must not destroy an
        # approved reply (it retries next run).
        ts = time.time()
        self._reg.set_context("freshness", scope)
        rd0 = self._reg.call("read_messages")
        if not rd0.ok:
            out.failure_reason = "freshness_read_failed"
            self._log("freshness", scope, "failed", ts, data={}, error=rd0.error)
            return out
        last_sender = _last_nonsystem_sender(rd0.data.get("messages", []))
        if last_sender != "hr":
            self._reg.call("invalidate_stale_reply", conv_id=conv_id)
            out.failure_reason = "stale_superseded"
            if self._logger is not None:
                self._logger.log(
                    "reply_skipped_stale",
                    scope=scope,
                    data={"last_sender": last_sender or "none",
                          "reason": "conversation advanced since approval; draft voided for re-analysis"},
                    visible=True,
                )
            self._log("freshness", scope, "skipped", ts, data={"last_sender": last_sender or "none"})
            return out
        self._log("freshness", scope, "successful", ts, data={"last_sender": "hr"})

        # ── Send ────────────────────────────────────────────────────────────
        ts = time.time()
        self._reg.set_context("send", scope)
        snd = self._reg.call("send_chat_message", text=text)
        out.submitted = bool(snd.ok)
        self._log("send", scope, "successful" if out.submitted else "failed", ts,
                  data={"submit": snd.data.get("submit"), "input_cleared": snd.data.get("input_cleared")}, error=snd.error)
        if not out.submitted:
            out.failure_reason = "submit_failed"
            return out

        # ── Verify (authoritative: re-scan thread, persist, confirm landing) ─
        # Re-read the open conversation with W2's read_messages, persist the
        # fresh scan (so the just-sent message lands in hr_messages), and confirm
        # our reply now exists as a 'me' bubble. Retry a few times: Boss renders
        # the sent bubble asynchronously after the submit returns.
        ts = time.time()
        self._reg.set_context("verify", scope)
        probe = _norm(text)[:16]
        messages: list = []
        for attempt in range(4):
            rd = self._reg.call("read_messages")
            messages = rd.data.get("messages", []) if rd.ok else []
            if probe and any(
                m.get("sender") == "me" and probe in _norm(m.get("text", "")) for m in messages
            ):
                out.delivered = True
                break
            if attempt < 3:
                time.sleep(1.2)
        # Persist whatever we last scanned (incl. our sent message); tracker dedups.
        if messages:
            self._reg.call("write_hr_messages", conv_id=conv_id, messages=messages)
        if out.delivered:
            self._reg.call("mark_reply_sent", conv_id=conv_id)
            out.marked_sent = True
            self._log("verify", scope, "successful", ts, data={"delivered": True, "scanned": len(messages)})
        else:
            # Keep 'approved', do NOT mark sent / clear text — the whole point of W3.
            out.failure_reason = "deliver_unverified"
            self._log("verify", scope, "failed", ts, data={"delivered": False, "scanned": len(messages)},
                      error="sent reply not found in re-scanned thread")
        return out
