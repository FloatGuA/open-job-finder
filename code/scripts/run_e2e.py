"""
E2E 手动验证运行脚本。

存在理由：main.py 的 CLI 不支持有头模式、不支持限制规模(max_cards)，
且 --once 会在 Dashboard 运行时把任务委托给 server。本脚本直接调用
run_w1 / run_w2，强制有头(headless=False) + 可限规模，便于人工核对业务正确性。
不修改任何主代码。

用法（在 code/ 目录下执行）：
  python scripts/run_e2e.py verify [--wait N]
      用 VerifySessionStep 确认登录态(有头)。未登录时 --wait N 保持窗口 N 秒供扫码。
  python scripts/run_e2e.py w1 [--max-cards N] [--score-threshold N]
      真实投递(dry_run=False)，默认只处理 3 张卡、分数线 60。
  python scripts/run_e2e.py w2 [--no-response-days N] [--stale-conv-days N]
      真实处理 HR 会话(dry_run=False)。
"""
import argparse
import sys
import time
from pathlib import Path

# 脚本在 code/scripts/ 内，把 code/ 加入 import 路径
CODE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE_DIR))

from services.config_manager import get_config_manager
from services.llm_client import build_model_router
from services.tracker import ApplicationTracker


def _data_dir() -> Path:
    return CODE_DIR / "data"


def cmd_verify(args) -> int:
    from services.browser_context import open_browser, close_browser
    from pipeline.common.verify_session import VerifySessionStep
    from pipeline.base import StepStatus

    page = open_browser(_data_dir(), headless=False)
    try:
        out = VerifySessionStep(page).run()
        if out.status == StepStatus.SUCCESSFUL:
            print(f"[verify] LOGGED IN as: {out.username!r}")
            return 0
        print(f"[verify] NOT logged in: {out.reason} (error={out.error})")
        if args.wait > 0:
            print(
                f"[verify] keeping browser open {args.wait}s — "
                f"scan QR / login in the window; session persists to browser_profile."
            )
            time.sleep(args.wait)
            out2 = VerifySessionStep(page).run()
            if out2.status == StepStatus.SUCCESSFUL:
                print(f"[verify] login OK after wait: {out2.username!r}")
                return 0
            print(f"[verify] still not logged in: {out2.reason}")
        return 1
    finally:
        close_browser(page)


def cmd_w1(args) -> int:
    from pipeline.w1_runner import run_w1

    config = get_config_manager().get_system_config()
    tracker = ApplicationTracker()
    model_router = build_model_router(config)
    summary = run_w1(
        config=config,
        tracker=tracker,
        model_router=model_router,
        dry_run=False,
        score_threshold=args.score_threshold,
        max_cards=args.max_cards,
        search_url=getattr(args, "search_url", None) or None,
        headless=False,
        debug=True,
        trigger="cli",
    )
    print(f"\n[w1] summary: {summary}")
    return 0


def cmd_w2(args) -> int:
    from pipeline.w2_runner import run_w2

    config = get_config_manager().get_system_config()
    tracker = ApplicationTracker()
    model_router = build_model_router(config)
    summary = run_w2(
        config=config,
        tracker=tracker,
        model_router=model_router,
        dry_run=args.dry_run,
        max_conversations=args.max_conversations,
        no_response_days=args.no_response_days,
        stale_conv_days=args.stale_conv_days,
        headless=False,
        debug=True,
        trigger="cli",
    )
    print(f"\n[w2] summary: {summary}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenJobFinder E2E manual verification")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_verify = sub.add_parser("verify", help="confirm login via VerifySessionStep (headed)")
    p_verify.add_argument("--wait", type=int, default=0, help="seconds to keep window open for QR login if not logged in")

    p_w1 = sub.add_parser("w1", help="run W1 apply pipeline (real apply, headed)")
    p_w1.add_argument("--max-cards", type=int, default=3)
    p_w1.add_argument("--score-threshold", type=int, default=60)
    p_w1.add_argument("--search-url", type=str, default=None, help="override Boss search URL (else built from profile)")

    p_w2 = sub.add_parser("w2", help="run W2 check-responses pipeline (headed)")
    p_w2.add_argument("--dry-run", action="store_true", help="不真发简历/回复，只跑 scan/read/analyze/落库")
    p_w2.add_argument("--max-conversations", type=int, default=200)
    p_w2.add_argument("--no-response-days", type=int, default=14)
    p_w2.add_argument("--stale-conv-days", type=int, default=30)

    args = parser.parse_args()
    if args.cmd == "verify":
        sys.exit(cmd_verify(args))
    elif args.cmd == "w1":
        sys.exit(cmd_w1(args))
    elif args.cmd == "w2":
        sys.exit(cmd_w2(args))


if __name__ == "__main__":
    main()
