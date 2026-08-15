"""信息池的「变更提案 → 人工勾选 → 落盘」。

**为什么需要它**：信息池是关于求职者的全部信息的唯一主库，而机器有两条路径会改它：

  - `merge_parsed`（上传简历解析）——只增改不删，相对安全；
  - `build_pool`（LLM 把自我描述融进池）——**让模型整体重写 sections，会丢内容**。

原本的防线只有"写盘前自动快照 + 事后手动回滚"。那是**事后补救**：内容已经被覆盖，
你得先发现丢了东西、再去翻快照。用户 2026-08-15 要求改成事前把关——每次更新出一份
diff，哪些块改了、改在哪、新增了什么，勾选决定接受哪些。跟 Checkpoint 1、golden set
是同一条原则：**机器提议，人拍板**。

**边界**：人在池编辑页直接改内容**不走**这里（`PUT /api/resume/pool`）——那时人就是
作者，给自己的编辑出 diff 让自己确认是纯仪式。只有机器产生的变更才需要确认。

块的身份 = `(分区名, 块标题)`，跟 `merge_parsed` 的匹配规则一致。没有标题的块匹配不上，
一律算新增（`merge_parsed` 也是这么做的）。
"""
import difflib
import os
import time
from typing import Optional

import yaml

# 池路径的唯一定义在 info_pool，这里引用而不是再写一个字面量——同一个路径两处各写
# 一份，改一处漏一处就会出现"提案存到了别的目录"这种查半天的问题。
from services.info_pool import POOL_PATH

# 块里参与比较的字段。`style` 是排版（粗体/斜体），不是信息，改了不值得让人确认。
_BLOCK_FIELDS = ("time", "summary", "bullets")

# 默认勾选策略：
#   added   —— 默认选中。新信息通常是想要的，一条条勾太累。
#   changed —— 默认不选。它会**覆盖**已有内容，是这里最该被看一眼的东西。
#   removed —— 默认不选。绝不静默删除；要删得你明确点。
_DEFAULT_ACCEPT = {"added": True, "changed": False, "removed": False}


def _norm_bullets(v) -> list:
    if isinstance(v, list):
        return [str(x) for x in v]
    return [str(v)] if v else []


def _bullet_lines(old: list, new: list) -> list:
    """逐条的增删对照，形状仿 GitHub：{op: ' '|'-'|'+', text}。

    用 difflib 而不是"整块前后对照"：要点通常只动一两条，整块红绿会让人看不出改了啥。
    """
    out = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=old, b=new).get_opcodes():
        if tag == "equal":
            out += [{"op": " ", "text": t} for t in old[i1:i2]]
        else:
            out += [{"op": "-", "text": t} for t in old[i1:i2]]
            out += [{"op": "+", "text": t} for t in new[j1:j2]]
    return out


def _diff_block(old: Optional[dict], new: Optional[dict]) -> Optional[dict]:
    """一个块的变更。没有实质变化返回 None（不进 diff，免得刷屏）。"""
    if old is None and new is None:
        return None
    if old is None:
        return {"kind": "added", "title": new.get("title", ""), "new": new,
                "fields": [], "bullets": _bullet_lines([], _norm_bullets(new.get("bullets")))}
    if new is None:
        return {"kind": "removed", "title": old.get("title", ""), "old": old,
                "fields": [], "bullets": _bullet_lines(_norm_bullets(old.get("bullets")), [])}

    fields = []
    for f in _BLOCK_FIELDS:
        if f == "bullets":
            continue
        o, n = str(old.get(f) or ""), str(new.get(f) or "")
        if o != n:
            fields.append({"field": f, "old": o, "new": n})
    ob, nb = _norm_bullets(old.get("bullets")), _norm_bullets(new.get("bullets"))
    bullets = _bullet_lines(ob, nb) if ob != nb else []
    if not fields and not bullets:
        return None
    return {"kind": "changed", "title": new.get("title", ""), "old": old, "new": new,
            "fields": fields, "bullets": bullets}


def block_key(section_name: str, title: str) -> str:
    """块在勾选表里的唯一标识。分区名和标题都可能含 `/`，所以用不太可能出现的分隔符。"""
    return f"{section_name}␟{title}"


