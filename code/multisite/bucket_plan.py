"""桶计划：这一轮该去站点的哪几个桶，每个桶指望捞哪几个目标类别。

**术语**：**桶**＝站点自己的顶层分类（技术/产品/设计/市场…），运行时才从 `SiteManual.dimensions`
里发现；**类别**＝我们的目标类别（AI NATIVE/开发/产品…），来自 profile 的配额表。
桶计划做的就是这两者的映射。

**不走 ReAct 循环**（spec §2.1 同理，另见 `classify.py` 顶部说明）：它不碰浏览器，输入是
手册和求职条件，输出是一份清单，没有"观察→行动"的循环可言。做成普通 LLM 调用换来的是
**可单测、可 eval**（给定手册 A + 条件 B → 该选哪些桶，有 ground truth）。

**校验层才是这个模块的价值**（不是防御性编程）：LLM 会编。
- 编一个手册里没有的 `dimension`/`option` → 代码照着去点必然点空 → 而"点空"表现为
  "这个桶没有岗位"，跟真的没有分不开。所以逐条核对 dimension/option 真的在
  `manual.dimensions` 里，对不上就丢。
- 编一个配额表里没有的 `targets` → 后面按类别统计时凭空多出一类。所以 targets 逐个核对
  是否在配额表里，不在的丢；**一个桶如果对不上任何有效目标类别，整条丢掉**——扫它是
  纯浪费预算。

**`plan_buckets` 是 `async def`**：调用方是 LangGraph 图节点，那些节点全是 `async def`
（同 `classify.py` 的理由——multisite 这一层从浏览器工具到 `run_agent` 全是 async，跟着
统一成 async 而不是靠同步接口绕过）。

**JSON 数组解析没有从 `classify.py` 里 import**：那两个函数（`_extract_json_array` /
`_parse_response`）名字带下划线，是 classify.py 的模块内部实现，跨模块 import 私有符号会
把 bucket_plan 的正确性绑在 classify.py 不打算维持的内部契约上。本次改动范围也不许碰
classify.py（不能把它们改成公开符号）。两边形状确实一样（顶层都是 JSON 数组），所以这里
按同样的思路（围栏提取 → json.loads → json_repair 兜底）单独写一份，重复的是逻辑不是接口。
"""
import json
import re
from pathlib import Path

from json_repair import repair_json

from multisite.agent_runtime import build_model
from multisite.site_manual import SiteManual

_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "layer1_plan_buckets.md"

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")


async def plan_buckets(
    manual: SiteManual,
    quotas: dict,
    constraints: str,
    *,
    model=None,
    prompt_text: str | None = None,
) -> list[dict]:
    """决定这一轮扫哪几个桶。

    返回每项 `{"dimension": str, "option": str, "why": str, "targets": list[str]}`。
    **空列表是合法结果**（站上确实没有相关的桶），不抛；整段回不成 JSON 数组才抛
    `ValueError`（那是"没读懂"，不是"没有"，两者不能用同一个返回值表达）。
    """
    if model is None:
        model = build_model()
    if prompt_text is None:
        prompt_text = _PROMPT_PATH.read_text(encoding="utf-8")

    prompt = _render_prompt(prompt_text, manual, quotas, constraints)

    response = await model.ainvoke(prompt)
    raw_plan = _parse_response(response.content)

    valid_options = {
        dim.get("name"): set(dim.get("options") or [])
        for dim in (manual.dimensions or [])
        if isinstance(dim, dict)
    }

    out = []
    for entry in raw_plan:
        if not isinstance(entry, dict):
            continue
        dimension = entry.get("dimension")
        option = entry.get("option")
        if dimension not in valid_options:
            # 手册里根本没有这个维度——编的，丢掉整条。
            continue
        if option not in valid_options[dimension]:
            # 维度是真的，选项是编的——照着去点必然点空，丢掉整条。
            continue

        targets = [t for t in (entry.get("targets") or []) if t in quotas]
        if not targets:
            # 对不上任何有效目标类别，扫它是纯浪费预算。
            continue

        out.append({
            "dimension": dimension,
            "option": option,
            "why": entry.get("why") or "",
            "targets": targets,
        })
    return out


def _render_prompt(template: str, manual: SiteManual, quotas: dict, constraints: str) -> str:
    dimensions_block = "\n".join(
        f"- {dim.get('name', '')}：{', '.join(dim.get('options') or [])}"
        for dim in (manual.dimensions or [])
    ) or "（无）"
    quota_table = "、".join(f"{name} {count} 个" for name, count in quotas.items()) or "（未配置）"

    text = template
    for key, value in {
        "dimensions": dimensions_block,
        "quota_table": quota_table,
        "constraints": constraints or "（无）",
    }.items():
        text = text.replace("{{" + key + "}}", value)

    remaining = _PLACEHOLDER_RE.findall(text)
    if remaining:
        raise ValueError(f"prompt 模板占位符未替换：{remaining}")
    return text


def _extract_json_array(text: str) -> str | None:
    """比照 `classify.py` 的同名函数：围栏提取 + 括号配平，找 `[...]`。"""
    fence_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()

    start = text.find("[")
    if start == -1:
        return None

    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return text[start:index + 1].strip()
    return None


def _parse_response(text: str) -> list:
    """整段回不成 JSON 数组是失败，抛 `ValueError`——静默返回空列表会让"没读懂"
    和"确实没有相关的桶"变成同一个返回值，两者含义完全不同。"""
    extracted = _extract_json_array(text)
    if extracted is None:
        raise ValueError(f"LLM 回复中没有找到 JSON 数组：{text[:200]!r}")

    try:
        parsed = json.loads(extracted)
    except json.JSONDecodeError as exc:
        try:
            repaired = repair_json(extracted)
            parsed = json.loads(repaired) if isinstance(repaired, str) else repaired
        except Exception:
            raise ValueError(f"LLM 回复无法解析为 JSON：{text[:200]!r}") from exc

    if not isinstance(parsed, list):
        raise ValueError(f"LLM 回复解析结果不是 JSON 数组：{text[:200]!r}")
    return parsed
