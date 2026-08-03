"""按岗位挑简历（v2.18）：Agent 只做「投这个岗该发哪一份」的选择题。

产品边界（用户 2026-08-03 定）：简历**内容**由用户自己掌控，Agent 不替用户写；
这里只在用户已经存好的几份里选一份，选不出就用当前激活份兜底——**永不新建、
永不改内容**。

选法（code decides，确定性规则，不调 LLM）：
- 每份简历有「目标岗位」(target)，按空白/顿号/斜杠等切成关键词
- 拿岗位标题 + JD 文本做包含匹配，命中词越多分越高；标题命中权重高于 JD
- 平分时取更新时间较新的那份；一个都不中 → 当前激活份，matched=False
不用 LLM 是有意的：这是可解释、可预期的路由决策，用户能一眼看懂为什么选了这份
（"models judge / code decides" 原则）。
"""
import re
from typing import Optional

_SPLIT = re.compile(r"[\s,，、/|｜;；]+")

TITLE_WEIGHT = 3        # 岗位标题命中：强信号
JD_WEIGHT = 1           # JD 正文命中：弱信号（JD 里什么词都可能出现）


def _keywords(target: str) -> list:
    return [w.strip().lower() for w in _SPLIT.split(target or "") if len(w.strip()) >= 2]


def pick_resume(items: list, active_slug: str, job_title: str = "", jd_text: str = "") -> dict:
    """从简历列表里挑一份最合适的。

    items: [{slug, name, target, updated_at}]（ResumeStore.list()['items']）
    返回 {slug, name, matched, score, hit_keywords, reason}
    """
    title_l = (job_title or "").lower()
    jd_l = (jd_text or "")[:2000].lower()

    best = None
    for it in items:
        kws = _keywords(it.get("target", ""))
        if not kws:
            continue
        hits, score = [], 0
        for kw in kws:
            if kw in title_l:
                score += TITLE_WEIGHT
                hits.append(kw)
            elif kw in jd_l:
                score += JD_WEIGHT
                hits.append(kw)
        if score <= 0:
            continue
        # 同分取更新时间新的那份（用户最近在维护的更可能是想用的）
        key = (score, it.get("updated_at", ""))
        if best is None or key > best[0]:
            best = (key, it, hits)

    if best is not None:
        _, it, hits = best
        return {
            "slug": it["slug"], "name": it.get("name", ""), "matched": True,
            "score": best[0][0], "hit_keywords": hits,
            "reason": f"目标岗位命中 {'/'.join(hits)}",
        }

    fallback = next((i for i in items if i["slug"] == active_slug), None) or (items[0] if items else None)
    if fallback is None:
        return {"slug": "", "name": "", "matched": False, "score": 0, "hit_keywords": [], "reason": "没有任何简历"}
    return {
        "slug": fallback["slug"], "name": fallback.get("name", ""), "matched": False,
        "score": 0, "hit_keywords": [],
        "reason": "没有简历的目标岗位与之匹配，用当前编辑的这份兜底",
    }


def pick_for_job(store, job_title: str = "", jd_text: str = "") -> dict:
    """便捷入口：从 ResumeStore 读列表再挑。"""
    idx = store.list()
    return pick_resume(idx.get("items") or [], idx.get("active") or "", job_title, jd_text)