def diff_pools(current: dict, proposed: dict) -> dict:
    """算出「当前池」到「提案」的差异，形状给前端直接渲染。

    只列有变化的东西：没动过的块不出现——一份 5 个分区十几个块的池，全列出来
    人根本找不到改了哪里。
    """
    cur_basic = current.get("basic_info") or {}
    new_basic = proposed.get("basic_info") or {}
    basic = []
    for k, v in new_basic.items():
        nv = str(v or "")
        ov = str(cur_basic.get(k) or "")
        if not nv or nv == ov:
            continue
        basic.append({"key": k, "kind": "changed" if ov else "added", "old": ov, "new": nv})

    cur_secs = {s["name"]: s for s in (current.get("sections") or [])}
    new_secs = {s["name"]: s for s in (proposed.get("sections") or [])}

    sections = []
    for name in list(new_secs) + [n for n in cur_secs if n not in new_secs]:
        cur_blocks = {b.get("title", ""): b for b in (cur_secs.get(name, {}).get("blocks") or [])}
        new_blocks = {b.get("title", ""): b for b in (new_secs.get(name, {}).get("blocks") or [])}

        entries = []
        for title in list(new_blocks) + [t for t in cur_blocks if t not in new_blocks]:
            d = _diff_block(cur_blocks.get(title), new_blocks.get(title))
            if d is None:
                continue
            d["key"] = block_key(name, title)
            d["accept_default"] = _DEFAULT_ACCEPT[d["kind"]]
            entries.append(d)
        if entries:
            sections.append({"name": name, "kind": "added" if name not in cur_secs else "existing",
                             "blocks": entries})

    return {
        "basic_info": [dict(b, key=f"basic_info␟{b['key']}",
                            accept_default=_DEFAULT_ACCEPT[b["kind"]]) for b in basic],
        "sections": sections,
        "has_changes": bool(basic or sections),
    }


def apply_selection(current: dict, proposed: dict, accepted_keys) -> dict:
    """按勾选把提案的一部分落到池上，返回新池。**没勾的一律保持现状。**

    刻意从 `current` 出发逐项打补丁，而不是从 `proposed` 出发删掉没勾的：后者会让
    "提案里根本没提到的内容"（LLM 重写时漏掉的块）悄悄消失——那正是 build_pool
    最危险的地方，也是做这套确认的起因。
    """
    accepted = set(accepted_keys or [])
    out = {
        "basic_info": dict(current.get("basic_info") or {}),
        "self_description": proposed.get("self_description", current.get("self_description", "")),
        "sections": [
            {"name": s["name"], "blocks": [dict(b) for b in (s.get("blocks") or [])]}
            for s in (current.get("sections") or [])
        ],
    }

    new_basic = proposed.get("basic_info") or {}
    for k, v in new_basic.items():
        if f"basic_info␟{k}" in accepted and str(v or ""):
            out["basic_info"][k] = v

    by_name = {s["name"]: s for s in out["sections"]}
    new_secs = {s["name"]: s for s in (proposed.get("sections") or [])}

    for name, sec in new_secs.items():
        for blk in sec.get("blocks") or []:
            title = blk.get("title", "")
            if block_key(name, title) not in accepted:
                continue
            target = by_name.get(name)
            if target is None:
                target = {"name": name, "blocks": []}
                out["sections"].append(target)
                by_name[name] = target
            idx = next((i for i, b in enumerate(target["blocks"]) if b.get("title", "") == title), None)
            if idx is None:
                target["blocks"].append(dict(blk))
            else:
                target["blocks"][idx] = dict(blk)

    # 删除：提案里没有、当前有，且人**明确勾了**的块。
    #
    # 默认保留靠的是"没勾就不删"，不是靠跳过某些分区。这里原先有一句
    # `if name not in new_secs: continue`（提案完全没提这个分区就整个跳过），
    # 结果是 diff 把那些块显示成「删除」并给了勾选框、勾了却没反应——
    # **UI 摆一个点了没用的框比不摆更糟**（2026-08-15 用真实池数据跑出来才发现）。
    for name, sec in list(by_name.items()):
        proposed_titles = {b.get("title", "") for b in (new_secs.get(name, {}).get("blocks") or [])}
        sec["blocks"] = [
            b for b in sec["blocks"]
            if b.get("title", "") in proposed_titles
            or block_key(name, b.get("title", "")) not in accepted
        ]
    out["sections"] = [s for s in out["sections"] if s["blocks"]]
    return out


# ── 待确认提案的存放 ──────────────────────────────────────────────────────────
#
# 落文件而不是放进进程内存：解析一份简历要几十秒，人未必当场就决定；重启后端
# （改代码、--reload、崩溃）不该让一份待确认的提案凭空消失，否则人只会学会
# "别管它，反正会没"。跟池同目录，一眼看得出是它的附属物。

def pending_path(pool_path: str = POOL_PATH) -> str:
    return os.path.join(os.path.dirname(pool_path) or "data", "pool_pending.yaml")


def save_pending(proposed: dict, source: str, pool_path: str = POOL_PATH) -> dict:
    """存一份待确认提案，覆盖上一份。

    **同一时刻只允许有一份**：两份并存的话，先确认哪一份会算出不同结果（第二份的
    diff 是相对旧池算的），而人看不出这种顺序依赖。新提案来了就顶掉旧的，简单且可预期。
    """
    rec = {"source": source, "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
           "proposed": proposed}
    p = pending_path(pool_path)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        yaml.safe_dump(rec, f, allow_unicode=True, sort_keys=False)
    return rec


def load_pending(pool_path: str = POOL_PATH) -> Optional[dict]:
    p = pending_path(pool_path)
    if not os.path.exists(p):
        return None
    with open(p, "r", encoding="utf-8") as f:
        rec = yaml.safe_load(f) or {}
    return rec if rec.get("proposed") else None


def clear_pending(pool_path: str = POOL_PATH) -> None:
    p = pending_path(pool_path)
    if os.path.exists(p):
        os.remove(p)
