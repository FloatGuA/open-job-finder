# -*- coding: utf-8 -*-
"""导出「意图分类金标集」待标注文件（阶段1 eval 第一步）。

从 jobs.db 里**有真实 HR 消息**的会话中分层抽样，写出一份 JSONL 待用户人工标注。
- 分层依据是**当前已存库的 intent（模型历史判断）**——这是 bootstrap 采样的无奈之举
  （还没有人标，只能按模型视角分层）；**membership 以人标为准**，采样只保证各类都有样本、
  且对稀有/高代价类（resume_request/rejection/interview_invite/offer）过采，抵消 general 的
  近 50% 基率。
- 每行含 model_intent（模型历史判断，仅作标注**建议**，绝非 ground truth）与 human_intent（待填）。
- ⚠️ 输出落在 code/data/eval/（整目录 gitignore）——含真实公司/HR/消息 = PII，**绝不进 git**。

用法：
    cd code && python scripts/eval/export_intent_golden.py [--per-class N] [--seed S]
标注：打开 data/eval/intent_golden.jsonl，给每行填 human_intent（六选一），存盘。
校验/统计：python scripts/eval/run_intent_eval.py（读已填 human_intent 的行）。
"""
import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(CODE_DIR))

from services.tracker import ApplicationTracker  # noqa: E402

VALID_INTENTS = ["interview_invite", "offer", "rejection", "resume_request",
                 "general_inquiry", "general_notice", "unknown"]

# 稀有/高代价类过采上限（相对 general）。offer 极稀有——全取。
PER_CLASS_CAP = {
    "resume_request": 15,
    "interview_invite": 12,
    "rejection": 12,
    "general": 15,
    "unknown": 6,
    "offer": 100,  # 实际全库仅 1 条，全取
}

OUT_PATH = CODE_DIR / "data" / "eval" / "intent_golden.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser(description="导出意图分类金标待标注集")
    ap.add_argument("--seed", type=int, default=42, help="抽样随机种子（可复现）")
    ap.add_argument("--min-hr", type=int, default=1, help="最少真实 HR 消息数")
    args = ap.parse_args()
    random.seed(args.seed)

    tracker = ApplicationTracker()

    # 收集有 >=min_hr 条真实 HR 消息的会话，按已存 intent 分组
    by_intent = defaultdict(list)
    for conv in tracker.get_hr_conversations():
        msgs = tracker.get_hr_messages(conv.conv_id)
        hr_cnt = sum(1 for m in msgs if m.get("sender") == "hr")
        if hr_cnt < args.min_hr:
            continue
        stored = (conv.intent or "unknown").strip() or "unknown"
        by_intent[stored].append((conv, msgs))

    # 分层抽样
    rows = []
    picked = Counter()
    for intent, items in by_intent.items():
        cap = PER_CLASS_CAP.get(intent, 8)  # 未知历史脏值（greeting/info_request…）也取几条暴露
        random.shuffle(items)
        for conv, msgs in items[:cap]:
            rows.append({
                # human_intent 放最前，方便标注时一眼定位、快速填
                "human_intent": "",
                "model_intent": intent,          # 模型历史判断（仅建议）
                "conv_id": conv.conv_id,
                "company": conv.company or "",
                "messages": [
                    {"sender": m.get("sender", ""), "text": m.get("text", "")}
                    for m in msgs
                ],
            })
            picked[intent] += 1

    random.shuffle(rows)  # 打乱，避免标注时按类扎堆产生锚定偏差

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"[导出] {len(rows)} 条 → {OUT_PATH}")
    print(f"[分层] 采样自各历史 intent：{dict(picked)}")
    print(f"[合法标签] {VALID_INTENTS}")
    print("[下一步] 打开该 JSONL，逐行填 human_intent（六选一），存盘后跑 run_intent_eval.py")
    print("[⚠️PII] 该文件含真实会话内容，位于 gitignore 的 data/ 下——切勿提交或外发")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
