"""简历积木库（功能一）。

把简历 + 用户自我描述拆成"可排列组合的块"，按固定类别分组：
- basic_info：固定字段（姓名/电话/邮箱/城市/学历/期望岗位）
- education / internship / project / skills / awards：块列表，
  每块 = {title, time, bullets[], summary}（一段经历 = 一个块）

单一可编辑真相：data/resume_blocks.yaml。上传简历仅用于预填。
非 basic_info 的块各带一个 LLM 生成的「简单概括」(summary)，供功能二挑块用。
"""
import copy
import os
from typing import Optional

import yaml

# 非 basic_info 的固定类别（块列表）
BLOCK_CATEGORIES = ["education", "internship", "project", "skills", "awards"]

_BASIC_FIELDS = ["name", "phone", "email", "city", "degree", "target_title"]


def empty_blocks() -> dict:
    data: dict = {"basic_info": {k: "" for k in _BASIC_FIELDS}, "self_description": ""}
    for cat in BLOCK_CATEGORIES:
        data[cat] = []
    # 分区在简历里的先后顺序（编辑器可拖拽调整，预览/导出按此渲染）
    data["section_order"] = list(BLOCK_CATEGORIES)
    return data


def normalize_section_order(order) -> list:
    """归一化分区顺序：只认已知类别、去重，缺的按默认顺序补到尾部（结构稳定）。"""
    seen = []
    for c in order if isinstance(order, list) else []:
        if c in BLOCK_CATEGORIES and c not in seen:
            seen.append(c)
    return seen + [c for c in BLOCK_CATEGORIES if c not in seen]


def load_blocks(path: str = "data/resume_blocks.yaml") -> dict:
    """读取块库；不存在返回空结构。补齐缺失类别，保证结构稳定。"""
    if not os.path.exists(path):
        return empty_blocks()
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    base = empty_blocks()
    # 浅合并，保留已有、补齐缺失
    bi = data.get("basic_info") or {}
    for k in _BASIC_FIELDS:
        if k in bi:
            base["basic_info"][k] = bi[k]
    base["self_description"] = data.get("self_description", "")
    for cat in BLOCK_CATEGORIES:
        if isinstance(data.get(cat), list):
            base[cat] = data[cat]
    base["section_order"] = normalize_section_order(data.get("section_order"))
    return base


def save_blocks(data: dict, path: str = "data/resume_blocks.yaml") -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


def is_available(path: str = "data/resume_blocks.yaml") -> bool:
    try:
        d = load_blocks(path)
    except Exception:
        return False
    return bool(d["basic_info"].get("name")) or any(d.get(c) for c in BLOCK_CATEGORIES)


def build_blocks(resume_base: dict, self_description: str, model_router, prompt_manager) -> dict:
    """用 LLM 把解析后的简历 + 自我描述整理成结构化块库（含每块 summary）。

    models judge：分类/概括是判断活儿，交给 LLM；结构与存储由 code 决定。
    """
    import json

    from services.llm_parser import safe_parse_json

    prompt = prompt_manager.render("resume_build", {
        "resume_json": json.dumps(resume_base or {}, ensure_ascii=False),
        "self_desc": (self_description or "").strip() or "（无）",
    })
    text, _provider = model_router.complete(prompt=prompt, capability="balanced")
    parsed = safe_parse_json(text, required_fields={"basic_info": dict})
    return _normalize_parsed_blocks(parsed, self_description)


def _normalize_parsed_blocks(parsed: dict, self_description: str = "") -> dict:
    """把 LLM 解析出的 JSON 归一化成稳定的块库结构（basic_info + 5 类块，逐字段兜底）。

    build_blocks（简历+自述整理）与 parse_resume_to_blocks（PDF 文本一步解析）共用。
    """
    out = empty_blocks()
    out["self_description"] = self_description or ""
    bi = parsed.get("basic_info") or {}
    for k in _BASIC_FIELDS:
        v = bi.get(k)
        if isinstance(v, str):
            out["basic_info"][k] = v
    for cat in BLOCK_CATEGORIES:
        items = parsed.get(cat)
        if not isinstance(items, list):
            continue
        clean = []
        for it in items:
            if not isinstance(it, dict):
                continue
            clean.append({
                "title": str(it.get("title", "")),
                "time": str(it.get("time", "")),
                "bullets": [str(b) for b in (it.get("bullets") or []) if str(b).strip()],
                "summary": str(it.get("summary", "")),
            })
        out[cat] = clean
    return out


def parse_resume_to_blocks(raw_text: str, model_router, prompt_manager) -> dict:
    """LLM 一步解析：PDF/DOCX 提取的纯文本 → 结构化块库（跳过脆弱正则，更接近 flowcv）。

    models judge：解析/归类/概括交给 LLM；结构与存储由 code 决定。
    """
    from services.llm_parser import safe_parse_json

    prompt = prompt_manager.render("resume_parse", {"raw_text": (raw_text or "").strip()})
    text, _provider = model_router.complete(prompt=prompt, capability="balanced")
    parsed = safe_parse_json(text, required_fields={"basic_info": dict})
    return _normalize_parsed_blocks(parsed, "")


def parse_resume_vision(pdf_path: str, model_router, prompt_manager) -> dict:
    """视觉解析：PDF 渲染成页面图片 → 视觉模型（vision 链）直接读版式 → 结构化块库。

    排版型简历（多栏/图形/表格）的纯文本提取会丢结构，视觉模型看真实版面能更准地
    归类。走 vision capability 链（本地 qwen2.5vl 主 + 云端 claude 兜底）。
    """
    from services.llm_parser import safe_parse_json
    from services.resume_parser import render_pdf_to_images

    images = render_pdf_to_images(pdf_path)
    if not images:
        raise ValueError("PDF 渲染图片为空，无法视觉解析")
    prompt = prompt_manager.render("resume_parse_vision", {})
    text, _provider = model_router.complete(prompt=prompt, images=images, capability="vision")
    parsed = safe_parse_json(text, required_fields={"basic_info": dict})
    return _normalize_parsed_blocks(parsed, "")
