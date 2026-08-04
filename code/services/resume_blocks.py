"""简历块文档（v2.16 起为「自定义动态分区」形状；信息池与每份简历共用同一形状）。

文档形状（信息池 data/info_pool.yaml 与简历 data/resumes/{slug}.yaml 相同）：
  basic_info: {name, phone, email, city, degree, target_title}
  self_description: str          # 信息池实际使用（融入池的原料）；简历文件保留兼容
  sections: [ {name: str, blocks: [ {title, time, bullets[], summary} ]} ]

分区名自定义（如「游戏经历」「Agent 经历」），顺序即数组顺序（拖拽直接重排数组）。
旧形状（≤v2.15：education/... 固定五键 + section_order）在 load_blocks 读入时自动
转换为动态 sections，一次保存后即固化为新形状。
"""
import os
from typing import Optional

import yaml

# 旧形状的固定类别键（仅用于 legacy 转换）及其中文分区名
LEGACY_CATEGORIES = ["education", "internship", "project", "skills", "awards"]
LEGACY_LABELS = {
    "education": "教育经历", "internship": "实习经历", "project": "项目经历",
    "skills": "技能特长", "awards": "获奖荣誉",
}

_BASIC_FIELDS = ["name", "phone", "email", "city", "degree", "target_title"]


def empty_blocks() -> dict:
    return {"basic_info": {k: "" for k in _BASIC_FIELDS}, "self_description": "", "sections": []}


# 字段级富文本开关：每个块的 title / time / bullets 各自可设 粗/斜/下划线。
# 空 dict = 用模板预设（分区标题粗体带下划线、条目标题粗体、日期灰色），所以老数据
# 不带 style 时行为完全不变；AI 组合出来的简历同样走预设。
_STYLE_FIELDS = ("title", "time", "bullets")
_STYLE_MARKS = ("bold", "italic", "underline")


def clean_style(raw) -> dict:
    """归一化字段级样式：{field: {bold/italic/underline: bool}}，只留 True 的键。"""
    out = {}
    if not isinstance(raw, dict):
        return out
    for f in _STYLE_FIELDS:
        marks = raw.get(f)
        if not isinstance(marks, dict):
            continue
        on = {m: True for m in _STYLE_MARKS if marks.get(m)}
        if on:
            out[f] = on
    return out


def _clean_block(it) -> Optional[dict]:
    if not isinstance(it, dict):
        return None
    return {
        "title": str(it.get("title", "")),
        "time": str(it.get("time", "")),
        "bullets": [str(b) for b in (it.get("bullets") or []) if str(b).strip()],
        "summary": str(it.get("summary", "")),
        "style": clean_style(it.get("style")),
    }


def clean_sections(items) -> list:
    """归一化 sections：只认 {name, blocks[]}，块逐字段兜底；无名分区给占位名。"""
    out = []
    for sec in items if isinstance(items, list) else []:
        if not isinstance(sec, dict):
            continue
        blocks = [b for b in (_clean_block(it) for it in (sec.get("blocks") or [])) if b is not None]
        name = str(sec.get("name", "")).strip() or "未命名分区"
        out.append({"name": name, "blocks": blocks})
    return out


def _convert_legacy(data: dict) -> list:
    """旧五键形状 → 动态 sections（按 section_order 顺序，含空分区保留编辑位）。"""
    order = [c for c in (data.get("section_order") or []) if c in LEGACY_CATEGORIES]
    order += [c for c in LEGACY_CATEGORIES if c not in order]
    sections = []
    for cat in order:
        items = data.get(cat)
        blocks = [b for b in (_clean_block(it) for it in (items if isinstance(items, list) else [])) if b is not None]
        sections.append({"name": LEGACY_LABELS[cat], "blocks": blocks})
    return sections


def load_blocks(path: str = "data/resume_blocks.yaml") -> dict:
    """读取文档；不存在返回空结构；旧形状自动转换为动态 sections。"""
    if not os.path.exists(path):
        return empty_blocks()
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    base = empty_blocks()
    bi = data.get("basic_info") or {}
    for k in _BASIC_FIELDS:
        if k in bi:
            base["basic_info"][k] = bi[k]
    base["self_description"] = data.get("self_description", "")
    if isinstance(data.get("sections"), list):
        base["sections"] = clean_sections(data["sections"])
    elif any(k in data for k in LEGACY_CATEGORIES):
        base["sections"] = _convert_legacy(data)
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
    return bool(d["basic_info"].get("name")) or any(s["blocks"] for s in d["sections"])


def normalize_parsed_doc(parsed: dict, self_description: str = "") -> dict:
    """LLM 解析输出（{basic_info, sections}）→ 稳定文档结构，逐字段兜底。"""
    out = empty_blocks()
    out["self_description"] = self_description or ""
    bi = parsed.get("basic_info") or {}
    for k in _BASIC_FIELDS:
        v = bi.get(k)
        if isinstance(v, str):
            out["basic_info"][k] = v
    out["sections"] = clean_sections(parsed.get("sections"))
    return out


def parse_resume_to_blocks(raw_text: str, model_router, prompt_manager) -> dict:
    """LLM 一步解析：PDF/DOCX 提取的纯文本 → 动态分区文档（入信息池用）。

    models judge：解析/归类/概括交给 LLM（分区名由它按内容起，如「游戏经历」）；
    结构与存储由 code 决定。
    """
    from services.llm_parser import safe_parse_json

    prompt = prompt_manager.render("resume_parse", {"raw_text": (raw_text or "").strip()})
    text, _provider = model_router.complete(prompt=prompt, capability="balanced")
    parsed = safe_parse_json(text, required_fields={"basic_info": dict})
    return normalize_parsed_doc(parsed, "")


def parse_resume_vision(pdf_path: str, model_router, prompt_manager) -> dict:
    """视觉解析：PDF 渲染成页面图片 → 视觉模型（vision 链）直接读版式 → 动态分区文档。

    排版型简历（多栏/图形/表格）的纯文本提取会丢结构，视觉模型看真实版面能更准地
    归类。走 vision capability 链（codex_cli 主 + claude_cli 兜底）。
    """
    from services.llm_parser import safe_parse_json
    from services.resume_parser import render_pdf_to_images

    images = render_pdf_to_images(pdf_path)
    if not images:
        raise ValueError("PDF 渲染图片为空，无法视觉解析")
    prompt = prompt_manager.render("resume_parse_vision", {})
    text, _provider = model_router.complete(prompt=prompt, images=images, capability="vision")
    parsed = safe_parse_json(text, required_fields={"basic_info": dict})
    return normalize_parsed_doc(parsed, "")
