"""Tests for IntentClassifier — rule-based fallback path (no Ollama needed)."""
import pytest
from services.intent_classifier import IntentClassifier, Intent


@pytest.fixture
def clf():
    c = IntentClassifier()
    c._ollama_available = False  # force rule-based, no network call
    return c


# ── Rule-based classification ────────────────────────────────────────────────

@pytest.mark.parametrize("text,expected_type", [
    ("帮我投几个岗位", "apply"),
    ("投递几个职位", "apply"),
    ("开始投简历", "apply"),
    ("搜索一下职位", "apply"),
    ("检查一下回复", "check"),
    ("有没有HR回我", "check"),
    ("应聘进度怎么样", "check"),
    ("查看回复", "check"),
    ("今天投了多少", "summary"),
    ("汇报一下状态", "summary"),
    ("统计数据", "summary"),
    ("记住我不考虑外包", "remember"),
    ("记一下，不想去大厂", "remember"),
    ("把关键词改成AI算法", "config"),
    ("修改一下城市设置", "config"),
])
def test_rule_based_known_intents(clf, text, expected_type):
    intent = clf._classify_rules(text)
    assert intent.type == expected_type
    assert intent.confidence == "low"


def test_rule_based_unknown(clf):
    intent = clf._classify_rules("今天天气真好")
    assert intent.type == "unknown"


def test_empty_input_returns_chitchat(clf):
    intent = clf.classify("")
    assert intent.type == "chitchat"


def test_rule_fallback_when_ollama_disabled(clf):
    intent = clf.classify("帮我投岗位")
    assert intent.type == "apply"


# ── Confirm / cancel detection ───────────────────────────────────────────────

@pytest.mark.parametrize("text", ["好", "可以", "行", "嗯", "确认", "ok", "开始", ""])
def test_is_confirm_positive(clf, text):
    assert clf.is_confirm(text) is True


@pytest.mark.parametrize("text", ["不", "取消", "算了", "停", "no"])
def test_is_cancel_positive(clf, text):
    assert clf.is_cancel(text) is True


def test_confirm_and_cancel_are_mutually_exclusive(clf):
    # "好" is confirm, not cancel
    assert clf.is_confirm("好") is True
    assert clf.is_cancel("好") is False


# ── LLM path: parse valid JSON response ─────────────────────────────────────

def test_classify_llm_parses_valid_json(monkeypatch):
    import json
    import services.intent_classifier as mod

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {"message": {"content": '{"type":"apply","params":{},"confidence":"high"}'}}

    monkeypatch.setattr(mod.requests, "post", lambda *a, **kw: FakeResp())
    clf = IntentClassifier()
    clf._ollama_available = None
    intent = clf.classify("帮我投岗位")
    assert intent.type == "apply"
    assert intent.confidence == "high"


def test_classify_llm_falls_back_on_json_error(monkeypatch):
    import services.intent_classifier as mod

    def bad_post(*a, **kw):
        raise ConnectionError("ollama down")

    monkeypatch.setattr(mod.requests, "post", bad_post)
    clf = IntentClassifier()
    clf._ollama_available = None
    intent = clf.classify("检查回复")
    # should fall back to rule-based
    assert intent.type == "check"
    assert intent.confidence == "low"
    assert clf._ollama_available is False


def test_classify_llm_handles_markdown_codeblock(monkeypatch):
    import services.intent_classifier as mod

    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            body = "```json\n{\"type\":\"summary\",\"params\":{},\"confidence\":\"high\"}\n```"
            return {"message": {"content": body}}

    monkeypatch.setattr(mod.requests, "post", lambda *a, **kw: FakeResp())
    clf = IntentClassifier()
    clf._ollama_available = None
    intent = clf.classify("今天状态")
    assert intent.type == "summary"
