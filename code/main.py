#!/usr/bin/env python3
"""
OpenJobFinder - Main entry point.
Usage:
  python main.py                # Start scheduler (default)
  python main.py --once         # Run one apply cycle immediately
  python main.py --check        # Check responses only
  python main.py --chat         # Start conversational agent
  python main.py --onboarding   # Run onboarding setup
  python main.py --dry-run      # Run once in dry-run mode
"""

import argparse

from services.config_manager import get_config_manager
from services.llm_client import build_model_router
from services.logger import get_orchestrator_logger
from services.onboarding import OnboardingChecker


def _try_delegate_to_server(action: str, dry_run: bool = False) -> bool:
    """If the Dashboard server is running, delegate the workflow to it via HTTP.

    Returns True if delegation succeeded (caller should exit), False if server
    is not reachable (caller should run directly).
    """
    import urllib.request
    import urllib.error
    import json

    base = "http://localhost:8765"
    try:
        urllib.request.urlopen(f"{base}/api/workflow/status", timeout=2)
    except (urllib.error.URLError, OSError):
        return False  # server not running, fall through to direct execution

    endpoint = f"{base}/api/workflow/{action}"
    payload = json.dumps({"dry_run": dry_run}).encode()
    req = urllib.request.Request(endpoint, data=payload,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read())
        print(f"Delegated to Dashboard server → {result}")
        print("Monitor progress at http://localhost:8765")
        return True
    except Exception as exc:
        print(f"Server delegation failed ({exc}), running directly.")
        return False


def main():
    parser = argparse.ArgumentParser(description="OpenJobFinder")
    parser.add_argument("--once", action="store_true", help="Run one apply cycle")
    parser.add_argument("--check", action="store_true", help="Check responses only")
    parser.add_argument("--onboarding", action="store_true", help="Run onboarding setup")
    parser.add_argument("--setup-profile", action="store_true", help="Configure job search preferences")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    parser.add_argument("--chat", action="store_true", help="Start conversational agent (temporarily unavailable)")
    parser.add_argument("--debug", action="store_true", help="Enable tool-level SSE events")
    args = parser.parse_args()

    logger = get_orchestrator_logger()
    config = get_config_manager().get_system_config()

    checker = OnboardingChecker(config=config)
    status = checker.check_all()

    # CLI onboarding/login is retired — the Dashboard (BrowserSession + VerifySessionStep)
    # owns login now. Previously a missing session sent us into run_interactive_setup,
    # whose _step3_login_boss raises unconditionally: a dead end. Point users to the
    # Dashboard instead of pretending the CLI can still log in.
    _DASH_HINT = (
        "请启动 Dashboard 后在「设置 → 环境&Session」完成登录与配置：\n"
        "  python -m uvicorn dashboard.server:app --host 0.0.0.0 --port 8765 --reload"
    )
    if args.onboarding:
        print("CLI onboarding 已退役。" + _DASH_HINT)
        return
    if not status["session"]:
        print("未检测到有效 Boss session。CLI 不再负责登录——" + _DASH_HINT)
        return

    if args.setup_profile:
        checker.run_setup_profile()
        return

    if args.chat:
        print("--chat mode is temporarily unavailable (pending migration to new pipeline architecture).")
        return

    from pathlib import Path

    from pipeline.w1_runner import run_w1
    from pipeline.w2_runner import run_w2
    from services.settings_resolver import resolve_params
    from services.tracker import ApplicationTracker

    tracker = ApplicationTracker()
    model_router = build_model_router(config)
    data_dir = Path(__file__).resolve().parent / "data"

    if args.once or args.dry_run:
        overrides = {"dry_run": True} if args.dry_run else {}
        p = resolve_params("w1", overrides, config, data_dir)
        dry_run = bool(p.get("dry_run", False))
        if _try_delegate_to_server("apply", dry_run=dry_run):
            return
        summary = run_w1(
            config=config,
            tracker=tracker,
            model_router=model_router,
            dry_run=dry_run,
            score_threshold=int(p.get("score_threshold", 60)),
            max_cards=(int(p["max_cards"]) if p.get("max_cards") else None),
            headless=bool(p.get("headless", True)),
            debug=args.debug,
            data_dir=data_dir,
            trigger="cli",
        )
        print(f"\nRun complete: {summary}")
    elif args.check:
        if _try_delegate_to_server("check"):
            return
        p = resolve_params("w2", {}, config, data_dir)
        summary = run_w2(
            config=config,
            tracker=tracker,
            model_router=model_router,
            dry_run=bool(p.get("dry_run", False)),
            max_conversations=int(p.get("max_conversations", 200)),
            no_response_days=int(p.get("no_response_days", 14)),
            stale_conv_days=int(p.get("stale_conv_days", 30)),
            headless=bool(p.get("headless", True)),
            debug=args.debug,
            data_dir=data_dir,
            trigger="cli",
        )
        print(f"\nCheck complete: {summary}")
    else:
        print("Scheduler mode not yet available in new pipeline. Use --once or --check.")


if __name__ == "__main__":
    main()
