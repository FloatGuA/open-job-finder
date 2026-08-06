"""面试 Prep 卡片的只读加载。

内容存 `data/interview_prep.yaml`（gitignore，属个人材料不进公开仓库）。
这里只负责读盘 + 形状归一，不做任何生成——卡片由人写，不让 LLM 编。
"""
from __future__ import annotations

import os
from typing import Any

import yaml


def _clean_card(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    q = str(raw.get("q") or "").strip()
    if not q:
        return None
    ev = raw.get("evidence") or []
    return {
        "q": q,
        "a": str(raw.get("a") or "").strip(),
        "evidence": [str(x).strip() for x in ev if str(x).strip()] if isinstance(ev, list) else [],
        "avoid": str(raw.get("avoid") or "").strip(),
    }


def _clean_role(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    key = str(raw.get("key") or "").strip()
    name = str(raw.get("name") or "").strip()
    if not key or not name:
        return None
    cards = [c for c in (_clean_card(x) for x in (raw.get("cards") or [])) if c]
    return {
        "key": key,
        "name": name,
        "pitch": str(raw.get("pitch") or "").strip(),
        "hook": str(raw.get("hook") or "").strip(),
        "cards": cards,
    }


def load_prep(path: str) -> dict:
    """读卡片；文件不存在或为空时返回空结构（页面自己提示怎么建）。"""
    if not os.path.exists(path):
        return {"roles": []}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    roles = [r for r in (_clean_role(x) for x in (data.get("roles") or [])) if r]
    return {"roles": roles}
