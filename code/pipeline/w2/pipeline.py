import time
from dataclasses import dataclass

from pipeline.base import StepStatus
from pipeline.w2.conversation_pipeline import ConversationPipeline
from pipeline.w2.finalize_step import FinalizeStep
from pipeline.w2.scan_step import ScanStep


@dataclass
class W2Config:
    dry_run: bool
    max_conversations: int = 200
    # \u5f00\uff1aHR \u8981\u7b80\u5386\u65f6\u4f18\u5148\u53d1\u300c\u6309\u5c97\u4f4d\u5339\u914d\u5230\u7684\u90a3\u4efd\u7b80\u5386\u7684\u5df2\u5bfc\u51fa PDF\u300d\uff1b
    # \u6ca1\u5bfc\u51fa\u8fc7 / \u4e0a\u4f20\u5931\u8d25 \u2192 \u81ea\u52a8\u56de\u9000 Boss \u7ad9\u5185\u7b80\u5386\uff08\u4e0d\u4f1a\u6f0f\u53d1\uff09\u3002
    auto_send_adapted_resume: bool = False
    no_response_days: int = 14
    stale_conv_days: int = 30
    # Wall-clock budget for the whole conversation loop. A run that exceeds it stops
    # gracefully (runs FinalizeStep, records stopped) so a slow batch (e.g. many
    # unreachable conversations each ~100s to fail navigation) can't run for hours.
    # 0 disables the budget.
    max_run_minutes: int = 25


class W2Pipeline:
    def __init__(self, registry, profile, logger):
        self._reg = registry
        self._profile = profile
        self._logger = logger

    def run(self, config: W2Config) -> dict:
        # no_response_days doubles as the scan activity window: a conversation with
        # no new message for longer than it is stale (and FinalizeStep soft-closes it
        # anyway), so filter_conversations skips it instead of navigating in + running
        # the LLM on a months-old thread. Unread / approved-reply convs are exempt.
        scan_out = ScanStep(self._reg).run(active_window_days=config.no_response_days)
        if scan_out.status == StepStatus.FAILED:
            self._logger.close("failed")
            return {"convs_processed": 0, "replies_sent": 0, "resumes_sent": 0, "stage_changes": 0, "error": "scan_failed"}

        conversations_to_process = scan_out.conversations_to_process
        if config.max_conversations and config.max_conversations > 0:
            conversations_to_process = conversations_to_process[: config.max_conversations]
        approved_replies = scan_out.approved_replies

        convs_processed = 0
        replies_sent = 0
        resumes_sent = 0
        stage_changes = 0
        llm_degraded = 0
        conv_errors = 0

        total = len(conversations_to_process)
        stopped = False
        loop_start = time.time()
        budget_s = config.max_run_minutes * 60 if config.max_run_minutes else 0
        for conv in conversations_to_process:
            # Time budget: bound the whole loop so a slow batch can't run for hours.
            # Break gracefully (FinalizeStep still runs below).
            if budget_s and (time.time() - loop_start) > budget_s:
                stopped = True
                self._logger.log(
                    "run_time_budget_exceeded",
                    scope={},
                    data={"minutes": config.max_run_minutes, "processed": convs_processed, "total": total},
                )
                break
            # Honor the 中止 button: break BETWEEN conversations so we exit promptly
            # yet still run FinalizeStep below (graceful, unlike a hard kill).
            if self._logger.should_stop():
                stopped = True
                self._logger.log(
                    "run_stopped",
                    scope={},
                    data={"reason": "user_stop", "processed": convs_processed, "total": total},
                )
                break
            approved_reply = approved_replies.get(conv.conv_id)
            try:
                out = ConversationPipeline(
                    self._reg, self._profile, self._logger, config
                ).run(conv, approved_reply)
            except Exception as exc:
                conv_errors += 1
                self._logger.log(
                    "conv_pipeline_error",
                    scope={"conv_id": conv.conv_id, "company": conv.company},
                    data={"error": str(exc)},
                )
                continue
            convs_processed += 1
            replies_sent += int(out.reply_sent)
            resumes_sent += int(out.resume_sent)
            stage_changes += int(out.stage_changed)
            llm_degraded += int(out.llm_degraded)

        finalize_out = FinalizeStep(self._reg, self._logger).run(
            no_response_days=config.no_response_days,
            stale_conv_days=config.stale_conv_days,
        )

        summary = {
            "convs_processed": convs_processed,
            "convs_total": total,
            "stopped": stopped,
            "replies_sent": replies_sent,
            "resumes_sent": resumes_sent,
            "stage_changes": stage_changes,
            "llm_degraded": llm_degraded,
            # Surface per-conversation failures (were caught + swallowed with no count)
            # and finalize DB-tool failures so a run full of errors can't read as clean.
            "conv_errors": conv_errors,
            "finalize_errors": finalize_out.failed_count,
        }
        self._logger.close("done", summary=summary)
        return summary
