"""岗位分类：批量、纯判断、可测。

**不走 ReAct 循环**是刻意的（spec §2.1 同理）：它不需要"看一眼再决定下一步"，
输入是文本、输出是标签。做成普通 LLM 调用换来的是**可单测 + 可 eval**。

**解析没有复用 `services/llm_parser.safe_parse_json`**：那个函数认死了 LLM
回复的顶层是一个 JSON 对象——`_extract_json_candidate` 只找 `{...}`，末尾还
`isinstance(parsed, dict)` 校验。而这里的输出天然是一个数组（`[{"index":...}]`，
按 index 对齐是硬要求，见下）。套用不了，所以照它的三层思路（围栏提取 →
json.loads → json_repair 兜底）单独写了一份只服务数组场景的最小实现，
详见本文件底部的 `_extract_json_array` / `_parse_response`。

**`classify_jobs` 是 `async def`**（修复轮 1）：调用方 `multisite/harvest.py` 的
`harvest_page` 本身是 `async def`，且跑在 LangGraph 已有的事件循环里；这里如果
用 `asyncio.run()` 自己另起一个循环，会在集成时直接炸
`RuntimeError: asyncio.run() cannot be called from a running event loop`。
multisite 这一层从浏览器工具到 `run_agent` 全是 async，分类是网络调用，跟着
统一成 async 而不是靠 `model.invoke()` 同步接口绕过——后者会在 async 管线里
插一个阻塞调用，只是「眼下没有并发」才不出问题，是把正确性寄托在环境假设上。
"""
import json
import re
from pathlib import Path

from json_repair import repair_json

from multisite.agent_runtime import build_model

_PROMPT_PATH = Path(__file__).resolve().parent.parent.parent / "prompts" / "layer1_classify_jobs.md"

_PLACEHOLDER_RE = re.compile(r"\{\{(\w+)\}\}")

# 本模块没有 tracker 入参（签名见 spec），不接历史纠正样例——那是选岗 agent
# （layer1_find_jobs，见 preferences.render_golden_examples）的事。
_NO_GOLDEN_EXAMPLES = "（本次未提供历史纠正样例）"


async def classify_jobs(
    items: list[dict],
    quotas: dict,
    *,
    model=None,
    prompt_text: str | None = None,
) -> list[dict]:
    """给每条岗位打一个类别标签。

    入参每项至少 `{title, jd, site_category}`，出参每项在原字段基础上加
    `{category, why}`。空输入直接返回空列表，**不调模型**——没有岗位就没有
    要判断的东西，调一次空 prompt 只是白花钱。
    """
    if not items:
        return []

    if model is None:
        model = build_model()
    if prompt_text is None:
        prompt_text = _PROMPT_PATH.read_text(encoding="utf-8")

    prompt = _render_prompt(prompt_text, items, quotas)

    response = await model.ainvoke(prompt)
    raw_results = _parse_response(response.content)

    by_index: dict[int, dict] = {}
    for entry in raw_results:
        if not isinstance(entry, dict):
            continue
        index = entry.get("index")
        if isinstance(index, int):
            by_index[index] = entry

    out = []
    for i, item in enumerate(items):
        merged = dict(item)
        entry = by_index.get(i)
        if entry is None:
            # LLM 没回这一条——按 index 对齐，缺的就是空，绝不能让后面的
            # 答案错位顶上来（那会给岗位安错标签，结果却看起来完全正常）。
            merged["category"] = ""
            merged["why"] = ""
        else:
            category = entry.get("category") or ""
            why = entry.get("why") or ""
            if category in quotas:
                merged["category"] = category
                merged["why"] = why
            else:
                # 类别必须来自配额表，否则配额形同虚设。不丢弃 LLM 报的名字——
                # 写进 why 留痕，这是调 prompt 时最好的线索。
                merged["category"] = ""
                merged["why"] = f"LLM 报的类别「{category}」不在配额表里。{why}".strip()
        out.append(merged)
    return out


def _render_prompt(template: str, items: list[dict], quotas: dict) -> str:
    quota_table = "、".join(f"{name} {count} 个" for name, count in quotas.items()) or "（未配置）"
    jobs_block = "\n\n".join(
        f"### [{i}] {item.get('title', '')}\n"
        f"站点分类：{item.get('site_category', '') or '（无）'}\n"
        f"职责：{item.get('jd', '') or '（无）'}"
        for i, item in enumerate(items)
    )

    text = template
    for key, value in {
        "quota_table": quota_table,
        "golden_examples": _NO_GOLDEN_EXAMPLES,
        "jobs": jobs_block,
    }.items():
        text = text.replace("{{" + key + "}}", value)

    remaining = _PLACEHOLDER_RE.findall(text)
    if remaining:
        raise ValueError(f"prompt 模板占位符未替换：{remaining}")
    return text


def _extract_json_array(text: str) -> str | None:
    """比照 `services/llm_parser._extract_json_candidate`，但找 `[...]` 而不是
    `{...}`——顶层结构不一样，找的括号也得跟着换。"""
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
    """整段回不成 JSON 数组是失败，抛 `ValueError`——静默返回空列表会让上层
    把它当成"这一页没有符合的岗位"。"""
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
