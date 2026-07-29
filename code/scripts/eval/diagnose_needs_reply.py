# -*- coding: utf-8 -*-
"""诊断：intent 分类错到什么程度、以及**needs_reply 层面**（真正的生产决策）对不对。

比 intent 准确率更贴近痛点——用户关心的是「要不要回复」，而 needs_reply = f(intent, 简历检测)。
本脚本重跑 analyze_hr_intent + detect_resume_request，模拟 AnalyzeStep 的 needs_reply 派生，
比对人标派生值，重点数「该不回却判要回」（误回=审批噪声）。全程只输出聚合，不 dump 原文。

用法：cd code && python scripts/eval/diagnose_needs_reply.py
"""
import io
import json
import sys
from collections import Counter
from pathlib import Path

CODE_DIR = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(CODE_DIR))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from services.config_manager import get_config_manager  # noqa: E402
from services.llm_client import build_model_router  # noqa: E402
from services.prompt_manager import PromptManager  # noqa: E402
from services.tracker import ApplicationTracker  # noqa: E402
from tools.db.w2 import register_w2_tools  # noqa: E402
from tools.llm.analyze_intent import default_needs_reply  # noqa: E402
from tools.registry import ToolRegistry  # noqa: E402

GOLDEN = CODE_DIR / "data" / "eval" / "intent_golden.jsonl"
_RESUME_TOKENS = ("简历", "resume", "附件", "[卡片]", "发我", "发一份", "发份")


def derive_needs_reply(intent: str, detect: dict) -> bool:
    """完全复刻 AnalyzeStep 的 needs_reply 派生。"""
    if intent == "resume_request":
        return not (detect.get("needs_resume") or detect.get("already_sent"))
    return default_needs_reply(intent)


def main() -> int:
    rows = [json.loads(l) for l in GOLDEN.read_text(encoding="utf-8").splitlines() if l.strip()]
    labeled = [r for r in rows if (r.get("human_intent") or "").strip()]

    config = get_config_manager().get_system_config()
    tracker = ApplicationTracker()
    router = build_model_router(config)
    pm = PromptManager()  # 诊断用无注入基线
    tp = config.get("llm", {}).get("tool_providers", {})
    reg = ToolRegistry(browser=None, db=tracker, llm_client=router, prompt_manager=pm)
    register_w2_tools(reg, tracker, router, pm, tool_providers=tp)

    intent_ok = nr_ok = 0
    false_reply = []      # 该不回却判要回（human_nr=False, pred_nr=True）
    missed_reply = []     # 该回却判不回
    notice_as_resume = 0  # general_notice 被判 resume_request
    notice_as_resume_with_ctx = 0  # ↑ 且线程含更早简历字眼 / already_sent
    already_sent_cnt = 0

    for i, r in enumerate(labeled, 1):
        msgs = r.get("messages", [])
        det = reg.call("detect_resume_request", messages=msgs)
        detect = det.data if det.ok else {}
        pred = reg.call("analyze_hr_intent", conv_id=r.get("conv_id", ""),
                        messages=msgs, company=r.get("company", ""))
        if not pred.ok:
            print(f"  [{i}] 调用失败: {pred.error}")
            continue
        pi = pred.data.get("intent", "unknown")
        hi = r["human_intent"]

        if detect.get("already_sent"):
            already_sent_cnt += 1
        if pi == hi:
            intent_ok += 1

        pred_nr = derive_needs_reply(pi, detect)
        human_nr = derive_needs_reply(hi, detect)
        if pred_nr == human_nr:
            nr_ok += 1
        elif human_nr is False and pred_nr is True:
            false_reply.append((hi, pi))
        elif human_nr is True and pred_nr is False:
            missed_reply.append((hi, pi))

        if hi == "general_notice" and pi == "resume_request":
            notice_as_resume += 1
            thread_has_resume = any(
                any(t in (m.get("text") or "") for t in _RESUME_TOKENS) for m in msgs
            )
            if thread_has_resume or detect.get("already_sent"):
                notice_as_resume_with_ctx += 1

        if i % 10 == 0:
            print(f"  ...{i}/{len(labeled)}")

    n = len(labeled)
    print(f"\n===== 诊断（n={n}）=====")
    print(f"intent 准确率     : {intent_ok}/{n} = {intent_ok/n:.1%}")
    print(f"needs_reply 准确率: {nr_ok}/{n} = {nr_ok/n:.1%}   ← 更贴近生产决策")
    print(f"简历已发(already_sent)的会话数: {already_sent_cnt}")

    print(f"\n【痛点】该不回却判要回（误回=审批噪声）: {len(false_reply)}")
    print(f"  按 (人标→预测) 分布: {dict(Counter(false_reply))}")
    print(f"【反向】该回却判不回（漏回）: {len(missed_reply)}")
    print(f"  按 (人标→预测) 分布: {dict(Counter(missed_reply))}")

    print(f"\n【假设验证】general_notice 被判 resume_request: {notice_as_resume}")
    print(f"  其中线程含更早简历字眼 或 already_sent=True: {notice_as_resume_with_ctx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
