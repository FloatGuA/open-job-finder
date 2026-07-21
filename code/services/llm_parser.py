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
