"""W3Pipeline — send user-approved replies (approved/revision) with delivery verification.

LoadApprovedStep (get approved replies + navigate to chat list) → SendReplyPipeline
per reply (locate → send → verify → mark). Decoupled from W2: W2 drafts + sends
resume; W3 only sends approved replies and only marks them sent once delivery is
verified.
"""
import time
from dataclasses import dataclass

from pipeline.base import StepStatus
from pipeline.w3.send_pipeline import SendReplyPipeline


@dataclass
class W3Config:
    dry_run: bool = False
    max_replies: int = 50


class W3Pipeline:
    def __init__(self, registry, logger):
        self._reg = registry
        self._logger = logger

    def run(self, config: W3Config) -> dict:
        # ── LoadApprovedStep ────────────────────────────────────────────────
        ts = time.time()
        self._reg.set_context("scan", {})
        res = self._reg.call("get_approved_replies")
        replies = [
            c for c in (res.data.get("conversations", []) if res.ok else [])
            if (c.get("reply_text") or "").strip()
        ]
        if config.max_replies and config.max_replies > 0:
            replies = replies[: config.max_replies]
        self._logger.log_step(
            step="scan", scope={}, status="successful",
            duration_ms=int((time.time() - ts) * 1000),
            data={"approved": len(replies)}, error=res.error,
        )

        if not replies:
            summary = {"approved": 0, "located": 0, "replies_sent": 0, "failed": 0}
            self._logger.close("done", summary=summary)
            return summary

        nav = self._reg.call("navigate_to_chat_list")
        if not nav.ok:
            self._logger.close("failed")
            return {"approved": len(replies), "located": 0, "replies_sent": 0, "failed": len(replies), "error": "chat_list_failed"}

        located = sent = failed = 0
        stopped = False
        for reply in replies:
            if self._logger.should_stop():  # honor 中止 between replies
                stopped = True
                self._logger.log("run_stopped", scope={}, data={"reason": "user_stop", "sent": sent})
                break
            try:
                out = SendReplyPipeline(self._reg, self._logger, config).run(reply)
            except Exception as exc:
                failed += 1
                self._logger.log(
                    "send_reply_error",
                    scope={"conv_id": reply.get("conv_id", ""), "company": reply.get("company", "")},
                    data={"error": str(exc)},
                )
                continue
            located += int(out.located)
            sent += int(out.delivered)
            if not out.delivered:
                failed += 1

        summary = {
            "approved": len(replies),
            "located": located,
            "replies_sent": sent,
            "failed": failed,
            "stopped": stopped,
        }
        self._logger.close("done", summary=summary)
        return summary
