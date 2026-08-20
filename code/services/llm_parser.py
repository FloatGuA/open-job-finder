import json
import logging
import re

from services.exceptions import LLMParseError

logger = logging.getLogger(__name__)

try:
    from json_repair import repair_json as json_repair_func
    _has_json_repair = True
except ImportError:
    logger.warning("json-repair not installed; skipping repair step in llm_parser.")
    _has_json_repair = False


def _extract_json_candidate(text: str) -> str | None:
    fence_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        return fence_match.group(1).strip()

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1].strip()
    return None


def safe_parse_json(text: str, required_fields: dict = None) -> dict:
    """
    Three-layer parsing:
    1. Regex: extract content inside ```json ... ``` code fences.
       If not found, try to find the first {...} block.
    2. json-repair: call repair(extracted_text) if initial json.loads fails.
    3. Field coercion: apply required_fields type mapping.
       For missing fields, use None. For type errors, attempt cast; on failure use None.
    Returns the parsed dict. Raises LLMParseError if all layers fail.
    """
    extracted = _extract_json_candidate(text)

    if not extracted:
        logger.debug("Layer 1 extraction failed. Original text: %s", text)
        raise LLMParseError("No JSON content found in LLM response.")

    parsed = None
    try:
        parsed = json.loads(extracted)
    except json.JSONDecodeError as e:
        logger.debug("Layer 2 json.loads failed for text: %s", text)

        if _has_json_repair:
            try:
                repaired = json_repair_func(extracted)
                parsed = json.loads(repaired) if isinstance(repaired, str) else repaired
            except Exception as e2:
                logger.debug("Layer 2 json-repair failed for text: %s; error: %s", text, e2)
        else:
            logger.debug("json-repair unavailable while parsing text: %s", text)

        if parsed is None:
            raise LLMParseError(f"Failed to parse JSON after all layers. Original error: {e}") from e

    if not isinstance(parsed, dict):
        logger.debug("Parsed JSON is not an object for text: %s", text)
        raise LLMParseError("Parsed JSON is not an object.")

    if required_fields:
        for field_name, field_type in required_fields.items():
            if field_name not in parsed:
                parsed[field_name] = None
            elif parsed[field_name] is not None:
                try:
                    parsed[field_name] = field_type(parsed[field_name])
                except (ValueError, TypeError):
                    logger.debug(
                        "Layer 3 coercion failed for field '%s' to %s. Original text: %s",
                        field_name,
                        getattr(field_type, "__name__", str(field_type)),
                        text,
                    )
                    parsed[field_name] = None

    return parsed


def _extract_json_array_candidate(text: str) -> str | None:
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


def safe_parse_json_array(text: str) -> list:
    """
    与 `safe_parse_json` 同源的三层解析，但顶层结构是数组不是对象：
    1. Regex：提取 ```json ... ``` 围栏内容；找不到则找第一个 [...] 块
       （配平方括号，不是花括号——这是它跟 `safe_parse_json` 唯一的物理差异）。
    2. json-repair：初次 json.loads 失败时调 repair(extracted_text)。

    **没有 `required_fields` 参数**（修复轮 2 去掉）：`safe_parse_json` 的第 3 层
    字段类型强制是给它的调用方用的，`safe_parse_json_array` 目前两个调用方
    （`multisite/classify.py`、`multisite/bucket_plan.py`）拿到 list 后都是自己按
    各自规则逐条校验，不走这层强制。之前加了这个参数只是为了跟 `safe_parse_json`
    "签名对称"，但没有调用方、没有测试——YAGNI。真有第二个数组场景需要字段强制
    时再加，不要为了对称而对称。

    **为什么不是给 `safe_parse_json` 加一个"顶层是数组"的参数**：已实测过，
    把一个 JSON 数组喂给 `safe_parse_json` 它不会报错——`_extract_json_candidate`
    找的是第一个 "{"，命中的是数组里第一个元素对象，`json.loads` 解析成功、
    `isinstance(parsed, dict)` 也通过，于是**只返回数组的第一个元素，其余元素
    被静默丢弃**，调用方毫无察觉。两种顶层结构对应两种完全不同的失败模式，
    合并成一个函数只会把这种静默截断也焊死在共用路径里，所以拆成两个函数。

    Returns the parsed list. Raises LLMParseError if all layers fail or the
    parsed result isn't a list.
    """
    extracted = _extract_json_array_candidate(text)

    if not extracted:
        logger.debug("Layer 1 array extraction failed. Original text: %s", text)
        raise LLMParseError("No JSON array found in LLM response.")

    parsed = None
    try:
        parsed = json.loads(extracted)
    except json.JSONDecodeError as e:
        logger.debug("Layer 2 json.loads failed for text: %s", text)

        if _has_json_repair:
            try:
                repaired = json_repair_func(extracted)
                parsed = json.loads(repaired) if isinstance(repaired, str) else repaired
            except Exception as e2:
                logger.debug("Layer 2 json-repair failed for text: %s; error: %s", text, e2)
        else:
            logger.debug("json-repair unavailable while parsing text: %s", text)

        if parsed is None:
            raise LLMParseError(f"Failed to parse JSON after all layers. Original error: {e}") from e

    if not isinstance(parsed, list):
        logger.debug("Parsed JSON is not an array for text: %s", text)
        raise LLMParseError("Parsed JSON is not an array.")

    return parsed
