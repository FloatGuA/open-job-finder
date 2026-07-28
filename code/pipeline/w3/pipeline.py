"""W3Pipeline — deliver everything the user staged for outbound send.

Two queues, both human-approved, delivered on the same W3 run:
  1. approved/revision text replies -> SendReplyPipeline (locate → freshness → send
     → verify → mark). Marked sent only once delivery is verified.
  2. manually queued resumes (resume_status='queued', the W2 detection-miss
     fallback) -> SendResumePipeline (locate → idempotency → send → clear+advance).

Decoupled from W2: W2 drafts replies + auto-sends detected resumes; W3 delivers what
the user explicitly staged (approved reply / queued resume), so a real HR is only
messaged for something a human signed off on.
"""
import time
from dataclasses import dataclass

from pipeline.base import StepStatus
from pipeline.w3.send_pipeline import SendReplyPipeline
from pipeline.w3.send_resume_pipeline import SendResumePipeline


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
        # A failed load is NOT "zero approved replies" — masking it as done would hide a
        # DB/tool fault and silently skip real approved replies. Fail the run instead.
        if not res.ok:
            self._logger.log_step(
                step="scan", scope={}, status="failed",
                duration_ms=int((time.time() - ts) * 1000), data={}, error=res.error,
            )
            self._logger.close("failed")
            return {"approved": 0, "located": 0, "replies_sent": 0, "failed": 0,
                    "error": "load_approved_failed"}
        replies = [
            c for c in res.data.get("conversations", [])
            if (c.get("reply_text") or "").strip()
        ]
        if config.max_replies and config.max_replies > 0:
            replies = replies[: config.max_replies]

        # Manually staged resumes (W2 detection-miss fallback). A failed load here is
        # NOT "zero queued" -- same reasoning as replies: mask it and real staged
        # resumes silently never send.
        rq = self._reg.call("get_queued_resumes")
        if not rq.ok:
            self._logger.log_step(
                step="scan", scope={}, status="failed",
                duration_ms=int((time.time() - ts) * 1000), data={}, error=rq.error,
            )
            self._logger.close("failed")
            return {"approved": len(replies), "located": 0, "replies_sent": 0, "failed": 0,
                    "resumes_queued": 0, "resumes_sent": 0, "error": "load_queued_resumes_failed"}
        resumes = list(rq.data.get("conversations", []))

        self._logger.log_step(
            step="scan", scope={}, status="successful",
            duration_ms=int((time.time() - ts) * 1000),
            data={"approved": len(replies), "resumes_queued": len(resumes)}, error=None,
        )

        if not replies and not resumes:
            summary = {"approved": 0, "located": 0, "replies_sent": 0, "failed": 0,
                       "resumes_queued": 0, "resumes_sent": 0}
            self._logger.close("done", summary=summary)
            return summary

        nav = self._reg.call("navigate_to_chat_list")
        if not nav.ok:
            self._logger.close("failed")
            return {"approved": len(replies), "located": 0, "replies_sent": 0,
                    "failed": len(replies), "resumes_queued": len(resumes), "resumes_sent": 0,
                    "error": "chat_list_failed"}

        located = sent = failed = 0
        resumes_sent = 0
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

        # Queued resumes (same run, after replies). An already-sent skip counts as
        # success (the resume the user wanted IS there); a send failure keeps 'queued'.
        for rconv in resumes:
            if self._logger.should_stop():
                stopped = True
                self._logger.log("run_stopped", scope={}, data={"reason": "user_stop", "resumes_sent": resumes_sent})
                break
            try:
                rout = SendResumePipeline(self._reg, self._logger, config).run(rconv)
            except Exception as exc:
                failed += 1
                self._logger.log(
                    "send_resume_error",
                    scope={"conv_id": rconv.get("conv_id", ""), "company": rconv.get("company", "")},
                    data={"error": str(exc)},
                )
                continue
            located += int(rout.located)
            if rout.delivered or rout.skipped_already_sent:
                resumes_sent += 1
            elif not config.dry_run:
                failed += 1

        summary = {
            "approved": len(replies),
            "located": located,
            "replies_sent": sent,
            "failed": failed,
            "resumes_queued": len(resumes),
            "resumes_sent": resumes_sent,
            "stopped": stopped,
        }
        self._logger.close("done", summary=summary)
        return summary
