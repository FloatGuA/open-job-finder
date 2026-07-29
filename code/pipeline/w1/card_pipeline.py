from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple

from pipeline.base import StepOutput, StepStatus
from pipeline.w1.steps.fetch_jd import FetchJDStep
from pipeline.w1.steps.apply import ApplyStep
from tools.biz_logic.content_fingerprint import compute_content_hash


@dataclass
class CardInput:
    job_id: str
    title: str
    company: str
    salary_raw: str
    city: str
    hr_name: str
    card_dom_index: int
    company_id: str = ""


class CardPipeline:
    def __init__(self, registry, profile, logger, config, db_failures=None):
        self._reg = registry
        self._profile = profile
        self._logger = logger
        self._config = config
        self._db_failures = db_failures if db_failures is not None else []

    def run(self, card: CardInput) -> Tuple[StepOutput, bool, bool]:
        # Returns (output, should_stop, scored). `scored` = this card reached the LLM
        # scoring stage (got a real score), so the run summary can report how many of
        # the viewed cards were actually scored vs skipped before scoring.
        scored = False
        scope = {"job_id": card.job_id, "company": card.company}

        # W1 no longer skips jobs it thinks were already applied to. The old DB-based
        # dedup (job_id classify + content fingerprint) was dropping real opportunities:
        # Boss's search surfaces a posting only when it is NOT already an active
        # conversation, yet our applications table (proven unreliable — 150 greetings
        # sent were once recorded as 63, later back-filled) kept flagging these as
        # APPLIED and skipping them. We now trust Boss's search results and let the
        # apply step's REAL button state (立即沟通 vs 继续沟通 → already_chatting) be the
        # sole authority on "already applied" — it never double-greets an HR. Simplifying
        # the flow this way removes the whole class of "wrongly skipped" bugs at the root.
        # See PROGRESS 2026-07-28.
        fetch = FetchJDStep(self._reg).run(card_dom_index=card.card_dom_index, job_id=card.job_id)
        if fetch.status != StepStatus.SUCCESSFUL:
            return fetch, False, scored
        jd_text = fetch.jd_text
        salary_decoded = fetch.salary_decoded

        # content_hash is still stored on the application row (cheap; kept in case dedup
        # is ever reintroduced) but is no longer used to skip anything.
        content_hash = compute_content_hash(card.title, card.company_id, jd_text)

        if self._config.score_threshold <= 0:
            # 阈值 <= 0：跳过 LLM 评分，直接投递（纯流程验证，不消耗 LLM）
            score = 0
            self._logger.log(
                "job_scored",
                scope={"job_id": card.job_id, "company": card.company},
                data={"score": 0, "reason": "threshold<=0, scoring skipped", "above_threshold": True},
            )
        else:
            score_res = self._reg.call(
                "score_job",
                job_id=card.job_id,
                title=card.title,
                company=card.company,
                jd_text=jd_text,
                profile=self._profile,
            )
            if not score_res.ok:
                # Not applied (scoring failed): mark apply as a terminal skipped step
                # so the loop detail + badge read "skipped", not "waiting".
                self._logger.log_step("apply", scope, "skipped", 0, {"reason": "llm_error"})
                self._logger.log(
                    "job_skipped",
                    scope=scope,
                    data={"reason": "llm_error"},
                    visible=True,
                )
                return StepOutput(status=StepStatus.DEGRADED, error=score_res.error), False, scored

            score = score_res.data["score"]
            scored = True
            self._logger.log(
                "job_scored",
                scope={"job_id": card.job_id, "company": card.company},
                data={
                    "score": score,
                    "reason": score_res.data.get("reason", ""),
                    "above_threshold": score >= self._config.score_threshold,
                    "provider_used": score_res.data.get("provider_used", ""),
                },
            )

            # Eval-collection: record EVERY real scoring (applied AND skipped) so a
            # re-scorable golden accrues for score-quality eval. Placed before the
            # threshold branch so both sides are captured. Non-fatal -- instrumentation
            # must never fail an apply (registry.call returns a ToolResult, never raises).
            self._reg.call(
                "record_scored_job",
                job_id=card.job_id,
                title=card.title,
                company=card.company,
                jd_text=jd_text,
                score=score,
                dimensions=score_res.data.get("dimensions", {}),
                reason=score_res.data.get("reason", ""),
                provider_used=score_res.data.get("provider_used", ""),
                threshold=self._config.score_threshold,
                above_threshold=score >= self._config.score_threshold,
            )

            if score < self._config.score_threshold:
                # Not applied (score below threshold): terminal skipped apply step.
                self._logger.log_step(
                    "apply", scope, "skipped", 0, {"reason": "score_below", "score": score},
                )
                self._logger.log(
                    "job_skipped",
                    scope=scope,
                    data={"reason": "score_below", "score": score},
                    visible=True,
                )
                return StepOutput(status=StepStatus.SKIPPED), False, scored

        apply_out = ApplyStep(self._reg).run(
            dry_run=self._config.dry_run,
            scope={"job_id": card.job_id, "company": card.company},
        )
        should_stop = apply_out.should_stop
        result = apply_out.result

        # Only persist APPLIED when a real click was confirmed.
        # button_not_found / dialog_blocked / error → don't save, retry next run.
        # already_chatting → existing conversation means we already applied.
        if result in ("applied", "already_chatting"):
            now = datetime.now(timezone.utc).isoformat()
            self._reg.set_context("upsert", {"job_id": card.job_id})
            upsert = self._reg.call(
                "upsert_application",
                job_id=card.job_id,
                url=f"https://www.zhipin.com/job_detail/{card.job_id}.html",
                title=card.title,
                company=card.company,
                status="APPLIED",
                # Prefer the HR name read from the detail panel (job-boss-info) — the
                # search card never carries it, so card.hr_name is blank. A populated
                # applications.hr_name is what lets sync_application_status JOIN to
                # hr_conversations.hr_name (both bare names now).
                hr_name=fetch.hr_name or card.hr_name,
                city=card.city,
                salary=salary_decoded,
                score=score,
                applied_at=now,
                content_hash=content_hash,
            )
            self._logger.log_step(
                "upsert", scope, "successful" if upsert.ok else "failed", 0,
                {"result": result}, error=None if upsert.ok else upsert.error,
            )
            if not upsert.ok:
                self._logger.log(
                    "db_write_failed",
                    scope={"job_id": card.job_id, "company": card.company},
                    data={"title": card.title, "status": "APPLIED", "error": upsert.error},
                    visible=True,
                )
                self._db_failures.append({
                    "job_id": card.job_id,
                    "title": card.title,
                    "company": card.company,
                })
            # Hard-association (W1→W2): pre-create the conversation stub keyed on
            # conv_id = job_id (== derive_conv_id when a job_id is present), stage
            # 'new'. When HR replies, the W2 scan updates THIS row instead of
            # creating a parallel one, so application and conversation are linked
            # from apply time. Non-fatal: a stub failure never fails the apply.
            self._reg.set_context("upsert", {"job_id": card.job_id})
            stub = self._reg.call(
                "upsert_hr_conversation",
                conv_id=card.job_id,
                hr_name=fetch.hr_name or card.hr_name or "",
                company=card.company,
                stage="new",
                job_id=card.job_id,
            )
            if not stub.ok:
                self._logger.log(
                    "hr_conversation_stub_failed",
                    scope={"job_id": card.job_id, "company": card.company},
                    data={"error": stub.error},
                    visible=False,
                )
            self._logger.log(
                "job_applied",
                scope={"job_id": card.job_id},
                data={"result": result, "db_ok": upsert.ok},
            )
            # Boss showed its "还剩N次" quota reminder on this (successful) apply — we
            # are near the daily cap. Surface a visible warning so the monitor flags it
            # before the hard cap stops the run.
            notice = getattr(apply_out, "quota_notice", "")
            if notice:
                self._logger.log(
                    "w1_quota_warning",
                    scope={"job_id": card.job_id, "company": card.company},
                    data={"message": notice},
                    visible=True,
                )
            return apply_out, should_stop, scored

        if result == "dry_run":
            # Dry-run deliberately does not click apply. ApplyStep already logged this
            # step as SUCCESSFUL; falling through to the technical-failure branch below
            # logged a SECOND contradictory 'apply failed' for the same step, emitted
            # job_apply_failed (a red "投递失败" in the monitor), and burned a failure
            # screenshot on every single dry run. Not applying is the expected outcome
            # here, not an error.
            return apply_out, should_stop, scored

        if result == "rate_limited":
            # Boss daily greeting cap hit — a global stop, NOT a per-job apply failure.
            # Surface it as a distinct visible event (not a red apply-failed) so the
            # monitor shows WHY the run ended, then let the caller stop the loop.
            self._logger.log_step("apply", scope, "skipped", 0, {"result": result})
            self._logger.log(
                "w1_rate_limited",
                scope=scope,
                data={"message": apply_out.message},
                visible=True,
            )
            return apply_out, should_stop, scored

        # Technical apply failure (button_not_found / dialog_blocked / error): the apply
        # ACTION did not confirm. Applying needs no HR reply, so this is a process error,
        # not a rejection. Screenshot what the browser actually showed (captcha / rate-
        # limit interstitial / navigated away), report it as a visible per-job failure,
        # and do NOT count it as applied.
        self._reg.set_context("apply", scope)
        # Name the shot {run_id}_{job_id} so a failure image maps back to a specific run
        # AND the specific card within it (the filename is the only handle on which run).
        snap = self._reg.call("capture_screenshot", label=f"{self._logger.run_id}_{card.job_id}")
        screenshot = snap.data.get("screenshot") if snap.ok else None
        self._logger.log_step("apply", scope, "failed", 0, {"result": result})
        self._logger.log(
            "job_apply_failed",
            scope=scope,
            data={"result": result, "screenshot": screenshot, "error": apply_out.error},
            visible=True,
        )
        return StepOutput(status=StepStatus.FAILED), should_stop, scored
