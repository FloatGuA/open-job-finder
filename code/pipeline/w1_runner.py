"""
W1 runner: assemble ToolRegistry, register W1 tools, and run W1Pipeline.

Entry point for both main.py (--once / --dry-run) and dashboard/server.py
(_run_apply_workflow).
"""
import logging
from pathlib import Path
from typing import Optional

from pipeline.common.verify_session import VerifySessionStep
from pipeline.run_logger import RunLogger
from pipeline.w1.pipeline import W1Config, W1Pipeline
from services.boss_search_url import build_search_url
from services.browser_context import close_browser, open_browser
from services.profile_loader import ProfileLoader
from services.prompt_manager import PromptManager
from tools.browser.w1 import register_w1_browser_tools
from tools.db.w1 import register_w1_tools
from tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def run_w1(
    config: dict,
    tracker,
    model_router,
    emitter=None,
    dry_run: bool = False,
    score_threshold: int = 72,
    max_cards: Optional[int] = None,
    search_url: Optional[str] = None,
    headless: bool = True,
    debug: bool = False,
    data_dir: Optional[Path] = None,
    trigger: str = "manual",
) -> dict:
    """Run the W1 (apply) pipeline end-to-end.

    Args:
        config: raw config dict (from config.yaml).
        tracker: ApplicationTracker instance.
        model_router: ModelRouter instance for LLM calls.
        emitter: optional ProgressEmitter for SSE push.
        dry_run: if True, skip actual apply actions.
        score_threshold: minimum score to consider applying.
        max_cards: cap on number of job cards to process (None = unlimited).
        search_url: prebuilt Boss search URL; built from profile if omitted.
        headless: run browser in headless mode.
        debug: if True, emit SSE events for individual tool calls.
        data_dir: path to the data/ directory; auto-detected if None.

    Returns:
        summary dict from W1Pipeline.run().
    """
    if data_dir is None:
        data_dir = Path(__file__).resolve().parent.parent / "data"

    # 1. Load profile (fail fast: a load failure here used to `return {"error":...}`
    #    silently, which the queue runner then recorded as a SUCCESS and — because the
    #    early return skips start/finish_workflow — never released the browser mutex,
    #    wedging the queue. Let it raise so run_item's except path logs + clears the lock.)
    profile = ProfileLoader(data_dir / "profile.yaml").load()

    # 2. Build prompt manager
    prompt_manager = PromptManager()

    # 4. Build search URL if not provided
    if not search_url:
        profile_dict = vars(profile)
        keyword = profile.keywords[0] if profile.keywords else None
        city = profile.cities[0] if profile.cities else None
        search_url = build_search_url(profile_dict, keyword=keyword, city=city)

    # 5. Notify emitter that workflow is starting. run_meta = who launched it + the run
    # knobs, surfaced in the live-panel title and persisted to the run log's run_start.
    run_meta = {
        "trigger": trigger,
        "params": {
            "score_threshold": score_threshold,
            "max_cards": max_cards,
            "dry_run": dry_run,
            "headless": headless,
        },
    }
    if emitter is not None:
        try:
            emitter.start_workflow("w1", meta=run_meta)
        except Exception:
            pass

    page = None
    run_logger = RunLogger(pipeline="w1", emitter=emitter, debug=debug, meta=run_meta)

    try:
        # 6. Open browser
        page = open_browser(data_dir, headless=headless)

        # 6b. Verify session before doing anything
        session = VerifySessionStep(page).run()
        if session.status != session.status.SUCCESSFUL:
            if session.error == "session_expired":
                raise RuntimeError(f"Boss session expired — please re-login: {session.reason}")
            # Not a confirmed logout (browser/page hiccup): say so instead of the
            # misleading "session invalid", which sent us chasing a non-existent re-login.
            raise RuntimeError(
                f"session verify failed (browser/page error, not necessarily logged out): {session.reason}"
            )

        # 7. Build registry
        registry = ToolRegistry(
            browser=page,
            db=tracker,
            llm_client=model_router,
            prompt_manager=prompt_manager,
        )
        registry.logger = run_logger

        # 8. Register tools
        tool_providers = config.get("llm", {}).get("tool_providers", {})
        register_w1_browser_tools(registry, page)
        register_w1_tools(registry, tracker, model_router, prompt_manager, tool_providers=tool_providers)

        # 9. Run pipeline
        pipeline = W1Pipeline(registry=registry, profile=profile, logger=run_logger)
        cfg_obj = W1Config(
            url=search_url,
            score_threshold=score_threshold,
            dry_run=dry_run,
            max_cards=max_cards,
        )
        summary = pipeline.run(cfg_obj)

    except Exception as exc:
        logger.exception("W1 pipeline failed: %s", exc)
        try:
            run_logger.close("failed")
        except Exception:
            pass
        raise
    finally:
        if page is not None:
            close_browser(page)

    # 10. Notify emitter that workflow finished
    if emitter is not None:
        try:
            emitter.finish_workflow("w1", str(summary), status="done")
        except Exception:
            pass

    return summary
