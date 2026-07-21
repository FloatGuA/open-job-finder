"""Unit tests for ConfigManager and /api/config/* endpoints."""
import copy
import importlib

import pytest
import yaml
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)


# ---------------------------------------------------------------------------
# ConfigManager unit tests
# ---------------------------------------------------------------------------

class TestConfigManager:
    def _make_cm(self, tmp_path, config_data=None, profile_data=None):
        import services.config_manager as cm_mod
        # Reset singleton so each test starts clean
        cm_mod._instance = None

        cfg_path = tmp_path / "config.yaml"
        prof_path = tmp_path / "data" / "profile.yaml"

        _write_yaml(cfg_path, config_data or {
            "llm": {"capabilities": {"fast": [], "balanced": []}},
            "w1": {"score_threshold": 60},
            "w2": {},
        })
        if profile_data is not None:
            _write_yaml(prof_path, profile_data)

        return cm_mod.ConfigManager(str(cfg_path), str(prof_path))

    def test_get_profile_returns_deep_copy(self, tmp_path):
        cm = self._make_cm(tmp_path, profile_data={"keywords": ["Python"], "cities": ["北京"]})
        p1 = cm.get_profile()
        p1["keywords"].append("Go")
        p2 = cm.get_profile()
        assert p2["keywords"] == ["Python"], "Mutation of returned dict must not affect internal state"

    def test_get_system_config_returns_deep_copy(self, tmp_path):
        cm = self._make_cm(tmp_path)
        c1 = cm.get_system_config()
        c1["w1"]["score_threshold"] = 999
        c2 = cm.get_system_config()
        assert c2["w1"]["score_threshold"] == 60

    def test_save_profile_merges_and_does_not_delete_unmentioned_keys(self, tmp_path):
        cm = self._make_cm(tmp_path, profile_data={"keywords": ["Python"], "cities": ["北京"]})
        cm.save_profile({"keywords": ["Python", "Go"]})
        p = cm.get_profile()
        assert p["keywords"] == ["Python", "Go"]
        assert p["cities"] == ["北京"], "Unmentioned key 'cities' must be preserved"

    def test_save_profile_creates_file_when_missing(self, tmp_path):
        import services.config_manager as cm_mod
        cm_mod._instance = None
        cfg_path = tmp_path / "config.yaml"
        prof_path = tmp_path / "data" / "profile.yaml"
        _write_yaml(cfg_path, {"apply": {}})
        # profile does not exist yet
        cm = cm_mod.ConfigManager(str(cfg_path), str(prof_path))
        cm.save_profile({"keywords": ["Python"]})
        assert prof_path.exists()
        with prof_path.open("r", encoding="utf-8") as f:
            saved = yaml.safe_load(f)
        assert saved["keywords"] == ["Python"]

    def test_save_system_config_rejects_llm_section(self, tmp_path):
        cm = self._make_cm(tmp_path)
        with pytest.raises(ValueError, match="llm"):
            cm.save_system_config("llm", {"capabilities": {}})

    def test_save_system_config_writes_allowed_section(self, tmp_path):
        cm = self._make_cm(tmp_path)
        cm.save_system_config("w1", {"score_threshold": 75})
        cfg = cm.get_system_config()
        assert cfg["w1"]["score_threshold"] == 75

    def test_reload_re_reads_disk(self, tmp_path):
        cm = self._make_cm(tmp_path, profile_data={"keywords": ["Python"]})
        # Externally modify profile file
        prof_path = tmp_path / "data" / "profile.yaml"
        _write_yaml(prof_path, {"keywords": ["Rust"]})
        cm.reload()
        assert cm.get_profile()["keywords"] == ["Rust"]


# ---------------------------------------------------------------------------
# /api/config/* endpoint tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(tmp_path, monkeypatch):
    """Return a TestClient wired to a temp config + profile."""
    import services.config_manager as cm_mod
    cm_mod._instance = None

    cfg_path = tmp_path / "config.yaml"
    prof_path = tmp_path / "data" / "profile.yaml"

    _write_yaml(cfg_path, {
        "llm": {"capabilities": {"fast": [], "balanced": []}},
        "w1": {"score_threshold": 60, "daily_limit": 10},
        "w2": {"max_conversations": 200},
    })
    _write_yaml(prof_path, {"keywords": ["Python"], "cities": ["北京"]})

    # Patch constants used by server.py before importing the app
    import dashboard.server as srv
    monkeypatch.setattr(srv, "CONFIG_PATH", cfg_path)
    monkeypatch.setattr(srv, "PROFILE_PATH", prof_path)

    # Reset singleton to pick up patched paths
    cm_mod._instance = None

    return TestClient(srv.app)


def test_get_config_system_returns_non_sensitive(client):
    resp = client.get("/api/config/system")
    assert resp.status_code == 200
    data = resp.json()
    # Must contain expected keys
    assert "w1" in data
    assert "w2" in data
    assert "llm_capabilities" in data
    # Must NOT expose api_key or full llm config
    assert "api_key" not in str(data)
    assert "providers" not in str(data)
    assert isinstance(data["llm_capabilities"], list)
