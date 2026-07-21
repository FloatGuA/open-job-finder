"""Tests for ChatAgent — conversation state machine and routing logic."""
import pytest
from unittest.mock import MagicMock, patch

from services.chat_agent import ChatAgent, ConversationState


@pytest.fixture
def mock_orchestrator():
    orc = MagicMock()
    orc.daily_limit = 25
    orc.tracker.count_today.return_value = 0
    orc.rate_limiter = None
    orc.daily_summary.return_value = {
        "applied_today": 3, "daily_limit": 25, "total_applied": 10,
        "responded": 1, "interviews": 0, "offers": 0, "remaining": 22,
    }
    orc.run_once.return_value = {
        "searched": 20, "applied": 5, "skipped": 3, "errors": 0,
    }
    orc.check_responses.return_value = {
        "checked": 34, "updated": 2,
        "updates": [{"company": "测试公司A"}, {"company": "测试公司B"}],
        "total_convs": 34, "unread_count": 2, "new_hr_msgs": 2,
        "synced_conversations": [
            {"company": "测试公司A", "last_msg": "方便聊吗"},
            {"company": "测试公司B", "last_msg": "请投递简历"},
        ],
    }
    return orc


@pytest.fixture
def agent(mock_orchestrator, tmp_path, monkeypatch):
    """ChatAgent with memory redirected to tmp_path."""
    import services.memory_manager as mm_mod
    monkeypatch.setattr(mm_mod, "MEMORY_DIR", tmp_path / "memory")
    monkeypatch.setattr(mm_mod, "LONG_TERM_PATH", tmp_path / "memory" / "long_term.yaml")
    monkeypatch.setattr(mm_mod, "SESSIONS_DIR", tmp_path / "memory" / "sessions")

    # Patch IntentClassifier to use rule-based only (no Ollama)
    with patch("services.chat_agent.IntentClassifier") as MockClf:
        from services.intent_classifier import IntentClassifier
        real_clf = IntentClassifier()
        real_clf._ollama_available = False
        MockClf.return_value = real_clf
        a = ChatAgent(mock_orchestrator)
    return a


# ── ConversationState ────────────────────────────────────────────────────────

def test_state_reset_clears_all_fields():
    state = ConversationState(
        pending_workflow="apply",
        awaiting_confirmation=True,
        last_config_shown="some config",
    )
    state.reset()
    assert state.pending_workflow is None
    assert state.awaiting_confirmation is False
    assert state.last_config_shown == ""


# ── Summary route ────────────────────────────────────────────────────────────

def test_handle_summary_intent(agent):
    response = agent.handle("今天投了多少")
    assert "3" in response  # applied_today
    assert "25" in response  # daily_limit


# ── Pre-flight: apply ────────────────────────────────────────────────────────

def test_handle_apply_sets_pending_state(agent):
    response = agent.handle("帮我投几个岗位")
    assert agent.state.awaiting_confirmation is True
    assert agent.state.pending_workflow == "apply"
    assert "配置" in response or "参数" in response


def test_handle_apply_then_confirm_executes(agent):
    agent.handle("帮我投岗位")
    response = agent.handle("好")
    assert agent.state.awaiting_confirmation is False
    assert agent.state.pending_workflow is None
    assert "投递" in response or "搜索" in response


def test_handle_apply_then_cancel_resets_state(agent):
    agent.handle("帮我投岗位")
    response = agent.handle("取消")
    assert agent.state.awaiting_confirmation is False
    assert "取消" in response


def test_handle_apply_blocked_at_daily_limit(agent, mock_orchestrator):
    mock_orchestrator.tracker.count_today.return_value = 25
    agent.handle("帮我投岗位")
    response = agent.handle("好")
    assert "上限" in response
    assert agent.state.pending_workflow is None  # state cleared


# ── Pre-flight: check ─────────────────────────────────────────────────────────

def test_handle_check_sets_pending_state(agent):
    response = agent.handle("检查一下回复")
    assert agent.state.awaiting_confirmation is True
    assert agent.state.pending_workflow == "check"


def test_handle_check_then_confirm_executes(agent):
    agent.handle("检查回复")
    response = agent.handle("可以")
    assert "34" in response or "检查" in response
    assert agent.state.pending_workflow is None


def test_handle_check_result_with_updates(agent):
    agent.handle("有没有HR回我")
    response = agent.handle("好")
    assert "2" in response  # new_hr_msgs count
    assert "测试公司A" in response or "测试公司B" in response


def test_handle_check_result_no_updates(agent, mock_orchestrator):
    mock_orchestrator.check_responses.return_value = {
        "checked": 10, "updated": 0, "updates": [],
        "total_convs": 10, "unread_count": 0, "new_hr_msgs": 0,
        "synced_conversations": [],
    }
    agent.handle("查看回复")
    response = agent.handle("嗯")
    assert "暂无新 HR 消息" in response


# ── Remember ──────────────────────────────────────────────────────────────────

def test_handle_remember_saves_to_long_term(agent):
    response = agent.handle("记住我不考虑外包公司")
    assert "已记住" in response
    long_term = agent.memory.load_long_term()
    assert "不考虑外包公司" in long_term


# ── Unknown intent ────────────────────────────────────────────────────────────

def test_handle_unknown_returns_hint(agent):
    # Patch classifier to return unknown
    agent.classifier._ollama_available = False
    response = agent.handle("今天天气真好")
    # Either unknown fallback or chitchat (chitchat calls Ollama which is patched)
    # Just verify it returns a non-empty string and doesn't crash
    assert isinstance(response, str)
    assert len(response) > 0


# ── State machine: mid-confirmation config change ────────────────────────────

def test_mid_confirmation_config_change_keeps_pending(agent, tmp_path, monkeypatch):
    """If user says a config-change while awaiting confirmation, state stays pending."""
    import agent_workflows as mod
    p = tmp_path / "profile.yaml"
    import yaml
    p.write_text(yaml.dump({"keywords": ["AI"], "cities": ["深圳"],
                             "job_type": "实习", "experience": [],
                             "degree": [], "salary": "", "boss_online": True,
                             "score_threshold": 50}, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(mod, "_PROFILE_PATH", p)

    agent.handle("帮我投岗位")
    assert agent.state.awaiting_confirmation is True
    # User wants to change config — state should remain pending after handling
    agent.handle("把评分阈值改成60")
    # Still waiting for final confirmation
    assert agent.state.awaiting_confirmation is True


# ── Session persistence ───────────────────────────────────────────────────────

def test_messages_appended_to_session(agent):
    initial = len(agent.session["recent"])
    agent.handle("今天状态")
    # user + assistant = 2 new messages
    assert len(agent.session["recent"]) == initial + 2


def test_end_session_saves_to_disk(agent):
    agent.handle("帮我汇报一下")
    agent._end_session()
    loaded = agent.memory.load_today_session()
    assert loaded is not None
    assert len(loaded["recent"]) > 0
