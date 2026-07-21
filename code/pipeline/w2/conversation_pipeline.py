from dataclasses import dataclass
from typing import Optional

from pipeline.base import StepStatus
from pipeline.w2.steps.analyze import AnalyzeStep
from pipeline.w2.steps.navigate import W2NavigateStep
from pipeline.w2.steps.read import ReadStep
from pipeline.w2.steps.resume import ResumeStep
from pipeline.w2.steps.wechat import WechatStep


INTENT_STAGE_MAP = {
    "interview_invite": "interview",
    "offer": "offer",
    "rejection": "closed",
}

STAGE_ORDER = ["new", "active", "resume_sent", "interview", "offer", "closed"]


def _stage_rank(s: str) -> int:
    try:
        return STAGE_ORDER.index(s)
    except ValueError:
        return 0


@dataclass
class ConvBasic:
    conv_id: str
    hr_name: str
    company: str
    boss_conv_id: str
    hr_title: str = ""
    last_msg_preview: str = ""
    job_id: Optional[str] = None
    last_msg_ts: int = 0


@dataclass
class ApprovedReply:
    conv_id: str
    reply_text: str


@dataclass
class ConversationPipelineOutput:
    reply_sent: bool = False
    resume_sent: bool = False
    stage_changed: bool = False
    llm_degraded: bool = False
    error: Optional[str] = None


class ConversationPipeline:
    def __init__(self, registry, profile, logger, config):
        self._reg = registry
        self._profile = profile
        self._logger = logger
        self._config = config

    def run(
        self,
        conv: ConvBasic,
        approved_reply: Optional[ApprovedReply],
    ) -> ConversationPipelineOutput:
        nav = W2NavigateStep(self._reg).run(conv)
        if nav.status == StepStatus.FAILED:
            return ConversationPipelineOutput(error="navigate_failed")
        boss_conv_id = nav.boss_conv_id_confirmed or conv.boss_conv_id

        read = ReadStep(self._reg).run(conv_id=conv.conv_id)
        if read.status == StepStatus.FAILED:
            return ConversationPipelineOutput(error="read_failed")
        messages = read.messages

        # Auto-agree to an HR 'exchange WeChat' card while the conversation is open.
        # Idempotent + cheap (a single DOM query); skipped in dry-run since agreeing
        # is an irreversible outbound action toward a real HR.
        if not self._config.dry_run:
            WechatStep(self._reg).run(scope={"conv_id": conv.conv_id, "company": conv.company})

        analyze = AnalyzeStep(self._reg).run(conv=conv, messages=messages)
        llm_degraded = analyze.status == StepStatus.DEGRADED
        if analyze.status == StepStatus.SUCCESSFUL:
            self._logger.log(
                "intent_analyzed",
                scope={"conv_id": conv.conv_id},
                data={
                    "intent": analyze.intent,
                    "confidence": "high" if analyze.intent != "unknown" else "low",
                    "provider_used": analyze.provider_used,
                },
            )
        elif llm_degraded:
            # All LLM providers failed for this conversation -- intent fell back to
            # "unknown" (not fabricated). Surface it loudly so it is countable, not
            # silently buried; the run summary aggregates these.
            self._logger.log(
                "llm_degraded",
                scope={"conv_id": conv.conv_id, "company": conv.company},
                data={"error": analyze.error},
            )
        needs_resume = analyze.needs_resume
        already_sent_resume = analyze.already_sent_resume
        intent = analyze.intent

        new_stage = "new"
        if intent in INTENT_STAGE_MAP:
            candidate = INTENT_STAGE_MAP[intent]
            if _stage_rank(candidate) > _stage_rank(new_stage):
                new_stage = candidate
        elif new_stage == "new":
            new_stage = "active"

        resume_sent = False
        if needs_resume and not already_sent_resume and not self._config.dry_run:
            res_out = ResumeStep(self._reg).run(
                request_type=analyze.request_type,
                scope={"conv_id": conv.conv_id},
            )
            if res_out.sent:
                resume_sent = True
                if _stage_rank("resume_sent") > _stage_rank(new_stage):
                    new_stage = "resume_sent"
                self._logger.log(
                    "resume_sent",
                    scope={"conv_id": conv.conv_id},
                    data={"strategy_used": res_out.strategy_used},
                )
        else:
            # No resume to send: emit an explicit skipped step so the monitor shows
            # "跳过" instead of a forever-pending "等待" dot. The conversation IS done
            # after analyze -- the resume step just doesn't apply here. Emitted on both
            # the live SSE stream (log_step is not debug-gated) and the run JSONL.
            if not needs_resume:
                skip_msg = "HR 未索要简历，无需发送"
            elif already_sent_resume:
                skip_msg = "简历此前已发送"
            else:
                skip_msg = "演练模式，跳过发送简历"
            self._logger.log_step(
                step="resume",
                scope={"conv_id": conv.conv_id, "company": conv.company},
                status="skipped",
                duration_ms=0,
                data={},
                message=skip_msg,
            )

        # Reply sending is owned by W3 (send + delivery verification). W2 only
        # understands/drafts; it no longer sends approved replies here (the old
        # ReplyStep marked sent without verifying delivery → false success).
        reply_sent_flag = False

        # Increment detection (filter_conversations) compares this stored value
        # against next run's chat-list preview from extract_conversation_list.
        # Both sides MUST come from the same source -- the list-row preview --
        # otherwise they never match and every conversation is reprocessed each
        # run. So store the scan-time list preview, not the in-conversation last
        # message (which is a different DOM source, capped differently, and is the
        # pre-reply snapshot). Trade-off: a conversation we just replied to gets
        # reprocessed exactly once more next run (its list preview now shows our
        # sent message), then converges. Edge: two HR messages rendering to the
        # same preview text could be missed if unread was cleared externally --
        # has_unread covers the normal case.
        last_preview = conv.last_msg_preview
        upsert = self._reg.call(
            "upsert_hr_conversation",
            conv_id=conv.conv_id,
            hr_name=conv.hr_name,
            company=conv.company,
            boss_conv_id=boss_conv_id,
            stage=new_stage,
            last_msg_preview=last_preview,
            hr_title=conv.hr_title,
            job_id=conv.job_id or "",
            last_msg_ts=conv.last_msg_ts,
        )
        if not upsert.ok:
            # Persisting the conversation's new stage is the whole point of this
            # pipeline. A failed upsert must be loud (visible red), not silently
            # treated as "no change". Skip to the next conversation; reply/resume
            # that already happened are still reported.
            self._logger.log_step(
                step="upsert",
                scope={"conv_id": conv.conv_id, "company": conv.company},
                status="failed",
                duration_ms=0,
                data={},
                error=upsert.error,
            )
            return ConversationPipelineOutput(
                reply_sent=reply_sent_flag,
                resume_sent=resume_sent,
                llm_degraded=llm_degraded,
                error="upsert_failed",
            )

        stage_changed = upsert.data.get("stage_changed", False)
        if stage_changed:
            self._logger.log(
                "stage_advanced",
                scope={"conv_id": conv.conv_id, "company": conv.company},
                data={
                    "old_stage": upsert.data.get("prev_stage", "unknown"),
                    "new_stage": upsert.data.get("stage", new_stage),
                },
            )

        return ConversationPipelineOutput(
            reply_sent=reply_sent_flag,
            resume_sent=resume_sent,
            stage_changed=stage_changed,
            llm_degraded=llm_degraded,
        )
