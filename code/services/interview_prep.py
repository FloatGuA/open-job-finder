"""面试 Prep 卡片的只读加载。

内容存 `data/interview_prep.yaml`（gitignore，属个人材料不进公开仓库）。
这里只负责读盘 + 形状归一，不做任何生成——卡片由人写，不让 LLM 编。
"""
from __future__ import annotations

import os
import re
from typing import Any

import yaml

# YAML 折叠标量（`>-`）在每个换行处插一个空格。英文里正好是词间距，中文里就成了
# 句中一个多余的空格（"落库， 每次运行"）。在读入边界统一收掉：只有空格两侧都是
# CJK 字符/全角标点时才删——"302 行 / 全项目"这种中英混排的空格必须保留。
_CJK = r"　-〿一-鿿＀-￯"
_CJK_GAP = re.compile(r"(?<=[" + _CJK + r"])[ \t]+(?=[" + _CJK + r"])")


def _text(v: Any) -> str:
    return _CJK_GAP.sub("", str(v or "").strip())


def _clean_card(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    q = _text(raw.get("q"))
    if not q:
        return None
    ev = raw.get("evidence") or []
    return {
        "q": q,
        "a": _text(raw.get("a")),
        "evidence": [_text(x) for x in ev if _text(x)] if isinstance(ev, list) else [],
        "avoid": _text(raw.get("avoid")),
    }


def _clean_role(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    key = str(raw.get("key") or "").strip()
    name = _text(raw.get("name"))
    if not key or not name:
        return None
    cards = [c for c in (_clean_card(x) for x in (raw.get("cards") or [])) if c]
    return {
        "key": key,
        "name": name,
        "pitch": _text(raw.get("pitch")),
        "hook": _text(raw.get("hook")),
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
