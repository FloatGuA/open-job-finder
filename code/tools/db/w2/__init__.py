from tools.db.w2.upsert_hr_conversation import UpsertHRConversation
from tools.db.w2.write_hr_messages import WriteHRMessages
from tools.db.w2.update_hr_analysis import UpdateHRAnalysis
from tools.db.w2.mark_reply_sent import MarkReplySent
from tools.db.w2.get_approved_replies import GetApprovedReplies
from tools.db.w2.get_conversation_states import GetConversationStates
from tools.db.w2.sync_application_status import SyncApplicationStatusFromConversations
from tools.db.w2.backfill_application_from_conversation import BackfillApplicationFromConversation
from tools.db.w2.mark_timeout_statuses import MarkTimeoutStatuses
from tools.db.w2.purge_stale_applications import PurgeStaleApplications
from tools.db.w2.match_resume import MatchResume


def register_w2_tools(registry, db, model_router, prompt_manager, tool_providers=None) -> None:
    from tools.llm.analyze_intent import AnalyzeHRIntent
    from tools.llm.generate_reply import GenerateReply
    from tools.biz_logic.detect_resume import DetectResumeRequest
    from tools.biz_logic.filter_conversations import FilterConversations

    tp = tool_providers or {}
    registry.register(AnalyzeHRIntent(
        llm_client=model_router,
        prompt_manager=prompt_manager,
        provider_name=tp.get("analyze_intent"),
    ))
    # Reply drafting: separate think=True call, only when analysis says a reply is
    # needed. Shares the analyze_intent provider override (intent + reply, same model).
    registry.register(GenerateReply(
        llm_client=model_router,
        prompt_manager=prompt_manager,
        provider_name=tp.get("analyze_intent"),
    ))
    registry.register(DetectResumeRequest())
    registry.register(FilterConversations())
    registry.register(UpsertHRConversation(db=db))
    registry.register(WriteHRMessages(db=db))
    registry.register(UpdateHRAnalysis(db=db))
    registry.register(MarkReplySent(db=db))
    registry.register(GetApprovedReplies(db=db))
    registry.register(GetConversationStates(db=db))
    registry.register(SyncApplicationStatusFromConversations(db=db))
    registry.register(BackfillApplicationFromConversation(db=db))
    registry.register(MarkTimeoutStatuses(db=db))
    registry.register(PurgeStaleApplications(db=db))
    registry.register(MatchResume(db=db))
