import time
from dataclasses import dataclass

from pipeline.base import StepOutput, StepStatus


@dataclass
class FinalizeStepOutput(StepOutput):
    updated_count: int = 0
    closed_count: int = 0
    failed_count: int = 0


class FinalizeStep:
    def __init__(self, registry, logger):
        self._reg = registry
        self._logger = logger

    def run(self, no_response_days: int, stale_conv_days: int) -> FinalizeStepOutput:
        start_ts = time.time()
        self._reg.set_context("finalize", {})

        # Each DB tool below used to fold a failure into a silent 0 while the step still
        # reported 'successful' — a failed status sync / stale-close / purge would vanish.
        # Collect failures so the step degrades (not fakes success) and they reach summary.
        failures: list = []

        # 0. Two-table reconcile (W2→W1): materialise an APPLIED application for any
        #    conversation that has a job_id but no application (HR contacted us first /
        #    apply-not-recorded / purged). Runs BEFORE sync so the new rows get their
        #    status promoted from conversation stage in this same pass.
        backfill = self._reg.call("backfill_application_from_conversation")
        if not backfill.ok:
            failures.append(("backfill_application_from_conversation", backfill.error))
        backfilled = backfill.data.get("backfilled_count", 0) if backfill.ok else 0
        if backfilled:
            self._logger.log(
                "applications_backfilled",
                scope={},
                data={"count": backfilled},
            )

        # 1. Sync application status from conversation stage (interview/offer, explicit
        #    rejection, and REJECTED→APPLIED revival when HR re-engaged).
        sync = self._reg.call("sync_application_status_from_conversations")
        if not sync.ok:
            failures.append(("sync_application_status_from_conversations", sync.error))
        updated = sync.data.get("updated_count", 0) if sync.ok else 0

        # 2. Soft-mark conversations stalled after `no_response_days` (stage='closed').
        #    Applications are NOT rejected here — a stall is a reminder, not a rejection.
        timeout = self._reg.call(
            "mark_timeout_rejections",
            no_response_days=no_response_days,
            stale_conv_days=stale_conv_days,
        )
        if not timeout.ok:
            failures.append(("mark_timeout_rejections", timeout.error))
        closed = 0
        if timeout.ok:
            for conv_id in timeout.data.get("stale_closed", []):
                self._logger.log(
                    "conv_timeout_closed",
                    scope={"conv_id": conv_id},
                    data={},
                )
                closed += 1

        # 3. Auto-revive by cleanup: purge jobs applied > stale_conv_days ago with no
        #    progress (deletes application + conversation + messages) so the posting
        #    re-runs the full W1 pipeline when it resurfaces.
        purge = self._reg.call("purge_stale_applications", days=stale_conv_days)
        if not purge.ok:
            failures.append(("purge_stale_applications", purge.error))
        purged = 0
        if purge.ok:
            for job_id in purge.data.get("purged", []):
                self._logger.log(
                    "job_purged",
                    scope={"job_id": job_id},
                    data={},
                )
                purged += 1

        if failures:
            self._logger.log(
                "finalize_tool_failures",
                scope={},
                data={"failures": [{"tool": name, "error": err} for name, err in failures]},
                visible=True,
            )

        self._logger.log_step(
            step="finalize",
            scope={},
            status="degraded" if failures else "successful",
            duration_ms=int((time.time() - start_ts) * 1000),
            data={
                "applications_backfilled": backfilled,
                "status_synced": updated,
                "stale_closed": closed,
                "purged": purged,
                "failed_tools": [name for name, _ in failures],
            },
        )

        return FinalizeStepOutput(
            status=StepStatus.DEGRADED if failures else StepStatus.SUCCESSFUL,
            updated_count=updated,
            closed_count=closed,
            failed_count=len(failures),
        )
