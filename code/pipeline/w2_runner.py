"""
W2 runner: assemble ToolRegistry, register W2 tools, and run W2Pipeline.

Entry point for both main.py (--check) and dashboard/server.py
(_run_check_workflow).
"""
import logging
from pathlib import Path
from typing import Optional

from pipeline.common.verify_session import VerifySessionStep
from pipeline.run_logger import RunLogger
from pipeline.w2.pipeline import W2Config, W2Pipeline
from services.browser_context import close_browser, open_browser
from services.profile_loader import ProfileLoader
from services.prompt_manager import PromptManager
from tools.browser.w2 import register_w2_browser_tools
from tools.db.w2 import register_w2_tools
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def run_w2(
    config: dict,
    tracker,
    model_router,
    emitter=None,
    dry_run: bool = False,
    max_conversations: int = 200,
    no_response_days: int = 14,
    stale_conv_days: int = 30,
    auto_send_adapted_resume: bool = False,
    headless: bool = True,
    debug: bool = False,
    data_dir: Optional[Path] = None,
    trigger: str = "manual",
    max_run_minutes: int = 25,
) -> dict:
    """Run the W2 (check responses) pipeline end-to-end.

    Args:
        config: raw config dict (from config.yaml).
        tracker: ApplicationTracker instance.
        model_router: ModelRouter instance for LLM calls.
        emitter: optional ProgressEmitter for SSE push.
        dry_run: if True, skip actual send actions.
        max_conversations: cap on conversations to inspect.
        no_response_days: mark as no-response after this many days.
        stale_conv_days: treat conversation as stale after this many days.
        headless: run browser in headless mode.
        debug: if True, emit SSE events for individual tool calls.
        data_dir: path to the data/ directory; auto-detected if None.

    Returns:
        summary dict from W2Pipeline.run().
    """
    if data_dir is None:
        data_dir = Path(__file__).resolve().parent.parent / "data"

    # 1. Load profile (fail fast — see w1_runner: a silent `return {"error":...}` here
    #    was misrecorded as success by the queue runner and leaked the browser mutex.)
    profile = ProfileLoader(data_dir / "profile.yaml").load()

    # 2. Build prompt manager (with user-configured prompt injection from profile)
    prompt_manager = PromptManager(injection=profile.prompt_injection)

    # 4. Notify emitter that workflow is starting (run_meta = launcher + run knobs).
    run_meta = {
        "trigger": trigger,
        "params": {
            "max_conversations": max_conversations,
            "no_response_days": no_response_days,
            "stale_conv_days": stale_conv_days,
            "dry_run": dry_run,
            "headless": headless,
        },
    }
    if emitter is not None:
        try:
            emitter.start_workflow("w2", meta=run_meta)
        except Exception:
            pass

    page = None
    run_logger = RunLogger(pipeline="w2", emitter=emitter, debug=debug, meta=run_meta)

    try:
        # 5. Open browser
        page = open_browser(data_dir, headless=headless)

        # 5b. Verify session before doing anything
        session = VerifySessionStep(page).run()
        if session.status != session.status.SUCCESSFUL:
            if session.error == "session_expired":
                raise RuntimeError(f"Boss session expired — please re-login: {session.reason}")
            # Not a confirmed logout (browser/page hiccup): say so instead of the
            # misleading "session invalid", which sent us chasing a non-existent re-login.
            raise RuntimeError(
                f"session verify failed (browser/page error, not necessarily logged out): {session.reason}"
            )

        # 6. Build registry
        registry = ToolRegistry(
            browser=page,
            db=tracker,
            llm_client=model_router,
            prompt_manager=prompt_manager,
        )
        registry.logger = run_logger

        # 7. Register tools
        tool_providers = config.get("llm", {}).get("tool_providers", {})
        register_w2_browser_tools(registry, page)
        register_w2_tools(registry, tracker, model_router, prompt_manager, tool_providers=tool_providers)

        # 8. Run pipeline
        pipeline = W2Pipeline(registry=registry, profile=profile, logger=run_logger)
        cfg_obj = W2Config(
            dry_run=dry_run,
            max_conversations=max_conversations,
            no_response_days=no_response_days,
            stale_conv_days=stale_conv_days,
            max_run_minutes=max_run_minutes,
            auto_send_adapted_resume=auto_send_adapted_resume,
        )
        summary = pipeline.run(cfg_obj)

    except Exception as exc:
        logger.exception("W2 pipeline failed: %s", exc)
        try:
            run_logger.close("failed")
        except Exception:
            pass
        raise
    finally:
        if page is not None:
            close_browser(page)

    # 9. Notify emitter that workflow finished
    if emitter is not None:
        try:
            emitter.finish_workflow("w2", str(summary), status="done")
        except Exception:
            pass

    return summary
