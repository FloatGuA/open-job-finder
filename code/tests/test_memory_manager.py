"""Tests for MemoryManager — short-term session and long-term memory."""
import json
from pathlib import Path

import pytest
import yaml

from services.memory_manager import MemoryManager, MAX_RECENT, COMPRESS_BATCH


@pytest.fixture
def tmp_memory(tmp_path, monkeypatch):
    """Redirect memory paths to a temp directory."""
    import services.memory_manager as mod
    monkeypatch.setattr(mod, "MEMORY_DIR", tmp_path / "memory")
    monkeypatch.setattr(mod, "LONG_TERM_PATH", tmp_path / "memory" / "long_term.yaml")
    monkeypatch.setattr(mod, "SESSIONS_DIR", tmp_path / "memory" / "sessions")
    return MemoryManager()


# ── Session lifecycle ────────────────────────────────────────────────────────

def test_new_session_structure(tmp_memory):
    s = tmp_memory.new_session()
    assert "session_id" in s
    assert s["summary"] == ""
    assert s["recent"] == []
    assert "started_at" in s


def test_load_today_session_none_when_empty(tmp_memory):
    assert tmp_memory.load_today_session() is None


def test_save_and_reload_session(tmp_memory):
    s = tmp_memory.new_session()
    tmp_memory.append_message(s, "user", "你好")
    tmp_memory.append_message(s, "assistant", "您好！")
    tmp_memory.save_session(s)

    loaded = tmp_memory.load_today_session()
    assert loaded is not None
    assert len(loaded["recent"]) == 2
    assert loaded["recent"][0]["content"] == "你好"


def test_append_message_increments_recent(tmp_memory):
    s = tmp_memory.new_session()
    for i in range(5):
        tmp_memory.append_message(s, "user", f"msg {i}")
    assert len(s["recent"]) == 5


# ── Compression ──────────────────────────────────────────────────────────────

def test_compression_triggers_at_max_recent(tmp_memory):
    s = tmp_memory.new_session()
    # Fill beyond MAX_RECENT
    for i in range(MAX_RECENT + 1):
        tmp_memory.append_message(s, "user", f"msg {i}")
    # After compression, recent should be <= MAX_RECENT
    assert len(s["recent"]) <= MAX_RECENT


def test_compression_preserves_content_in_summary(tmp_memory):
    s = tmp_memory.new_session()
    for i in range(MAX_RECENT + 1):
        tmp_memory.append_message(s, "user", f"unique_msg_{i}")
    # Summary should contain the early messages
    assert "unique_msg_0" in s["summary"]


def test_compress_removes_batch_from_recent(tmp_memory):
    s = tmp_memory.new_session()
    for i in range(MAX_RECENT + 2):
        s["recent"].append({"role": "user", "content": f"m{i}"})
    before = len(s["recent"])
    tmp_memory._compress(s)
    assert len(s["recent"]) == before - COMPRESS_BATCH


# ── Long-term memory ─────────────────────────────────────────────────────────

def test_load_long_term_empty_when_no_file(tmp_memory):
    result = tmp_memory.load_long_term()
    assert result == ""


def test_save_and_load_long_term(tmp_memory):
    tmp_memory.save_long_term("不考虑外包公司", "preferences")
    result = tmp_memory.load_long_term()
    assert "不考虑外包公司" in result
    assert "preferences" in result


def test_save_long_term_invalid_category_defaults_to_context(tmp_memory):
    tmp_memory.save_long_term("某个事实", "invalid_category")
    import services.memory_manager as mod
    with mod.LONG_TERM_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    assert "context" in data
    assert any(e["fact"] == "某个事实" for e in data["context"])


def test_save_long_term_appends_multiple(tmp_memory):
    tmp_memory.save_long_term("偏好 AI 方向", "preferences")
    tmp_memory.save_long_term("不考虑外包", "preferences")
    result = tmp_memory.load_long_term()
    assert "偏好 AI 方向" in result
    assert "不考虑外包" in result


def test_save_long_term_empty_fact_is_noop(tmp_memory):
    tmp_memory.save_long_term("", "preferences")
    result = tmp_memory.load_long_term()
    assert result == ""


def test_save_long_term_source_is_user_stated(tmp_memory):
    tmp_memory.save_long_term("测试事实", "context")
    import services.memory_manager as mod
    with mod.LONG_TERM_PATH.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    entry = data["context"][0]
    assert entry["source"] == "user_stated"


# ── Context messages ─────────────────────────────────────────────────────────

def test_get_context_messages_empty_session(tmp_memory):
    s = tmp_memory.new_session()
    msgs = tmp_memory.get_context_messages(s)
    assert msgs == []


def test_get_context_messages_includes_summary_as_assistant(tmp_memory):
    s = tmp_memory.new_session()
    s["summary"] = "之前聊了投递的事"
    s["recent"].append({"role": "user", "content": "继续"})
    msgs = tmp_memory.get_context_messages(s)
    assert msgs[0]["role"] == "assistant"
    assert "之前聊了投递的事" in msgs[0]["content"]
    assert msgs[1]["content"] == "继续"


def test_get_context_messages_dict_content_serialized(tmp_memory):
    s = tmp_memory.new_session()
    s["recent"].append({"role": "assistant", "content": {"key": "val"}})
    msgs = tmp_memory.get_context_messages(s)
    assert isinstance(msgs[0]["content"], str)
    assert "val" in msgs[0]["content"]
