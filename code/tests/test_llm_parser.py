"""Tests for services/llm_parser.safe_parse_json().

Covers the three-layer fallback: fence extraction → json.loads → json-repair,
plus required_fields coercion.
"""
import pytest

from services.exceptions import LLMParseError
from services.llm_parser import safe_parse_json, _extract_json_candidate


# ── _extract_json_candidate ───────────────────────────────────────────────────

class TestExtractJsonCandidate:
    def test_extracts_from_fence(self):
        text = '```json\n{"key": "value"}\n```'
        assert _extract_json_candidate(text) == '{"key": "value"}'

    def test_extracts_from_fence_case_insensitive(self):
        text = '```JSON\n{"a": 1}\n```'
        assert _extract_json_candidate(text) == '{"a": 1}'

    def test_extracts_bare_object(self):
        text = 'Some preamble {"score": 85} some suffix'
        candidate = _extract_json_candidate(text)
        assert candidate == '{"score": 85}'

    def test_returns_none_for_no_json(self):
        assert _extract_json_candidate("no JSON here at all") is None

    def test_nested_braces(self):
        text = '{"outer": {"inner": 1}}'
        candidate = _extract_json_candidate(text)
        assert candidate == '{"outer": {"inner": 1}}'


# ── safe_parse_json — happy path ─────────────────────────────────────────────

class TestSafeParseJsonHappy:
    def test_plain_json_string(self):
        result = safe_parse_json('{"score": 80, "decision": "apply"}')
        assert result["score"] == 80
        assert result["decision"] == "apply"

    def test_json_in_fence(self):
        text = '```json\n{"verdict": "approve", "reason": "good fit"}\n```'
        result = safe_parse_json(text)
        assert result["verdict"] == "approve"

    def test_json_with_leading_text(self):
        text = 'Here is my assessment:\n{"score": 72}'
        result = safe_parse_json(text)
        assert result["score"] == 72

    def test_json_with_trailing_text(self):
        text = '{"decision": "skip"}\nThat is my final answer.'
        result = safe_parse_json(text)
        assert result["decision"] == "skip"


# ── safe_parse_json — error cases ────────────────────────────────────────────

class TestSafeParseJsonErrors:
    def test_raises_on_no_json(self):
        with pytest.raises(LLMParseError):
            safe_parse_json("There is no JSON here whatsoever.")

    def test_raises_on_json_array_not_object(self):
        with pytest.raises(LLMParseError):
            safe_parse_json("[1, 2, 3]")

    def test_raises_on_empty_string(self):
        with pytest.raises(LLMParseError):
            safe_parse_json("")


# ── required_fields coercion ──────────────────────────────────────────────────

class TestRequiredFieldsCoercion:
    def test_int_coercion(self):
        result = safe_parse_json('{"score": "85"}', required_fields={"score": int})
        assert result["score"] == 85
        assert isinstance(result["score"], int)

    def test_str_coercion(self):
        result = safe_parse_json('{"decision": 1}', required_fields={"decision": str})
        assert result["decision"] == "1"

    def test_missing_field_becomes_none(self):
        result = safe_parse_json('{"other": "x"}', required_fields={"score": int})
        assert result["score"] is None

    def test_invalid_coercion_becomes_none(self):
        result = safe_parse_json('{"score": "not-a-number"}', required_fields={"score": int})
        assert result["score"] is None

    def test_existing_none_value_stays_none(self):
        result = safe_parse_json('{"score": null}', required_fields={"score": int})
        assert result["score"] is None

    def test_coercion_applied_only_to_declared_fields(self):
        result = safe_parse_json(
            '{"score": "80", "reason": "ok"}',
            required_fields={"score": int},
        )
        assert result["score"] == 80
        assert result["reason"] == "ok"  # untouched


# ── Regression: real LLM response shapes ─────────────────────────────────────

class TestRealWorldShapes:
    def test_score_response_shape(self):
        text = """
        Based on my analysis:
        ```json
        {
            "score": 78,
            "decision": "apply",
            "reason": "Good match for backend role",
            "resume_patch": {"summary": "Experienced engineer", "highlights": []}
        }
        ```
        """
        result = safe_parse_json(text, required_fields={"score": int, "decision": str})
        assert result["score"] == 78
        assert result["decision"] == "apply"

    def test_critic_response_shape(self):
        text = '{"verdict": "reject", "reason": "Requires 10+ years experience"}'
        result = safe_parse_json(text, required_fields={"verdict": str})
        assert result["verdict"] == "reject"
