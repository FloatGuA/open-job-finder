#!/usr/bin/env python3
"""Parse Boss filter raw dump into clean JSON files for dashboard APIs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse


BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_PATH = DATA_DIR / "boss_filters_raw.json"
DISTRICTS_PATH = DATA_DIR / "boss_districts.json"
POSITIONS_PATH = DATA_DIR / "boss_positions.json"
INDUSTRIES_PATH = DATA_DIR / "boss_industries.json"


DISTRICT_FALLBACK = {
    "\u6df1\u5733": [
        {"label": "\u5357\u5c71\u533a", "code": "440305"},
        {"label": "\u798f\u7530\u533a", "code": "440304"},
        {"label": "\u7f57\u6e56\u533a", "code": "440303"},
        {"label": "\u5b9d\u5b89\u533a", "code": "440306"},
        {"label": "\u9f99\u5c97\u533a", "code": "440307"},
    ],
    "\u5317\u4eac": [
        {"label": "\u6d77\u6dc0\u533a", "code": "110108"},
        {"label": "\u671d\u9633\u533a", "code": "110105"},
        {"label": "\u897f\u57ce\u533a", "code": "110102"},
        {"label": "\u4e1c\u57ce\u533a", "code": "110101"},
        {"label": "\u4e30\u53f0\u533a", "code": "110106"},
    ],
    "\u4e0a\u6d77": [
        {"label": "\u6d66\u4e1c\u65b0\u533a", "code": "310115"},
        {"label": "\u5f90\u6c47\u533a", "code": "310104"},
        {"label": "\u957f\u5b81\u533a", "code": "310105"},
        {"label": "\u9759\u5b89\u533a", "code": "310106"},
        {"label": "\u95f5\u884c\u533a", "code": "310112"},
    ],
}

TREE_FALLBACK_POSITIONS = [
    {"label": "Tech", "code": "100020", "children": [
        {"label": "Backend", "code": "100020.10"},
        {"label": "Frontend", "code": "100020.20"},
        {"label": "QA", "code": "100020.30"},
        {"label": "DevOps", "code": "100020.40"},
        {"label": "Algorithm", "code": "100020.50"},
    ]},
]

TREE_FALLBACK_INDUSTRIES = [
    {"label": "Internet", "code": "10000", "children": [
        {"label": "Ecommerce", "code": "10001"},
        {"label": "Enterprise Service", "code": "10002"},
        {"label": "Mobile Internet", "code": "10003"},
        {"label": "Social", "code": "10004"},
        {"label": "Gaming", "code": "10005"},
    ]},
]


def _json_loads_maybe(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                return None
    return None


def _iter_nodes(value: Any):
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from _iter_nodes(v)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_nodes(item)


def _node_label(node: dict[str, Any]) -> str:
    for key in ("label", "name", "title", "text", "valueName"):
        val = node.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _node_code(node: dict[str, Any]) -> str:
    for key in ("code", "value", "id", "encryptId", "cityCode", "areaCode"):
        val = node.get(key)
        if val is not None:
            sval = str(val).strip()
            if sval:
                return sval
    return ""


def _node_children(node: dict[str, Any]) -> list[dict[str, Any]]:
    for key in ("children", "child", "subList", "subs", "list"):
        children = node.get(key)
        if isinstance(children, list):
            out = [c for c in children if isinstance(c, dict)]
            if out:
                return out
    return []


def _normalize_tree(items: Any) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not isinstance(items, list):
        return out
    for raw in items:
        if not isinstance(raw, dict):
            continue
        label = _node_label(raw)
        code = _node_code(raw)
        if not label and not code:
            continue
        node: dict[str, Any] = {"label": label or code, "code": code or label}
        children = _normalize_tree(_node_children(raw))
        if children:
            node["children"] = children
        out.append(node)
    return out


def _tree_size(items: list[dict[str, Any]]) -> int:
    total = 0
    for node in items:
        total += 1
        total += _tree_size(node.get("children") or [])
    return total


def _extract_trees_from_data(data: Any, key_words: tuple[str, ...]) -> list[list[dict[str, Any]]]:
    trees: list[list[dict[str, Any]]] = []
    for node in _iter_nodes(data):
        for key, val in node.items():
            low = key.lower()
            if any(word in low for word in key_words):
                tree = _normalize_tree(val)
                if tree:
                    trees.append(tree)
    return trees


def _collect_from_raw_network(raw: dict[str, Any]) -> list[Any]:
    payloads: list[Any] = []
    for item in raw.get("_raw_network") or []:
        if not isinstance(item, dict):
            continue
        body = _json_loads_maybe(item.get("body"))
        if body is not None:
            payloads.append(body)
    return payloads


def _collect_filter_link_items(raw: dict[str, Any], param: str) -> list[dict[str, str]]:
    links = raw.get("_raw_filter_links") or {}
    if not isinstance(links, dict):
        return []

    items: list[dict[str, str]] = []
    source = links.get(param)
    if isinstance(source, dict):
        for code, label in source.items():
            if str(label).strip():
                items.append({"label": str(label).strip(), "code": str(code)})

    for v in links.values():
        if not isinstance(v, str):
            continue
        parsed = parse_qs(urlparse(v).query)
        if parsed.get(param):
            code = parsed[param][0]
            if code:
                items.append({"label": code, "code": code})
    return items


def _dedupe_items(items: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for item in items:
        code = str(item.get("code") or "").strip()
        label = str(item.get("label") or "").strip()
        if not code or not label:
            continue
        key = f"{code}|{label}"
        if key in seen:
            continue
        seen.add(key)
        out.append({"label": label, "code": code})
    return out


def _normalize_city_districts(raw: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    districts = raw.get("districts") or {}
    out: dict[str, list[dict[str, str]]] = {}
    if isinstance(districts, dict):
        for city, items in districts.items():
            parsed: list[dict[str, str]] = []
            if isinstance(items, list):
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    label = str(item.get("label") or item.get("name") or "").strip()
                    code = str(item.get("code") or item.get("value") or "").strip()
                    if label and code:
                        parsed.append({"label": label, "code": code})
            if parsed:
                out[str(city)] = _dedupe_items(parsed)

    for city, items in DISTRICT_FALLBACK.items():
        out.setdefault(city, items)
    return out


def _pick_best_tree(trees: list[list[dict[str, Any]]], fallback: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not trees:
        return fallback
    best = max(trees, key=_tree_size)
    if _tree_size(best) < 5:
        return fallback
    return best


def main() -> None:
    raw: dict[str, Any] = {}
    if RAW_PATH.exists():
        raw = _json_loads_maybe(RAW_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raw = {}

    payloads = _collect_from_raw_network(raw)
    payloads.append(raw.get("_window_globals") or {})

    position_trees: list[list[dict[str, Any]]] = []
    industry_trees: list[list[dict[str, Any]]] = []
    for payload in payloads:
        position_trees.extend(_extract_trees_from_data(payload, ("position",)))
        industry_trees.extend(_extract_trees_from_data(payload, ("industry",)))

    # Parse from filter links too (flat fallback)
    position_flat = _collect_filter_link_items(raw, "position")
    industry_flat = _collect_filter_link_items(raw, "industry")
    if position_flat:
        position_trees.append([{"label": "职位类型", "code": "position", "children": _dedupe_items(position_flat)}])
    if industry_flat:
        industry_trees.append([{"label": "公司行业", "code": "industry", "children": _dedupe_items(industry_flat)}])

    districts = _normalize_city_districts(raw)
    positions = _pick_best_tree(position_trees, TREE_FALLBACK_POSITIONS)
    industries = _pick_best_tree(industry_trees, TREE_FALLBACK_INDUSTRIES)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DISTRICTS_PATH.write_text(json.dumps(districts, ensure_ascii=False, indent=2), encoding="utf-8")
    POSITIONS_PATH.write_text(json.dumps(positions, ensure_ascii=False, indent=2), encoding="utf-8")
    INDUSTRIES_PATH.write_text(json.dumps(industries, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Saved: {DISTRICTS_PATH}")
    print(f"Saved: {POSITIONS_PATH}")
    print(f"Saved: {INDUSTRIES_PATH}")
    print(f"District cities: {len(districts)}")
    print(f"Position tree nodes: {_tree_size(positions)}")
    print(f"Industry tree nodes: {_tree_size(industries)}")


if __name__ == "__main__":
    main()
