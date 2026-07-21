"""Tests for agent_workflows — registry, config read/write, display formatting."""
import pytest
import yaml

from agent_workflows import (
    WORKFLOW_REGISTRY,
    format_config_for_display,
    read_profile,
    read_config,
    update_profile,
)


@pytest.fixture
def profile_file(tmp_path, monkeypatch):
    """Create a temp profile.yaml and patch the path constant."""
    import agent_workflows as mod
    p = tmp_path / "profile.yaml"
    data = {
        "keywords": ["AI"],
        "cities": ["深圳"],
        "job_type": "实习",
        "experience": ["应届生"],
        "degree": ["硕士"],
        "salary": "",
        "boss_online": True,
        "score_threshold": 50,
    }
    p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(mod, "_PROFILE_PATH", p)
    return p


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """Create a temp config.yaml and patch the path constant."""
    import agent_workflows as mod
    p = tmp_path / "config.yaml"
    data = {
        "schedule": {"check_responses_days": 7, "check_responses_max": 200},
        "apply": {"score_threshold": 60, "daily_limit": 25},
    }
    p.write_text(yaml.dump(data, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(mod, "_CONFIG_PATH", p)
    return p


# ── WORKFLOW_REGISTRY ────────────────────────────────────────────────────────

def test_registry_has_required_workflows():
    assert "apply" in WORKFLOW_REGISTRY
    assert "check" in WORKFLOW_REGISTRY
    assert "summary" in WORKFLOW_REGISTRY


def test_registry_apply_requires_confirmation():
    assert WORKFLOW_REGISTRY["apply"]["requires_confirmation"] is True


def test_registry_summary_no_confirmation():
    assert WORKFLOW_REGISTRY["summary"]["requires_confirmation"] is False


def test_registry_all_have_description():
    for key, wf in WORKFLOW_REGISTRY.items():
        assert "description" in wf, f"{key} missing description"


# ── read_profile ─────────────────────────────────────────────────────────────

def test_read_profile_returns_dict(profile_file):
    profile = read_profile()
    assert isinstance(profile, dict)
    assert profile["keywords"] == ["AI"]


def test_read_profile_returns_empty_when_missing(tmp_path, monkeypatch):
    import agent_workflows as mod
    monkeypatch.setattr(mod, "_PROFILE_PATH", tmp_path / "nonexistent.yaml")
    assert read_profile() == {}


# ── update_profile ───────────────────────────────────────────────────────────

def test_update_profile_changes_field(profile_file):
    result = update_profile("score_threshold", 70)
    assert result is True
    profile = read_profile()
    assert profile["score_threshold"] == 70


def test_update_profile_adds_new_field(profile_file):
    result = update_profile("new_field", "new_value")
    assert result is True
    profile = read_profile()
    assert profile["new_field"] == "new_value"


def test_update_profile_preserves_other_fields(profile_file):
    update_profile("score_threshold", 80)
    profile = read_profile()
    assert profile["keywords"] == ["AI"]  # unchanged


# ── read_config ──────────────────────────────────────────────────────────────

def test_read_config_returns_schedule_fields(config_file):
    cfg = read_config()
    assert cfg["check_responses_days"] == 7
    assert cfg["check_responses_max"] == 200


def test_read_config_returns_empty_when_missing(tmp_path, monkeypatch):
    import agent_workflows as mod
    monkeypatch.setattr(mod, "_CONFIG_PATH", tmp_path / "nonexistent.yaml")
    assert read_config() == {}


# ── format_config_for_display ────────────────────────────────────────────────

def test_format_apply_config_contains_all_fields(profile_file):
    display = format_config_for_display("apply")
    assert "关键词" in display
    assert "城市" in display
    assert "评分阈值" in display
    assert "仅活跃HR" in display


def test_format_apply_config_bool_shows_chinese(profile_file):
    display = format_config_for_display("apply")
    assert "是" in display  # boss_online: True → "是"


def test_format_apply_config_list_joined(profile_file):
    display = format_config_for_display("apply")
    assert "AI" in display


def test_format_check_config_contains_days_and_max(config_file):
    display = format_config_for_display("check")
    assert "扫描天数" in display
    assert "最多条数" in display
    assert "7" in display
    assert "200" in display


def test_format_unknown_workflow_returns_error():
    display = format_config_for_display("nonexistent")
    assert "未知" in display


def test_format_summary_no_config_needed():
    display = format_config_for_display("summary")
    assert "无需配置" in display
