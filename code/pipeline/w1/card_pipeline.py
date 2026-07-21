import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Tuple

from pipeline.base import StepOutput, StepStatus
from pipeline.w1.steps.fetch_jd import FetchJDStep
from pipeline.w1.steps.apply import ApplyStep


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
        t0 = time.time()
        self._reg.set_context("classify", {"job_id": card.job_id})
        cls = self._reg.call("classify_job_for_w1", job_id=card.job_id)
        if cls.data.get("action") == "skip":
            # prior_status (APPLIED/CHATTING/INTERVIEWING/OFFER) tells the user WHY this
            # card was skipped — surfaced on both the step trace and the job_skipped
            # event so the monitor shows "已投过（CHATTING）" instead of a vague reason.
            prior_status = cls.data.get("prior_status", "")
            # Emit a terminal step event so the loop detail shows classify as a
            # finished "skipped" node (not a stuck pending dot), and the card badge
            # resolves correctly instead of falling back to "waiting".
            self._logger.log_step(
                "classify", scope, "skipped", int((time.time() - t0) * 1000),
                {"reason": "classify_skip", "prior_status": prior_status},
            )
            self._logger.log(
                "job_skipped",
                scope=scope,
                data={"reason": "classify_skip", "prior_status": prior_status},
                visible=True,
            )
            return StepOutput(status=StepStatus.SKIPPED), False, scored
        self._logger.log_step("classify", scope, "successful", int((time.time() - t0) * 1000), {})

        fetch = FetchJDStep(self._reg).run(card_dom_index=card.card_dom_index, job_id=card.job_id)
        if fetch.status != StepStatus.SUCCESSFUL:
            return fetch, False, scored
        jd_text = fetch.jd_text
        salary_decoded = fetch.salary_decoded

        # Content-fingerprint dedup (2nd tier): the cheap job_id classify above misses
        # the SAME posting re-encountered under a rotated encryptJobId. Now that the JD is
        # read (panel was opened for scoring anyway), check the content hash before
        # scoring — a hit means we already applied to this posting (active/successful),
        # so skip it (saves the LLM score too). content_hash is reused for upsert below.
        self._reg.set_context("classify", {"job_id": card.job_id})
        dup = self._reg.call(
            "check_content_duplicate",
            title=card.title,
            company_id=card.company_id,
            jd_text=jd_text,
        )
        content_hash = dup.data.get("content_hash") if dup.ok else None
        if dup.ok and dup.data.get("is_duplicate"):
            prior = dup.data.get("prior_status", "")
            self._logger.log_step(
                "apply", scope, "skipped", 0,
                {"reason": "content_duplicate", "prior_status": prior},
            )
            self._logger.log(
                "job_skipped",
                scope=scope,
                data={"reason": "content_duplicate", "prior_status": prior},
                visible=True,
            )
            return StepOutput(status=StepStatus.SKIPPED), False, scored

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
        snap = self._reg.call("capture_screenshot", label=card.job_id)
        screenshot = snap.data.get("screenshot") if snap.ok else None
        self._logger.log_step("apply", scope, "failed", 0, {"result": result})
        self._logger.log(
            "job_apply_failed",
            scope=scope,
            data={"result": result, "screenshot": screenshot, "error": apply_out.error},
            visible=True,
        )
        return StepOutput(status=StepStatus.FAILED), should_stop, scored
