from dataclasses import dataclass
from typing import Optional

from pipeline.base import StepStatus
from pipeline.w1.card_pipeline import CardInput, CardPipeline
from pipeline.w1.steps.navigate import NavigateStep


@dataclass
class W1Config:
    url: str
    score_threshold: int
    dry_run: bool
    max_cards: Optional[int] = None


class W1Pipeline:
    def __init__(self, registry, profile, logger):
        self._reg = registry
        self._profile = profile
        self._logger = logger

    def run(self, config: W1Config) -> dict:
        nav = NavigateStep(self._reg).run(url=config.url)
        if nav.status != StepStatus.SUCCESSFUL:
            self._logger.close("failed")
            return {"cards_viewed": 0, "scored": 0, "applied": 0, "skipped": 0, "errors": 0, "error": "navigate_failed"}

        seen_job_ids: set = set()
        consecutive_skips = 0
        cards_viewed = 0
        applied = 0
        skipped = 0
        scored = 0
        errors = 0
        should_stop = False
        rate_limited = False  # True only when a card stopped the run via Boss's hard cap
        db_failures: list = []

        while True:
            self._reg.set_context("scan", {})
            page_check = self._reg.call("verify_current_url", expected_url=config.url)
            if not page_check.ok:
                self._logger.log(
                    "page_drift_detected",
                    scope={},
                    data={
                        "current_url": page_check.data.get("current_url", ""),
                        "expected_url": config.url,
                        "error": page_check.error,
                    },
                    visible=True,
                )
                break

            result = self._reg.call("extract_card_list")
            # A tool failure (selector drift / page error / browser hiccup) must NOT be
            # read as an empty result — that used to surface as "no_cards_found", masking
            # a real breakage as "search returned nothing". Surface it and stop.
            if not result.ok:
                self._logger.log(
                    "extract_cards_failed",
                    scope={},
                    data={"error": result.error, "seen_so_far": len(seen_job_ids)},
                    visible=True,
                )
                break
            cards = result.data.get("cards", [])

            # No cards on first pass means the search returned no results
            if not cards and not seen_job_ids:
                self._logger.log("no_cards_found", scope={}, data={})
                break

            new_cards = [c for c in cards if c["job_id"] not in seen_job_ids]
            self._logger.log_step(
                step="scan",
                scope={},
                status="successful",
                duration_ms=0,
                data={"card_count": len(cards), "new_card_count": len(new_cards)},
            )

            for card_data in new_cards:
                # Honor the 中止 button between cards (graceful — falls through to the
                # normal summary/close below, unlike a hard kill).
                if self._logger.should_stop():
                    should_stop = True
                    self._logger.log(
                        "run_stopped",
                        scope={},
                        data={"reason": "user_stop", "applied": applied, "viewed": cards_viewed},
                    )
                    break
                seen_job_ids.add(card_data["job_id"])
                cards_viewed += 1

                card_input = CardInput(
                    job_id=card_data["job_id"],
                    title=card_data.get("title", ""),
                    company=card_data.get("company", ""),
                    salary_raw=card_data.get("salary", ""),
                    city=card_data.get("city", ""),
                    hr_name=card_data.get("hr_name", ""),
                    card_dom_index=card_data.get("card_dom_index", 0),
                    company_id=card_data.get("company_id", ""),
                )

                output, stop, did_score = CardPipeline(self._reg, self._profile, self._logger, config, db_failures).run(card_input)

                if did_score:
                    scored += 1

                if output.status == StepStatus.SKIPPED:
                    skipped += 1
                    consecutive_skips += 1
                elif output.status == StepStatus.SUCCESSFUL:
                    applied += 1
                    consecutive_skips = 0
                else:
                    # FAILED (apply action failed: button_not_found/dialog_blocked/error)
                    # or DEGRADED (LLM score error): a technical failure, NOT an applied
                    # job. Reported per-job (job_apply_failed) with a failure screenshot.
                    errors += 1
                    consecutive_skips += 1

                if stop:
                    should_stop = True
                    # Distinguish a Boss daily-cap stop from a benign max_cards stop:
                    # only the former should pause scheduled/selfcheck runs for the day.
                    if getattr(output, "result", "") == "rate_limited":
                        rate_limited = True
                    break

                if consecutive_skips >= 5:
                    break

                if config.max_cards and cards_viewed >= config.max_cards:
                    should_stop = True
                    break

            if should_stop:
                break

            self._reg.set_context("scan", {})
            scroll = self._reg.call("scroll_search_results", current_card_count=len(seen_job_ids))
            if not scroll.ok:
                self._logger.log(
                    "scroll_stopped",
                    scope={},
                    data={"error": scroll.error, "attempts": scroll.data.get("attempts", 1)},
                )
                break
            if scroll.data.get("reached_end"):
                break

        if db_failures:
            self._logger.log(
                "db_write_failures_summary",
                scope={},
                data={"count": len(db_failures), "failures": db_failures},
                visible=True,
            )

        summary = {
            "cards_viewed": cards_viewed,
            "scored": scored,
            "applied": applied,
            "skipped": skipped,
            "errors": errors,
            "db_write_failures": len(db_failures),
            "rate_limited": rate_limited,
        }
        self._logger.close("done", summary=summary)
        return summary
