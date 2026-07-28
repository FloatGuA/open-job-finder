"""W3 per-conversation resume send: Locate -> Idempotency -> Send -> clear+advance.

Delivers a resume the user MANUALLY staged (resume_status='queued') as the fallback
for W2's detector blind spot. Unlike the reply pipeline there is NO freshness gate:
a resume does not go stale -- if the HR asked for it, sending it is correct even if
the conversation moved on. The only guard is idempotency (skip if a resume was
already delivered) so we never double-send to a real HR.

Steps (each with an explicit completion check, not "action performed"):
- Locate      : the conversation actually OPENED (direct-open first, search fallback).
- Idempotency : re-scan; if detect_resume_request.already_sent (a delivered-resume
                system bubble exists), the queue flag is fulfilled -> clear it, skip.
- Send        : ResumeStep reports sent=True only after real delivery (accept_card /
                toolbar, incl. the cross-border confirm popover).
- Clear+adv   : clear resume_status and advance stage=resume_sent (forward-only).
Only a real delivery clears the queue via the send path; an already-sent skip also
clears it (the intent is satisfied either way). A failure keeps 'queued' for retry.
"""
import time
from dataclasses import dataclass
from typing import Optional

from pipeline.w2.steps.resume import ResumeStep


@dataclass
class SendResumeOutput:
    conv_id: str
    located: bool = False
    delivered: bool = False
    skipped_already_sent: bool = False
    # locate_failed | locate_gave_up | dry_run | send_failed | null
    failure_reason: Optional[str] = None


class SendResumePipeline:
    def __init__(self, registry, logger, config):
        self._reg = registry
        self._logger = logger
        self._cfg = config

    def _log(self, step, scope, status, start_ts, data=None, error=None):
        lg = getattr(self._reg, "logger", None) or self._logger
        if lg is None:
            return
        lg.log_step(step=step, scope=scope, status=status,
                    duration_ms=int((time.time() - start_ts) * 1000),
                    data=data or {}, error=error)

    def run(self, conv: dict) -> SendResumeOutput:
        conv_id = conv.get("conv_id", "")
        company = conv.get("company", "")
        hr_name = conv.get("hr_name", "")
        job_id = (conv.get("job_id", "") or "").strip()
        boss_conv_id = (conv.get("boss_conv_id", "") or "").strip()
        scope = {"conv_id": conv_id, "company": company, "job_id": job_id}
        out = SendResumeOutput(conv_id=conv_id)

        # ── Locate: direct-open first, search-box fallback ──────────────────
        ts = time.time()
        self._reg.set_context("locate", scope)
        method = ""
        err = None
        if job_id and boss_conv_id and boss_conv_id != "62001":
            nav = self._reg.call("navigate_to_conversation", conv_id=conv_id, company=company,
                                 hr_name=hr_name, boss_conv_id=boss_conv_id, job_id=job_id)
            if nav.ok:
                out.located = True
                method = nav.data.get("method", "")
            else:
                err = nav.error
        if not out.located:
            loc = self._reg.call("search_locate_conversation", conv_id=conv_id, company=company, hr_name=hr_name)
            out.located = bool(loc.ok and loc.data.get("located"))
            method = "search"
            err = loc.error
        self._log("locate", scope, "successful" if out.located else "failed", ts,
                  data={"method": method}, error=err)
        rec = self._reg.call("record_locate_attempt", conv_id=conv_id, located=out.located)
        if not out.located:
            if rec.ok and rec.data.get("given_up"):
                self._logger.log("resume_locate_gave_up", scope=scope,
                                 data={"fail_count": rec.data.get("count")}, visible=True)
                out.failure_reason = "locate_gave_up"
            else:
                out.failure_reason = "locate_failed"
            return out

        # ── Dry run: located, do nothing else ───────────────────────────────
        if self._cfg.dry_run:
            ts = time.time()
            self._reg.set_context("resume", scope)
            self._log("resume", scope, "skipped", ts, data={"dry_run": True})
            out.failure_reason = "dry_run"
            return out

        # ── Idempotency: skip if a resume was already delivered ─────────────
        ts = time.time()
        self._reg.set_context("detect", scope)
        rd = self._reg.call("read_messages")
        messages = rd.data.get("messages", []) if rd.ok else []
        det = self._reg.call("detect_resume_request", messages=messages)
        if det.ok and det.data.get("already_sent"):
            # Intent fulfilled: clear the queue flag so it stops re-appearing, but do
            # NOT re-send. Treated as success (the resume the user wanted IS there).
            self._reg.call("clear_resume_queue", conv_id=conv_id)
            out.skipped_already_sent = True
            self._log("detect", scope, "skipped", ts, data={"already_sent": True})
            self._logger.log("resume_already_sent", scope=scope,
                             data={"reason": "resume already delivered; queue cleared"}, visible=True)
            return out
        self._log("detect", scope, "successful", ts, data={"already_sent": False})

        # ── Send (reuses W2's ResumeStep: accept_card then toolbar) ─────────
        res_out = ResumeStep(self._reg).run(request_type="hr_card", scope=scope)
        if not res_out.sent:
            out.failure_reason = "send_failed"
            self._logger.log("resume_send_failed", scope=scope,
                             data={"reason": "no available send method"}, visible=True)
            return out
        out.delivered = True

        # ── Clear queue + advance stage (forward-only) ──────────────────────
        self._reg.call("clear_resume_queue", conv_id=conv_id)
        self._reg.set_context("upsert", scope)
        self._reg.call(
            "upsert_hr_conversation",
            conv_id=conv_id, hr_name=hr_name, company=company,
            boss_conv_id=boss_conv_id, stage="resume_sent",
            last_msg_preview=conv.get("last_msg_preview", "") or "",
            hr_title=conv.get("hr_title", "") or "", job_id=job_id,
        )
        self._logger.log("resume_sent", scope=scope,
                         data={"strategy_used": res_out.strategy_used}, visible=True)
        return out
