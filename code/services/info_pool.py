"""信息池（v2.16）：关于求职者的全部信息的主库，高于任何一份简历。

- 存 data/info_pool.yaml，形状与简历文档相同（basic_info + self_description + sections），
  分区名自定义（如「游戏经历」「Agent 经历」）。
- 上传简历解析 → merge_parsed 合并入池（同名分区并组、同标题块替换、新块追加）。
- 简历 = 从池中挑块的**复制**组合（每份独立，改简历不回写池）。
- 首次使用自动迁移：把当前激活简历的内容收编为池的初始内容。
"""
import os

from services import resume_blocks as rb

POOL_PATH = "data/info_pool.yaml"


def load_pool(path: str = POOL_PATH, active_resume_path: str = "data/resume_blocks.yaml") -> dict:
    """读池；不存在则从激活简历迁移初始化（简历也没有就给空结构）。"""
    if os.path.exists(path):
        return rb.load_blocks(path)
    pool = rb.load_blocks(active_resume_path)  # 空文件时本身就是空结构
    rb.save_blocks(pool, path)
    return pool


def save_pool(pool: dict, path: str = POOL_PATH) -> None:
    rb.save_blocks(pool, path)


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
