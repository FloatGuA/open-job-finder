# -*- coding: utf-8 -*-
"""意图分类 eval harness（阶段1）：拿人标金标集跑当前 analyze_hr_intent，出精度报告。

忠实复刻生产：`AnalyzeStep` 只用 `conv_id, messages, company` 调 `analyze_hr_intent`
（**不传 job_title**），内部取 messages[-5:]。本 harness 照此调用，故测的就是真实链路。

用法：
    cd code
    python scripts/eval/run_intent_eval.py            # 用 profile.yaml 当前注入配置
    python scripts/eval/run_intent_eval.py --baseline # 关掉 prompt 注入，作 A/B 对照

指标：总准确率 + 逐类 precision/recall/support + 混淆矩阵 + **高代价错误专项**
（漏判 resume_request=简历发不出；误判 rejection=放弃活线索；漏判 interview_invite）。
"""
import argparse
import io
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(CODE_DIR))

# Windows GBK 控制台会对中文 print 抛 UnicodeEncodeError——强制 stdout 走 UTF-8
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from services.config_manager import get_config_manager  # noqa: E402
from services.llm_client import build_model_router  # noqa: E402
from services.profile_loader import ProfileLoader  # noqa: E402
from services.prompt_manager import PromptManager  # noqa: E402
from services.tracker import ApplicationTracker  # noqa: E402
from tools.db.w2 import register_w2_tools  # noqa: E402
from tools.registry import ToolRegistry  # noqa: E402

VALID_INTENTS = ["interview_invite", "offer", "rejection", "resume_request",
                 "general_inquiry", "general_notice", "unknown"]
GOLDEN_PATH = CODE_DIR / "data" / "eval" / "intent_golden.jsonl"


def _load_golden():
    if not GOLDEN_PATH.exists():
        print(f"[错误] 金标文件不存在：{GOLDEN_PATH}\n先跑 export_intent_golden.py 导出并人工标注 human_intent。")
        raise SystemExit(2)
    labeled, unlabeled = [], 0
    for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        h = (row.get("human_intent") or "").strip()
        if not h:
            unlabeled += 1
            continue
        if h not in VALID_INTENTS:
            print(f"[警告] conv {row.get('conv_id')} 的 human_intent='{h}' 不在合法集，跳过")
            continue
        labeled.append(row)
    return labeled, unlabeled


def _build_registry(baseline: bool):
    config = get_config_manager().get_system_config()
    tracker = ApplicationTracker()
    model_router = build_model_router(config)
    profile = ProfileLoader(CODE_DIR / "data" / "profile.yaml").load()
    injection = {} if baseline else profile.prompt_injection
    pm = PromptManager(injection=injection)
    tool_providers = config.get("llm", {}).get("tool_providers", {})
    reg = ToolRegistry(browser=None, db=tracker, llm_client=model_router, prompt_manager=pm)
    register_w2_tools(reg, tracker, model_router, pm, tool_providers=tool_providers)
    return reg


def _predict(reg, row):
    res = reg.call(
        "analyze_hr_intent",
        conv_id=row.get("conv_id", ""),
        messages=row.get("messages", []),
        company=row.get("company", ""),
    )
    if not res.ok:
        return None, res.error
    return res.data.get("intent", "unknown"), None


def _report(pairs):
    """pairs: list[(human, pred)]。打印总精度 + 逐类 P/R + 混淆矩阵 + 高代价错误。"""
    n = len(pairs)
    correct = sum(1 for h, p in pairs if h == p)
    print(f"\n===== 意图分类 eval（n={n}）=====")
    print(f"总准确率 accuracy = {correct}/{n} = {correct / n:.1%}\n")

    labels = sorted(set([h for h, _ in pairs] + [p for _, p in pairs]),
                    key=lambda x: (VALID_INTENTS.index(x) if x in VALID_INTENTS else 99, x))
    # 混淆矩阵：conf[human][pred]
    conf = defaultdict(Counter)
    for h, p in pairs:
        conf[h][p] += 1

    # 逐类 precision/recall
    print("逐类指标（support=金标该类条数）：")
    print(f"  {'intent':<18}{'P':>7}{'R':>7}{'support':>9}")
    for lab in labels:
        tp = conf[lab][lab]
        pred_total = sum(conf[h][lab] for h in labels)   # 预测为 lab 的总数
        supp = sum(conf[lab].values())                    # 人标为 lab 的总数
        prec = tp / pred_total if pred_total else 0.0
        rec = tp / supp if supp else 0.0
        print(f"  {lab:<18}{prec:>7.1%}{rec:>7.1%}{supp:>9}")

    # 混淆矩阵
    print("\n混淆矩阵（行=人标 human，列=预测 pred）：")
    header = "human\\pred".ljust(18) + "".join(l[:10].rjust(11) for l in labels)
    print("  " + header)
    for h in labels:
        row = h.ljust(18) + "".join(str(conf[h][p]).rjust(11) for p in labels)
        print("  " + row)

    # 高代价错误专项
    print("\n===== 高代价错误专项 =====")
    missed_resume = [(h, p) for h, p in pairs if h == "resume_request" and p != "resume_request"]
    false_reject = [(h, p) for h, p in pairs if p == "rejection" and h != "rejection"]
    missed_interview = [(h, p) for h, p in pairs if h == "interview_invite" and p != "interview_invite"]
    print(f"漏判 resume_request（→简历发不出）: {len(missed_resume)}  预测成 {Counter(p for _, p in missed_resume) or '-'}")
    print(f"误判成 rejection（→放弃活线索）  : {len(false_reject)}  实为 {Counter(h for h, _ in false_reject) or '-'}")
    print(f"漏判 interview_invite            : {len(missed_interview)}  预测成 {Counter(p for _, p in missed_interview) or '-'}")


def main() -> int:
    ap = argparse.ArgumentParser(description="意图分类 eval harness")
    ap.add_argument("--baseline", action="store_true", help="关闭 prompt 注入（A/B 对照基线）")
    ap.add_argument("--limit", type=int, default=0, help="只跑前 N 条（0=全部）")
    args = ap.parse_args()

    labeled, unlabeled = _load_golden()
    if unlabeled:
        print(f"[提示] 金标里还有 {unlabeled} 行未填 human_intent，本次跳过；已标注 {len(labeled)} 行。")
    if not labeled:
        print("[错误] 没有已标注的行，无法评估。请先给 intent_golden.jsonl 填 human_intent。")
        return 2

    todo = labeled if args.limit <= 0 else labeled[: args.limit]
    mode = "baseline(无注入)" if args.baseline else "current(profile 注入)"
    print(f"[模式] {mode} | 评估 {len(todo)} 条")

    reg = _build_registry(args.baseline)

    pairs, errors = [], 0
    for i, row in enumerate(todo, 1):
        pred, err = _predict(reg, row)
        if err is not None:
            errors += 1
            print(f"  [{i}/{len(todo)}] conv {row.get('conv_id')} 调用失败：{err}")
            continue
        pairs.append((row["human_intent"], pred))
        if i % 10 == 0:
            print(f"  ...已跑 {i}/{len(todo)}")

    if errors:
        print(f"\n[提示] {errors} 条调用失败（LLM 未就绪？），未计入指标。")
    if not pairs:
        print("[错误] 无有效预测，无法出报告。")
        return 1
    _report(pairs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
