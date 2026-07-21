"""Tests for ToolGuard — permission checks before side-effect operations."""
import pytest
from unittest.mock import MagicMock, PropertyMock

from services.tool_guard import ToolGuard, GuardResult


@pytest.fixture
def mock_orchestrator():
    orc = MagicMock()
    orc.daily_limit = 25
    orc.tracker.count_today.return_value = 0
    orc.rate_limiter = None  # no rate limiter by default
    return orc


@pytest.fixture
def confirmed_state():
    state = MagicMock()
    state.awaiting_confirmation = True
    return state


@pytest.fixture
def unconfirmed_state():
    state = MagicMock()
    state.awaiting_confirmation = False
    return state


# ── GuardResult ──────────────────────────────────────────────────────────────

def test_guard_result_ok():
    r = GuardResult.OK()
    assert r.ok is True
    assert r.reason == ""


def test_guard_result_blocked():
    r = GuardResult.BLOCKED("test reason")
    assert r.ok is False
    assert r.reason == "test reason"


# ── check_apply ──────────────────────────────────────────────────────────────

def test_check_apply_passes_when_confirmed_and_under_limit(mock_orchestrator, confirmed_state):
    guard = ToolGuard(mock_orchestrator)
    result = guard.check_apply(confirmed_state)
    assert result.ok is True


def test_check_apply_blocked_when_not_confirmed(mock_orchestrator, unconfirmed_state):
    guard = ToolGuard(mock_orchestrator)
    result = guard.check_apply(unconfirmed_state)
    assert result.ok is False
    assert "确认" in result.reason


def test_check_apply_blocked_when_daily_limit_reached(mock_orchestrator, confirmed_state):
    mock_orchestrator.tracker.count_today.return_value = 25
    guard = ToolGuard(mock_orchestrator)
    result = guard.check_apply(confirmed_state)
    assert result.ok is False
    assert "上限" in result.reason


def test_check_apply_blocked_when_rate_limited(mock_orchestrator, confirmed_state):
    rate_limiter = MagicMock()
    rate_limiter.is_exceeded.return_value = True
    mock_orchestrator.rate_limiter = rate_limiter
    guard = ToolGuard(mock_orchestrator)
    result = guard.check_apply(confirmed_state)
    assert result.ok is False
    assert "频率" in result.reason


def test_check_apply_passes_when_rate_limiter_ok(mock_orchestrator, confirmed_state):
    rate_limiter = MagicMock()
    rate_limiter.is_exceeded.return_value = False
    mock_orchestrator.rate_limiter = rate_limiter
    guard = ToolGuard(mock_orchestrator)
    result = guard.check_apply(confirmed_state)
    assert result.ok is True


def test_check_apply_passes_when_at_limit_minus_one(mock_orchestrator, confirmed_state):
    mock_orchestrator.tracker.count_today.return_value = 24
    guard = ToolGuard(mock_orchestrator)
    result = guard.check_apply(confirmed_state)
    assert result.ok is True


# ── check_responses ──────────────────────────────────────────────────────────

def test_check_responses_passes_when_confirmed(mock_orchestrator, confirmed_state):
    guard = ToolGuard(mock_orchestrator)
    result = guard.check_responses(confirmed_state)
    assert result.ok is True


def test_check_responses_blocked_when_not_confirmed(mock_orchestrator, unconfirmed_state):
    guard = ToolGuard(mock_orchestrator)
    result = guard.check_responses(unconfirmed_state)
    assert result.ok is False


# ── check_remember ───────────────────────────────────────────────────────────

def test_check_remember_passes_with_fact(mock_orchestrator):
    guard = ToolGuard(mock_orchestrator)
    result = guard.check_remember("不考虑外包")
    assert result.ok is True


def test_check_remember_blocked_with_empty_string(mock_orchestrator):
    guard = ToolGuard(mock_orchestrator)
    result = guard.check_remember("")
    assert result.ok is False


def test_check_remember_blocked_with_whitespace_only(mock_orchestrator):
    guard = ToolGuard(mock_orchestrator)
    result = guard.check_remember("   ")
    assert result.ok is False
