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
    return data


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


_BUILD_PROMPT = """你是简历结构化助手。把下面的「简历解析结果」和「用户自我描述」整理成 JSON。

要求：
- 严格输出 JSON，不要多余文字。
- basic_info：{name, phone, email, city, degree, target_title}，缺失留空字符串。
- education / internship / project / skills / awards：每项是数组，元素 = {title, time, bullets, summary}。
  - 一段经历 = 一个块（title 是单位/项目/技能名，time 是时间段，bullets 是要点数组）。
  - summary：用一句话概括这个块讲了什么（中文，20 字以内）。
- 只整理与重组已有信息，不要杜撰内容。自我描述里提到但简历没有的经历，也归入对应类别。

简历解析结果：
{resume_json}

用户自我描述：
{self_desc}
"""


def build_blocks(resume_base: dict, self_description: str, model_router) -> dict:
    """用 LLM 把解析后的简历 + 自我描述整理成结构化块库（含每块 summary）。

    models judge：分类/概括是判断活儿，交给 LLM；结构与存储由 code 决定。
    """
    import json

    from services.llm_parser import safe_parse_json

    prompt = _BUILD_PROMPT.format(
        resume_json=json.dumps(resume_base or {}, ensure_ascii=False),
        self_desc=(self_description or "").strip() or "（无）",
    )
    text, _provider = model_router.complete(prompt=prompt, capability="balanced")
    parsed = safe_parse_json(text, required_fields=["basic_info"])

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
