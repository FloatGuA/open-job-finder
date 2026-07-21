"""W3 runner: assemble ToolRegistry, register W3 tools, run W3Pipeline.

Entry point for dashboard/server.py (_run_reply_workflow) and main.py (--reply).
W3 = send user-approved replies (approved/revision) with delivery verification.
Reuses a subset of W2 tools (navigate_to_chat_list / send_chat_message /
read_messages / write_hr_messages / get_approved_replies / mark_reply_sent)
+ 1 W3-only tool (search_locate_conversation). Delivery is verified by
re-scanning the thread with read_messages and persisting via write_hr_messages.
"""
import logging
from pathlib import Path
from typing import Optional

from pipeline.common.verify_session import VerifySessionStep
from pipeline.run_logger import RunLogger
from pipeline.w3.pipeline import W3Config, W3Pipeline
from services.browser_context import close_browser, open_browser
from tools.browser.w2.navigate_to_chat_list import NavigateToChatList
from tools.browser.w2.read_messages import ReadMessages
from tools.browser.w2.send_chat_message import SendChatMessage
from tools.browser.w3 import register_w3_browser_tools
from tools.db.w2.get_approved_replies import GetApprovedReplies
from tools.db.w2.mark_reply_sent import MarkReplySent
from tools.db.w2.record_locate_attempt import RecordLocateAttempt
from tools.db.w2.write_hr_messages import WriteHRMessages
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def run_w3(
    config: dict,
    tracker,
    model_router=None,
    emitter=None,
    dry_run: bool = False,
    max_replies: int = 50,
    headless: bool = False,
    debug: bool = False,
    data_dir: Optional[Path] = None,
) -> dict:
    """Send all user-approved replies, verifying delivery before marking sent."""
    if data_dir is None:
        data_dir = Path(__file__).resolve().parent.parent / "data"

    if emitter is not None:
        try:
            emitter.start_workflow("w3")
        except Exception:
            pass

    page = None
    run_logger = RunLogger(pipeline="w3", emitter=emitter, debug=debug)
    try:
        page = open_browser(data_dir, headless=headless)

        session = VerifySessionStep(page).run()
        if session.status != session.status.SUCCESSFUL:
            if session.error == "session_expired":
                raise RuntimeError(f"Boss session expired — please re-login: {session.reason}")
            raise RuntimeError(
                f"session verify failed (browser/page error, not necessarily logged out): {session.reason}"
            )

        registry = ToolRegistry(browser=page, db=tracker, llm_client=model_router, prompt_manager=None)
        registry.logger = run_logger

        registry.register(NavigateToChatList(browser=page))
        registry.register(SendChatMessage(browser=page))
        registry.register(ReadMessages(browser=page))
        register_w3_browser_tools(registry, page)
        registry.register(GetApprovedReplies(db=tracker))
        registry.register(MarkReplySent(db=tracker))
        registry.register(RecordLocateAttempt(db=tracker))
        registry.register(WriteHRMessages(db=tracker))

        pipeline = W3Pipeline(registry=registry, logger=run_logger)
        summary = pipeline.run(W3Config(dry_run=dry_run, max_replies=max_replies))
    except Exception as exc:
        logger.exception("W3 pipeline failed: %s", exc)
        try:
            run_logger.close("failed")
        except Exception:
            pass
        raise
    finally:
        if page is not None:
            close_browser(page)

    if emitter is not None:
        try:
            emitter.finish_workflow("w3", str(summary), status="done")
        except Exception:
            pass

    return summary
