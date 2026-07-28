import time
from dataclasses import dataclass, field

from pipeline.base import StepOutput, StepStatus
from pipeline.w2.conversation_pipeline import ApprovedReply, ConvBasic

_CHAT_URL = "https://www.zhipin.com/web/geek/chat"
_MAX_SCAN_ATTEMPTS = 3
_RETRY_DELAY = 2.0  # seconds; multiplied by attempt number for a simple backoff


@dataclass
class ScanStepOutput(StepOutput):
    conversations_to_process: list = field(default_factory=list)
    approved_replies: dict = field(default_factory=dict)


class ScanStep:
    def __init__(self, registry):
        self._reg = registry

    def run(self, active_window_days: int = 0) -> ScanStepOutput:
        logger = getattr(self._reg, "logger", None)

        # Scan (navigate + full scroll) with retry. An empty conversation list is
        # almost always a transient failure (page not ready, drift, late SPA
        # render), and scan is the linchpin of W2: nothing downstream can run
        # without conversations. So we retry a few times before giving up, and
        # treat a persistently empty list as a visible hard failure.
        all_convs: dict = {}
        chat_url = _CHAT_URL
        last_error = None
        stop_reason = "reached_end"
        source = "api"
        for attempt in range(1, _MAX_SCAN_ATTEMPTS + 1):
            all_convs, chat_url, last_error, stop_reason, source = self._scan_once(
                logger, force_reload=(attempt > 1)
            )
            if all_convs:
                break
            if attempt < _MAX_SCAN_ATTEMPTS:
                if logger:
                    logger.log_step(
                        step="scan_list",
                        scope={},
                        status="running",
                        duration_ms=0,
                        data={"attempt": attempt, "max_attempts": _MAX_SCAN_ATTEMPTS},
                        error="empty conversation list, retrying",
                    )
                time.sleep(_RETRY_DELAY * attempt)

        if not all_convs:
            # Exhausted retries with an empty list -> visible hard failure.
            if logger:
                logger.log_step(
                    step="scan_list",
                    scope={},
                    status="failed",
                    duration_ms=0,
                    data={"total_conversations": 0, "attempts": _MAX_SCAN_ATTEMPTS},
                    error=last_error or "no_conversations_extracted",
                )
            return ScanStepOutput(
                status=StepStatus.FAILED,
                error="no_conversations_extracted",
            )

        current_convs = list(all_convs.values())
        if logger:
            # reached_end == clean full scan (green/done). A scan cut short by page
            # drift or a scroll error still has data but is incomplete -> degraded
            # (gray), so a non-debug observer can tell a full scan from a truncated
            # one at a glance; the precise reason rides in data.stop_reason.
            truncated = stop_reason in ("page_drift", "scroll_error", "extract_error")
            # source == "dom" means the getGeekFriendList XHR capture came up empty and
            # extract fell back to the DOM scrape — which supplies NO job_id and a
            # useless boss_conv_id ('62001'), so every direct-open is disabled and W2
            # navigate degrades to the slow (often-failing) scroll-search. Surface it
            # so a run full of navigate failures is traceable to the scan, not guessed.
            logger.log_step(
                step="scan_list",
                scope={},
                status="degraded" if (truncated or source == "dom") else "successful",
                duration_ms=0,
                data={"total_conversations": len(current_convs), "stop_reason": stop_reason, "source": source},
            )

        # Load approved replies and stored states
        self._reg.set_context("scan", {})
        approved_res = self._reg.call("get_approved_replies")
        approved_list = approved_res.data.get("conversations", [])
        approved_reply_ids = [c["conv_id"] for c in approved_list]
        approved_map = {
            c["conv_id"]: ApprovedReply(conv_id=c["conv_id"], reply_text=c["reply_text"])
            for c in approved_list
        }

        # Note: sending approved replies (and locating a conversation that has
        # dropped out of the scanned chat list) is now W3's job — W3 uses the chat
        # search box to locate, so W2 no longer alarms on "approved reply conv
        # missing from scan". approved_reply_ids is still passed to the filter below
        # so such conversations are re-read/analyzed (their approved reply_text is
        # protected by update_hr_analysis and stays intact for W3).

        states_res = self._reg.call("get_conversation_states", conv_ids=list(all_convs.keys()))
        stored_states = states_res.data.get("states", {})

        filter_res = self._reg.call(
            "filter_conversations",
            current_convs=current_convs,
            stored_states=stored_states,
            approved_reply_ids=approved_reply_ids,
            active_window_days=active_window_days,
        )
        to_process_raw = filter_res.data.get("conversations_to_process", [])
        decisions = filter_res.data.get("decisions", [])
        by_reason = filter_res.data.get("summary", {})

        if logger:
            # Per-conversation decision trace -> file log only. visible=False keeps
            # these off the SSE stream (the frontend gets the by_reason summary
            # below instead), while the file run-log records exactly why each
            # conversation was processed or skipped this round -- the key signal
            # when debugging "why didn't W2 touch conversation X".
            for d in decisions:
                logger.log(
                    "filter_decision",
                    scope={"conv_id": d.get("conv_id", "")},
                    data={
                        "action": d.get("action", ""),
                        "reason": d.get("reason", ""),
                        "stage": d.get("stage", ""),
                        "has_unread": d.get("has_unread", False),
                    },
                    visible=False,
                )
            # Summary -> file + SSE: counts by reason (no_change / preview_changed /
            # unread / new / approved / terminal) so the frontend shows an at-a-glance
            # breakdown without per-conversation noise.
            breakdown = ", ".join(f"{k}:{v}" for k, v in by_reason.items())
            summary_msg = f"filter: {len(to_process_raw)}/{len(current_convs)} to process"
            if breakdown:
                summary_msg += f" | {breakdown}"
            logger.log_step(
                step="scan_filter",
                scope={},
                status="successful",
                duration_ms=0,
                data={
                    "total": len(current_convs),
                    "to_process": len(to_process_raw),
                    "approved_replies": len(approved_list),
                    "by_reason": by_reason,
                },
                message=summary_msg,
            )

        conversations_to_process = [
            ConvBasic(
                conv_id=c["conv_id"],
                hr_name=c.get("hr_name", ""),
                company=c.get("company", ""),
                boss_conv_id=c.get("boss_conv_id", ""),
                hr_title=c.get("hr_title", ""),
                last_msg_preview=c.get("last_msg_preview", ""),
                job_id=c.get("job_id") or None,
                last_msg_ts=c.get("last_msg_ts", 0),
            )
            for c in to_process_raw
        ]

        return ScanStepOutput(
            status=StepStatus.SUCCESSFUL,
            conversations_to_process=conversations_to_process,
            approved_replies=approved_map,
        )

    def _scan_once(self, logger, force_reload: bool = False):
        """One navigate + full-scroll pass.

        Returns (all_convs, chat_url, error, stop_reason, source): error is a string
        when navigation failed, else None. An empty all_convs with error=None means the
        page loaded but no conversations were present. stop_reason records why the
        scroll loop ended: reached_end / page_drift / scroll_error / nav_failed.
        source is "api" (getGeekFriendList XHR) or "dom" (fallback scrape) — the last
        extract's source; "dom" flags a capture failure that disables W2 direct-open.
        """
        start_ts = time.time()
        source = "api"

        # Navigate to chat list
        self._reg.set_context("scan", {})
        nav = self._reg.call("navigate_to_chat_list", force=force_reload)
        if not nav.ok:
            if logger:
                logger.log_step(
                    step="scan_navigate",
                    scope={},
                    status="failed",
                    duration_ms=int((time.time() - start_ts) * 1000),
                    data={},
                    error=nav.error,
                )
            return {}, _CHAT_URL, nav.error or "navigate_to_chat_list failed", "nav_failed", source

        chat_url = nav.data.get("loaded_url", _CHAT_URL)
        if logger:
            logger.log_step(
                step="scan_navigate",
                scope={},
                status="successful",
                duration_ms=int((time.time() - start_ts) * 1000),
                data={"loaded_url": chat_url, "navigated": nav.data.get("navigated", True)},
            )

        # Scroll through full conversation list.
        #
        # extract_conversation_list now drains the getGeekFriendList XHR log, which
        # returns a whole API page (~100 conversations) at once — decoupled from the
        # ~15 rows the DOM renders. So end-of-list can no longer be detected from
        # DOM-row identity (scroll_chat_list's own seen-set logic assumed
        # extract ≈ visible rows). Instead we drive termination here from API-page
        # growth: each scroll to the bottom triggers Boss to fetch the next page;
        # when two consecutive scrolls add no new conversations, the list is
        # exhausted. A hard cap guards against a pathological non-terminating churn.
        all_convs: dict = {}
        stop_reason = "reached_end"
        stale_scrolls = 0
        max_scrolls = 80
        for _ in range(max_scrolls):
            # Honor 中止 during the (potentially long) scroll-to-bottom pagination.
            if logger is not None and logger.should_stop():
                stop_reason = "user_stop"
                break
            self._reg.set_context("scan", {})

            # Guard: verify we're still on chat page before each extract
            page_check = self._reg.call("verify_current_url", expected_url=chat_url)
            if not page_check.ok:
                if logger:
                    logger.log("page_drift_detected",
                               scope={},
                               data={"current_url": page_check.data.get("current_url", ""),
                                     "expected_url": chat_url,
                                     "error": page_check.error},
                               visible=True)
                stop_reason = "page_drift"
                break

            result = self._reg.call("extract_conversation_list")
            if not result.ok:
                # Don't silently contribute zero items: a failed extract means
                # the page is in a bad state. Stop scrolling and mark the scan as
                # truncated (degraded) rather than under-counting in silence.
                stop_reason = "extract_error"
                break
            source = result.data.get("source", source)
            prev_count = len(all_convs)
            for item in result.data.get("items", []):
                if item["conv_id"] not in all_convs:
                    all_convs[item["conv_id"]] = item
            grew = len(all_convs) > prev_count

            # scroll_chat_list still performs the physical scroll; its own
            # reached_end signal (DOM-based) is ignored — we judge end by growth.
            scroll = self._reg.call("scroll_chat_list", seen_conv_ids=[])
            if not scroll.ok:
                stop_reason = "scroll_error"
                break

            if grew:
                stale_scrolls = 0
            else:
                stale_scrolls += 1
                if stale_scrolls >= 2:
                    stop_reason = "reached_end"
                    break

        return all_convs, chat_url, None, stop_reason, source
