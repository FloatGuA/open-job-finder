"""信息池（v2.16）：关于求职者的全部信息的主库，高于任何一份简历。

- 存 data/info_pool.yaml，形状与简历文档相同（basic_info + self_description + sections），
  分区名自定义（如「游戏经历」「Agent 经历」）。
- 上传简历解析 → merge_parsed 合并入池（同名分区并组、同标题块替换、新块追加）。
- 简历 = 从池中挑块的**复制**组合（每份独立，改简历不回写池）。
- 首次使用自动迁移：把当前激活简历的内容收编为池的初始内容。
"""
import os
import shutil
import time

from services import resume_blocks as rb

POOL_PATH = "data/info_pool.yaml"
SNAPSHOT_KEEP = 20          # 快照滚动上限


def _snapshot_dir(path: str) -> str:
    return os.path.join(os.path.dirname(path) or ".", "pool_snapshots")


def load_pool(path: str = POOL_PATH, active_resume_path: str = "data/resume_blocks.yaml") -> dict:
    """读池；不存在则从激活简历迁移初始化（简历也没有就给空结构）。"""
    if os.path.exists(path):
        return rb.load_blocks(path)
    pool = rb.load_blocks(active_resume_path)  # 空文件时本身就是空结构
    rb.save_blocks(pool, path)
    return pool


def save_pool(pool: dict, path: str = POOL_PATH) -> None:
    """写池；**覆盖前先把旧内容存一份快照**。

    池是「关于求职者的全部信息」的唯一主库，而 build_pool 让 LLM 整体重写 sections
    （可能丢内容），一次错误保存就不可逆。故每次写盘前留档，可回滚。
    """
    snapshot_pool(path)
    rb.save_blocks(pool, path)


def snapshot_pool(path: str = POOL_PATH) -> str:
    """把当前池文件复制一份到 pool_snapshots/{时间戳}.yaml；文件不存在则跳过。"""
    if not os.path.exists(path):
        return ""
    d = _snapshot_dir(path)
    os.makedirs(d, exist_ok=True)
    base = time.strftime("%Y%m%d_%H%M%S")
    # 同一秒内多次保存也各留一档（加序号）——否则快速连续保存会丢中间状态。
    # 序号在后，倒序排列时 _1 排在无序号之前，正好等于"更晚创建的更靠前"。
    dest = os.path.join(d, f"{base}.yaml")
    n = 0
    while os.path.exists(dest):
        n += 1
        dest = os.path.join(d, f"{base}_{n}.yaml")
    shutil.copy2(path, dest)
    _prune_snapshots(d)
    return dest


def list_snapshots(path: str = POOL_PATH) -> list:
    """快照列表（新→旧）。"""
    d = _snapshot_dir(path)
    if not os.path.isdir(d):
        return []
    out = []
    for fn in sorted(os.listdir(d), reverse=True):
        if not fn.endswith(".yaml"):
            continue
        p = os.path.join(d, fn)
        doc = rb.load_blocks(p)
        out.append({
            "file": fn,
            "saved_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(p))),
            "blocks": sum(len(s["blocks"]) for s in doc["sections"]),
            "sections": len(doc["sections"]),
        })
    return out


def restore_snapshot(fname: str, path: str = POOL_PATH) -> dict:
    """回滚到某个快照（回滚本身也会先给当前内容留档，防误回滚）。"""
    if "/" in fname or "\\" in fname or ".." in fname:
        raise ValueError(f"非法快照名: {fname}")
    src = os.path.join(_snapshot_dir(path), fname)
    if not os.path.isfile(src):
        raise FileNotFoundError(fname)
    doc = rb.load_blocks(src)
    save_pool(doc, path)        # 走 save_pool → 当前内容先留档
    return doc


def _prune_snapshots(d: str) -> None:
    files = sorted([f for f in os.listdir(d) if f.endswith(".yaml")], reverse=True)
    for fn in files[SNAPSHOT_KEEP:]:
        try:
            os.remove(os.path.join(d, fn))
        except OSError:
            pass


def merge_parsed(pool: dict, parsed: dict) -> dict:
    """把一次解析结果合并入池（确定性规则，code decides）：

    - basic_info：解析出的非空字段覆盖池值（新简历里的联系方式通常更新）。
    - 分区：同名分区并组——组内按块标题匹配，同标题替换（视为更新版），新标题追加；
      池中没有的分区整个追加到尾部。
    - 池独有的分区/块一律保留（池是超集，只增改不删）。
    """
    out = {
        "basic_info": dict(pool.get("basic_info") or {}),
        "self_description": pool.get("self_description", ""),
        "sections": [
            {"name": s["name"], "blocks": [dict(b) for b in s["blocks"]]}
            for s in (pool.get("sections") or [])
        ],
    }
    for k, v in (parsed.get("basic_info") or {}).items():
        if isinstance(v, str) and v.strip():
            out["basic_info"][k] = v
    by_name = {s["name"]: s for s in out["sections"]}
    for sec in parsed.get("sections") or []:
        target = by_name.get(sec["name"])
        if target is None:
            out["sections"].append({"name": sec["name"], "blocks": [dict(b) for b in sec["blocks"]]})
            by_name[sec["name"]] = out["sections"][-1]
            continue
        by_title = {b["title"]: i for i, b in enumerate(target["blocks"]) if b.get("title")}
        for blk in sec["blocks"]:
            idx = by_title.get(blk.get("title"))
            if idx is not None:
                target["blocks"][idx] = dict(blk)
            else:
                target["blocks"].append(dict(blk))
    return out


def build_pool(pool: dict, self_description: str, model_router, prompt_manager) -> dict:
    """用 LLM 把自我描述融进池（重新整理分区/块，含每块概括）。

    models judge：归类/概括交给 LLM；结构与存储由 code 决定。
    """
    import json

    from services.llm_parser import safe_parse_json

    prompt = prompt_manager.render("resume_build", {
        "resume_json": json.dumps(
            {"basic_info": pool.get("basic_info"), "sections": pool.get("sections")},
            ensure_ascii=False,
        ),
        "self_desc": (self_description or "").strip() or "（无）",
    })
    text, _provider = model_router.complete(prompt=prompt, capability="balanced")
    parsed = safe_parse_json(text, required_fields={"basic_info": dict})
    out = rb.normalize_parsed_doc(parsed, self_description)
    # LLM 整理不许丢基本信息：解析没给的字段用池原值兜底
    for k, v in (pool.get("basic_info") or {}).items():
        if not out["basic_info"].get(k):
            out["basic_info"][k] = v
    return out
