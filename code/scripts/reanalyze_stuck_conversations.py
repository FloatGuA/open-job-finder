"""
离线重分析「在库但未分析」的 HR 会话。

存在理由：排查发现 924 条会话中有一批已落库、有 HR 消息，但 intent 为空、
从未起草回复——很可能是某次 W2 读了消息但 analyze 整批失败（LLM 超时），
之后又被 filter_conversations 判 no_change 永久跳过，卡死在空 intent。它们在
控制台上隐形（无 intent 徐章、不进待审批/待发送）。

本脚本直接读 DB 里已有的消息，复用与 W2 完全相同的 AnalyzeStep
（detect_resume → has_hr_message 守门 → analyze_hr_intent → generate_reply →
update_hr_analysis）重跑分析 + 起草回复，回填 intent。不开浏览器。
因为只选 intent 为空的目标，重跑天然幂等（已回填的不再命中）。

用法（在 code/ 目录下执行）：
  python scripts/reanalyze_stuck_conversations.py --dry-run
      只列出目标会话数量 + 样例，不调 LLM、不写库。
  python scripts/reanalyze_stuck_conversations.py [--limit N] [--min-hr N]
      真跑：重分析（写库）。--limit 限批量（0=全部），
      --min-hr 最少 HR 消息数（默认 1，滤掉零 HR 发言的）。

注意：真跑会写生产 DB（intent + 待审批草稿）。与 Dashboard 写锁共存时最好
在 W2 不在跑时执行（tracker 是 WAL + busy_timeout，并发写可能瞬时冲突）。
"""
import argparse
import sys
from pathlib import Path

# 脚本在 code/scripts/ 内，把 code/ 加入 import 路径
CODE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(CODE_DIR))

from pipeline.w2.steps.analyze import AnalyzeStep
from services.config_manager import get_config_manager
from services.llm_client import build_model_router
from services.prompt_manager import PromptManager
from services.tracker import ApplicationTracker
from tools.db.w2 import register_w2_tools
from tools.registry import ToolRegistry


def _select_targets(tracker, min_hr: int):
    """intent 为空 且 HR 消息数 >= min_hr 的会话。"""
    targets = []
    for conv in tracker.get_hr_conversations():
        if (conv.intent or "").strip():
            continue
        msgs = tracker.get_hr_messages(conv.conv_id)
        hr_cnt = sum(1 for m in msgs if m.get("sender") == "hr")
        if hr_cnt >= min_hr:
            targets.append((conv, msgs, hr_cnt))
    return targets


def main() -> int:
    ap = argparse.ArgumentParser(description="重分析卡死在空 intent 的 HR 会话")
    ap.add_argument("--dry-run", action="store_true", help="只列目标，不调 LLM、不写库")
    ap.add_argument("--limit", type=int, default=0, help="限处理条数（0=全部）")
    ap.add_argument("--min-hr", type=int, default=1, help="最少 HR 消息数（默认 1）")
    args = ap.parse_args()

    config = get_config_manager().get_system_config()
    tracker = ApplicationTracker()

    targets = _select_targets(tracker, args.min_hr)
    print(f"[scope] 空 intent + HR消息>={args.min_hr} 的会话：{len(targets)} 条")

    if args.dry_run:
        print("\n[dry-run] 样例（最多 20 条）：")
        for conv, msgs, hr_cnt in targets[:20]:
            last_hr = next((m["text"] for m in reversed(msgs) if m.get("sender") == "hr"), "")
            preview = (last_hr or "").replace("\n", " ")[:42]
            print(f"  {conv.company[:16]:<16} {conv.hr_name[:8]:<8} stage={conv.stage:<11} HR消息={hr_cnt}  最后HR: {preview}")
        print("\n[dry-run] 未调 LLM、未写库。去掉 --dry-run 真跑。")
        return 0

    # 真跑：装配与 W2 相同的 registry（无浏览器，只需 db+llm 工具）
    model_router = build_model_router(config)
    prompt_manager = PromptManager()
    tool_providers = config.get("llm", {}).get("tool_providers", {})
    registry = ToolRegistry(browser=None, db=tracker, llm_client=model_router, prompt_manager=prompt_manager)
    register_w2_tools(registry, tracker, model_router, prompt_manager, tool_providers=tool_providers)
    step = AnalyzeStep(registry)

    todo = targets if args.limit <= 0 else targets[: args.limit]
    print(f"[run] 处理 {len(todo)} 条（写库）…\n")

    intents: dict[str, int] = {}
    drafted = 0
    failed = 0
    for i, (conv, msgs, hr_cnt) in enumerate(todo, 1):
        try:
            out = step.run(conv, msgs)
        except Exception as exc:
            failed += 1
            print(f"  [{i}/{len(todo)}] ERROR {conv.company[:14]} / {conv.hr_name[:8]}: {exc}")
            continue
        intents[out.intent] = intents.get(out.intent, 0) + 1
        if out.needs_reply:
            drafted += 1
        flag = "→起草" if out.needs_reply else ""
        print(f"  [{i}/{len(todo)}] {conv.company[:14]:<14} {conv.hr_name[:8]:<8} intent={out.intent:<16} {out.status.value} {flag}")

    print("\n[summary]")
    print(f"  处理: {len(todo)}  失败: {failed}  起草回复(待审批): {drafted}")
    print(f"  intent 分布: " + ", ".join(f"{k}:{v}" for k, v in sorted(intents.items(), key=lambda x: -x[1])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
