from tools.db.w1.classify_job_for_w1 import ClassifyJobForW1
from tools.db.w1.check_content_duplicate import CheckContentDuplicate
from tools.db.w1.upsert_application import UpsertApplication
from tools.db.w2.upsert_hr_conversation import UpsertHRConversation


def register_w1_tools(registry, db, model_router, prompt_manager, tool_providers=None) -> None:
    """Register all W1 non-browser tools into the given ToolRegistry."""
    from tools.biz_logic.decode_salary import DecodeJobSalary
    from tools.llm.score_job import ScoreJob

    tp = tool_providers or {}
    registry.register(ScoreJob(
        llm_client=model_router,
        prompt_manager=prompt_manager,
        provider_name=tp.get("score_job"),
    ))
    registry.register(DecodeJobSalary())
    registry.register(ClassifyJobForW1(db=db))
    registry.register(CheckContentDuplicate(db=db))
    registry.register(UpsertApplication(db=db))
    # Hard-association: W1 pre-creates a conversation stub (conv_id = job_id) at
    # apply time so a W1 application and its future W2 conversation share one
    # identity from the start. Reuses the W2 upsert tool — same canonical write.
    registry.register(UpsertHRConversation(db=db))
