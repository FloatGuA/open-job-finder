"""FastAPI integration tests for dashboard/server.py.

Uses TestClient — no real browser, no real LLM, no network calls.
All filesystem I/O is redirected to pytest's tmp_path via monkeypatching.
"""
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml
from fastapi.testclient import TestClient

from dashboard.server import app
from schemas import AppStatus, ApplicationRecord, HRConversation
import dashboard.server as srv


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rec(
    job_id: str = "j001",
    status: str = AppStatus.FOUND.value,
    city: str = "北京",
    salary: str = "10K-20K",
    applied_at: str = None,
    score: int = 70,
) -> ApplicationRecord:
    # A genuine W1 apply is always scored; count_today excludes score-NULL rows
    # (backfill reconstructions), so seeded APPLIED records need a score to count.
    now = _now()
    return ApplicationRecord(
        job_id=job_id,
        title="后端工程师",
        company="测试公司",
        url="https://www.zhipin.com/job/001",
        status=status,
        city=city,
        salary=salary,
        score=score,
        applied_at=applied_at,
        created_at=now,
    )


def _upload_file(content: bytes, filename: str) -> dict:
    """Build a files dict for TestClient upload requests."""
    return {"file": (filename, io.BytesIO(content), "application/octet-stream")}


def _conv(
    conv_id: str = "conv_001",
    company: str = "测试公司",
    hr_name: str = "王女士",
) -> HRConversation:
    return HRConversation(
        conv_id=conv_id,
        hr_name=hr_name,
        company=company,
        last_msg_preview="你好",
        created_at=_now(),
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient with all server paths redirected to tmp_path.

    Patches DATA_DIR, CONTROL_PATH, PROFILE_PATH, CONFIG_PATH and the four
    filter-data paths so every test runs in an isolated empty filesystem.
    Also mocks build_model_router to avoid real LLM client construction.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Reset the ConfigManager singleton. It binds to whatever paths it was first
    # constructed with and then ignores later ones (by design -- the app has exactly
    # one config), so without this every test after the first would read the FIRST
    # test's tmp_path. Endpoints now read/write config through this singleton, which
    # is what makes the leak visible.
    from services import config_manager as _cm
    _cm._instance = None

    # ConfigManager fails fast when config.yaml is missing (it is required in any
    # real deployment). Give the sandbox that same precondition instead of weakening
    # the guard -- tests should not be the reason a missing config becomes tolerable.
    cfg_file = tmp_path / "config.yaml"
    if not cfg_file.exists():
        cfg_file.write_text("llm: {}\n", encoding="utf-8")

    # Close and reset any tracker left over from a previous test
    old = getattr(app.state, "tracker", None)
    if old is not None:
        old.close()
    app.state.tracker = None

    # Reset emitter (created once at app startup; we reuse it but clear state)
    emitter = getattr(app.state, "emitter", None)
    if emitter is not None:
        emitter.current_workflow = None
        emitter.stop_requested = False
    app.state.workflow_running = None
    # Clear any items a previous test left in the shared queue so its daemon
    # worker can't run a stale item (with the REAL runner) once this test resets
    # the mutex below.
    _q = getattr(app.state, "workflow_queue", None)
    if _q is not None:
        _q.clear()

    # Redirect every path that server.py resolves at runtime
    monkeypatch.setattr(srv, "DATA_DIR", data_dir)
    monkeypatch.setattr(srv, "CONTROL_PATH", data_dir / "control.json")
    monkeypatch.setattr(srv, "PROFILE_PATH", data_dir / "profile.yaml")
    monkeypatch.setattr(srv, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(srv, "BOSS_DISTRICTS_PATH", data_dir / "boss_districts.json")
    monkeypatch.setattr(srv, "BOSS_POSITIONS_PATH", data_dir / "boss_positions.json")
    monkeypatch.setattr(srv, "BOSS_INDUSTRIES_PATH", data_dir / "boss_industries.json")
    monkeypatch.setattr(srv, "RUNS_DIR", tmp_path / "runs")
    # Prevent real LLM client creation. configured_provider_names() must return a
    # real list (not an auto-generated MagicMock) -- /api/config/llm JSON-encodes it.
    def _fake_router(*a, **kw):
        router = MagicMock()
        router.configured_provider_names.return_value = []
        return router
    monkeypatch.setattr(srv, "build_model_router", _fake_router)

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    # Teardown: close the tracker the startup event created
    tracker = getattr(app.state, "tracker", None)
    if tracker is not None:
        tracker.close()
    app.state.tracker = None


@pytest.fixture
def populated(client):
    """client with a few records pre-inserted into the tracker."""
    tracker = app.state.tracker
    tracker.upsert(_rec("j001", AppStatus.FOUND.value))
    tracker.upsert(_rec("j002", AppStatus.REJECTED.value))
    tracker.upsert(_rec("j003", AppStatus.APPLIED.value, applied_at=_now()))
    return client


# ── Jobs list / detail ────────────────────────────────────────────────────────


def _write_run_log(runs_dir: Path, filename: str, events: list[dict]) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    content = "\n".join(json.dumps(event, ensure_ascii=False) for event in events) + "\n"
    (runs_dir / filename).write_text(content, encoding="utf-8")


class TestRunLogs:
    def test_runs_empty_dir(self, client):
        r = client.get("/api/runs")
        assert r.status_code == 200
        assert r.json() == {"runs": [], "total": 0}

    def test_runs_list_and_pipeline_filter(self, client, tmp_path):
        runs_dir = tmp_path / "runs"
        _write_run_log(
            runs_dir,
            "w1_20260521-014000_ab12cd34.jsonl",
            [
                {"event": "run_start", "run_id": "ab12cd34ef56", "pipeline": "w1",
                 "ts": "2026-05-20T17:40:00Z"},
                {"event": "run_end", "run_id": "ab12cd34ef56", "pipeline": "w1",
                 "ts": "2026-05-20T17:52:34Z", "status": "done", "duration_ms": 754000,
                 "summary": {"applied": 2}},
            ],
        )
        _write_run_log(
            runs_dir,
            "w2_20260521-015000_cd34ef56.jsonl",
            [
                {"event": "run_start", "run_id": "cd34ef567890", "pipeline": "w2",
                 "ts": "2026-05-20T17:50:00Z"},
            ],
        )

        r = client.get("/api/runs")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 2
        # Sorted by started_at desc: the w2 run (17:50) comes before w1 (17:40)
        assert data["runs"][0]["run_id"] == "cd34ef567890"
        assert data["runs"][0]["status"] == "running"
        assert data["runs"][1]["summary"] == {"applied": 2}

        r = client.get("/api/runs?pipeline=w1")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        assert data["runs"][0]["pipeline"] == "w1"

    def test_run_detail_groups_steps_and_404(self, client, tmp_path):
        runs_dir = tmp_path / "runs"
        _write_run_log(
            runs_dir,
            "w1_20260521-014000_ab12cd34.jsonl",
            [
                {"event": "run_start", "run_id": "ab12cd34ef56", "pipeline": "w1",
                 "ts": "2026-05-20T17:40:00Z"},
                {"event": "step", "run_id": "ab12cd34ef56", "step": "fetch_jd",
                 "scope": {}, "status": "successful", "duration_ms": 10, "data": {},
                 "ts": "2026-05-20T17:40:05Z"},
                {"event": "tool", "run_id": "ab12cd34ef56", "tool": "read_panel_jd",
                 "scope": {}, "status": "successful", "duration_ms": 5, "data": {},
                 "ts": "2026-05-20T17:40:06Z"},
                {"event": "job_scored", "run_id": "ab12cd34ef56", "scope": {"job_id": "j1"},
                 "data": {"score": 78}, "ts": "2026-05-20T17:40:07Z"},
                {"event": "run_end", "run_id": "ab12cd34ef56", "ts": "2026-05-20T17:41:00Z",
                 "status": "done", "duration_ms": 60000, "summary": {"applied": 1}},
            ],
        )

        r = client.get("/api/runs/ab12cd34ef56")
        assert r.status_code == 200
        data = r.json()
        assert data["run_id"] == "ab12cd34ef56"
        assert data["status"] == "done"
        # one step, with the tool event attached to it
        assert len(data["steps"]) == 1
        assert data["steps"][0]["step"] == "fetch_jd"
        assert data["steps"][0]["tools"][0]["tool"] == "read_panel_jd"
        # non step/tool/meta events become business events
        assert any(be["event"] == "job_scored" for be in data["business_events"])

        assert client.get("/api/runs/unknown").status_code == 404


class TestOpsArtifacts:
    def test_empty_when_nothing_on_disk(self, client):
        r = client.get("/api/ops/artifacts")
        assert r.status_code == 200
        assert r.json() == {"run_logs": [], "screenshots": []}

    def test_lists_only_failed_runs_and_all_screenshots(self, client, tmp_path):
        runs_dir = tmp_path / "runs"
        _write_run_log(runs_dir, "w1_ok.jsonl", [
            {"event": "run_start", "run_id": "ok1", "pipeline": "w1", "ts": "2026-08-01T00:00:00Z"},
            {"event": "run_end", "run_id": "ok1", "ts": "2026-08-01T00:01:00Z", "status": "successful", "summary": {}},
        ])
        _write_run_log(runs_dir, "w1_bad.jsonl", [
            {"event": "run_start", "run_id": "bad1", "pipeline": "w1", "ts": "2026-08-01T00:00:00Z"},
            {"event": "run_end", "run_id": "bad1", "ts": "2026-08-01T00:01:00Z", "status": "failed", "summary": {}},
        ])
        shots_dir = tmp_path / "data" / "apply_failures"
        shots_dir.mkdir(parents=True)
        (shots_dir / "bad1_job1_20260801_000100.png").write_bytes(b"fake")

        r = client.get("/api/ops/artifacts")
        data = r.json()
        assert [x["run_id"] for x in data["run_logs"]] == ["bad1"]
        assert data["screenshots"][0]["filename"] == "bad1_job1_20260801_000100.png"

    def test_delete_removes_selected_files_only(self, client, tmp_path):
        runs_dir = tmp_path / "runs"
        _write_run_log(runs_dir, "w1_bad.jsonl", [
            {"event": "run_start", "run_id": "bad1", "pipeline": "w1", "ts": "2026-08-01T00:00:00Z"},
            {"event": "run_end", "run_id": "bad1", "ts": "2026-08-01T00:01:00Z", "status": "failed", "summary": {}},
        ])
        shots_dir = tmp_path / "data" / "apply_failures"
        shots_dir.mkdir(parents=True)
        (shots_dir / "keep.png").write_bytes(b"x")
        (shots_dir / "drop.png").write_bytes(b"x")

        r = client.post("/api/ops/artifacts/delete", json={
            "run_logs": ["w1_bad.jsonl"],
            "screenshots": ["drop.png"],
        })
        assert r.status_code == 200
        body = r.json()
        assert body["run_logs"] == {"w1_bad.jsonl": True}
        assert body["screenshots"] == {"drop.png": True}
        assert body["deleted_count"] == 2
        assert not (runs_dir / "w1_bad.jsonl").exists()
        assert not (shots_dir / "drop.png").exists()
        assert (shots_dir / "keep.png").exists()

    def test_delete_rejects_path_traversal_without_error(self, client, tmp_path):
        r = client.post("/api/ops/artifacts/delete", json={
            "run_logs": ["../../etc/passwd"],
            "screenshots": [],
        })
        assert r.status_code == 200
        assert r.json()["run_logs"] == {"../../etc/passwd": False}


class TestJobsEndpoints:
    def test_list_empty(self, client):
        r = client.get("/api/jobs")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 0
        assert data["jobs"] == []
        assert data["page"] == 1

    def test_list_returns_records(self, populated):
        r = populated.get("/api/jobs")
        assert r.json()["total"] == 3

    def test_list_job_shape(self, populated):
        job = populated.get("/api/jobs").json()["jobs"][0]
        for key in ("job_id", "title", "company", "city", "salary", "status",
                    "score", "applied_at", "url"):
            assert key in job, f"key '{key}' missing"

    def test_list_city_salary_present(self, populated):
        jobs = populated.get("/api/jobs").json()["jobs"]
        j = next(j for j in jobs if j["job_id"] == "j001")
        assert j["city"] == "北京"
        assert j["salary"] == "10K-20K"

    def test_pagination(self, populated):
        r = populated.get("/api/jobs?page=1&page_size=2")
        data = r.json()
        assert len(data["jobs"]) == 2
        assert data["total"] == 3

    def test_pagination_second_page(self, populated):
        r = populated.get("/api/jobs?page=2&page_size=2")
        assert len(r.json()["jobs"]) == 1

    def test_filter_by_status(self, populated):
        r = populated.get(f"/api/jobs?status={AppStatus.FOUND.value}")
        data = r.json()
        assert data["total"] == 1
        assert data["jobs"][0]["status"] == AppStatus.FOUND.value

    def test_invalid_page_rejected(self, client):
        assert client.get("/api/jobs?page=0").status_code == 400

    def test_invalid_page_size_rejected(self, client):
        assert client.get("/api/jobs?page_size=0").status_code == 400

    def test_get_single_job(self, populated):
        r = populated.get("/api/jobs/j001")
        assert r.status_code == 200
        assert r.json()["job_id"] == "j001"

    def test_get_nonexistent_job_returns_404(self, client):
        assert client.get("/api/jobs/ghost").status_code == 404


# ── Stats ─────────────────────────────────────────────────────────────────────

class TestStats:
    def test_stats_empty(self, client):
        r = client.get("/api/stats")
        assert r.status_code == 200
        stats = r.json()["stats"]
        assert stats["total"] == 0
        assert stats["applied_today"] == 0
        # daily_limit comes from config (empty → default 25)
        assert "daily_limit" in stats
        assert "remaining_today" in stats

    def test_stats_with_applied_record(self, client):
        app.state.tracker.upsert(_rec("j1", AppStatus.APPLIED.value, applied_at=_now()))
        stats = client.get("/api/stats").json()["stats"]
        assert stats["total"] == 1
        assert stats["applied_today"] == 1

    def test_stats_contains_onboarding(self, client):
        assert "onboarding" in client.get("/api/stats").json()

    def test_stats_by_status_has_all_statuses(self, client):
        by_status = client.get("/api/stats").json()["stats"]["by_status"]
        for s in AppStatus:
            assert s.value in by_status


# ── Pause / Resume / Control ──────────────────────────────────────────────────

class TestControlPauseResume:
    def test_control_status_unpaused_initially(self, client):
        r = client.get("/api/control/status")
        assert r.status_code == 200
        assert r.json()["paused"] is False

    def test_pause_returns_paused_true(self, client):
        r = client.post("/api/pause")
        assert r.status_code == 200
        assert r.json()["paused"] is True

    def test_pause_creates_control_file(self, client, tmp_path):
        client.post("/api/pause")
        assert (tmp_path / "data" / "control.json").exists()

    def test_control_status_after_pause(self, client):
        client.post("/api/pause")
        assert client.get("/api/control/status").json()["paused"] is True

    def test_resume_returns_paused_false(self, client):
        client.post("/api/pause")
        r = client.post("/api/resume")
        assert r.json()["paused"] is False

    def test_resume_removes_control_file(self, client, tmp_path):
        client.post("/api/pause")
        client.post("/api/resume")
        assert not (tmp_path / "data" / "control.json").exists()

    def test_resume_is_idempotent_without_file(self, client):
        # No prior pause — resume should not raise
        r = client.post("/api/resume")
        assert r.status_code == 200


# ── Profile CRUD ──────────────────────────────────────────────────────────────

class TestProfile:
    def test_get_defaults_when_profile_missing(self, client):
        r = client.get("/api/profile")
        assert r.status_code == 200
        data = r.json()
        assert data["keywords"] == []
        assert data["cities"] == []
        assert data["salary"] == ""

    def test_save_and_retrieve_profile(self, client):
        payload = {
            "keywords": ["Python", "后端"],
            "cities": ["北京"],
            "salary": "15K-25K",
            "experience": ["1-3年"],
            "degree": ["本科"],
            "scale": [],
            "job_types": [],
            "financing": [],
            "districts": [],
            "position_types": [],
            "industries": [],
        }
        assert client.post("/api/profile", json=payload).status_code == 200

        got = client.get("/api/profile").json()
        assert got["keywords"] == ["Python", "后端"]
        assert got["cities"] == ["北京"]
        assert got["salary"] == "15K-25K"

    def test_save_preserves_unmanaged_fields(self, client, tmp_path):
        # Pre-write a profile.yaml with a field the dashboard doesn't manage
        profile_file = tmp_path / "data" / "profile.yaml"
        with profile_file.open("w", encoding="utf-8") as f:
            yaml.dump({"greeting_template": "你好，我是{name}", "keywords": []}, f,
                      allow_unicode=True)

        client.post("/api/profile", json={"keywords": ["Go"], "cities": []})
        with profile_file.open("r", encoding="utf-8") as f:
            saved = yaml.safe_load(f)
        assert saved.get("greeting_template") == "你好，我是{name}"
        assert saved["keywords"] == ["Go"]


# ── LLM Config ────────────────────────────────────────────────────────────────

class TestLLMConfig:
    def test_get_defaults_when_no_config_file(self, client):
        r = client.get("/api/config/llm")
        assert r.status_code == 200
        data = r.json()
        assert "capabilities" in data
        assert "tool_providers" in data

    def test_save_and_get_llm_config(self, client):
        client.post("/api/config/llm", json={
            "capabilities": {"fast": "ollama", "balanced": "ollama", "powerful": "ollama"},
            "tool_providers": {},
        })
        r = client.get("/api/config/llm")
        data = r.json()
        assert data["capabilities"]["fast"] == "ollama"
        assert data["capabilities"]["balanced"] == "ollama"

    def test_save_config_writes_yaml_file(self, client, tmp_path):
        client.post("/api/config/llm", json={
            "capabilities": {"fast": "anthropic_api", "balanced": "claude_cli", "powerful": "claude_cli"},
            "tool_providers": {},
        })
        cfg_path = tmp_path / "config.yaml"
        assert cfg_path.exists()
        with cfg_path.open("r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        caps = cfg["llm"]["capabilities"]
        assert caps["fast"][0]["type"] == "anthropic_api"
        assert caps["balanced"][0]["type"] == "claude_cli"


# ── Filter endpoints (districts / positions / industries) ─────────────────────

class TestFilterEndpoints:
    def test_districts_empty_when_no_file(self, client):
        r = client.get("/api/filters/districts")
        assert r.status_code == 200
        assert r.json()["items"] == []

    def test_positions_empty_when_no_file(self, client):
        assert client.get("/api/filters/positions").json()["items"] == []

    def test_industries_empty_when_no_file(self, client):
        assert client.get("/api/filters/industries").json()["items"] == []

    def test_districts_with_city_param(self, client, tmp_path):
        data = {"北京": [{"code": "110100", "name": "朝阳区"}]}
        (tmp_path / "data" / "boss_districts.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        r = client.get("/api/filters/districts?city=北京")
        items = r.json()["items"]
        assert len(items) == 1
        assert items[0]["name"] == "朝阳区"

    def test_districts_unknown_city_returns_empty(self, client, tmp_path):
        data = {"北京": [{"code": "110100", "name": "朝阳区"}]}
        (tmp_path / "data" / "boss_districts.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
        assert client.get("/api/filters/districts?city=火星市").json()["items"] == []

    def test_positions_returns_list(self, client, tmp_path):
        items = [{"code": "100001", "name": "后端开发"}]
        (tmp_path / "data" / "boss_positions.json").write_text(
            json.dumps(items, ensure_ascii=False), encoding="utf-8"
        )
        assert client.get("/api/filters/positions").json()["items"] == items

    def test_industries_returns_list(self, client, tmp_path):
        items = [{"code": "200001", "name": "互联网"}]
        (tmp_path / "data" / "boss_industries.json").write_text(
            json.dumps(items, ensure_ascii=False), encoding="utf-8"
        )
        assert client.get("/api/filters/industries").json()["items"] == items


# ── Resume upload ─────────────────────────────────────────────────────────────

class TestResumeUpload:
    def test_upload_wrong_type_rejected(self, client):
        r = client.post(
            "/api/resume/upload",
            files=_upload_file(b"hello", "resume.txt"),
        )
        assert r.status_code == 400
        assert "PDF" in r.json()["detail"] or "DOCX" in r.json()["detail"]

    def test_upload_too_large_rejected(self, client):
        big = b"A" * (10 * 1024 * 1024 + 1)  # just over 10 MB
        r = client.post(
            "/api/resume/upload",
            files=_upload_file(big, "big.pdf"),
        )
        assert r.status_code == 400
        assert "10 MB" in r.json()["detail"]

    def test_upload_pdf_ok(self, client):
        doc = {"basic_info": {"name": "张三"}, "self_description": "",
               "sections": [{"name": "技能特长", "blocks": [{"title": "Python", "time": "", "bullets": [], "summary": ""}]}]}
        with patch("dashboard.server._parse_resume_upload", return_value=(doc, "vision")):
            r = client.post(
                "/api/resume/upload",
                files=_upload_file(b"%PDF-1.4 minimal content", "my_resume.pdf"),
            )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["method"] == "vision"
        assert "技能特长" in data["sections_found"]

    def test_upload_docx_ok(self, client):
        doc = {"basic_info": {"name": "李四"}, "self_description": "", "sections": []}
        with patch("dashboard.server._parse_resume_upload", return_value=(doc, "text")):
            r = client.post(
                "/api/resume/upload",
                files=_upload_file(b"PK fake docx bytes", "cv.docx"),
            )
        assert r.status_code == 200


# ── Conversations ─────────────────────────────────────────────────────────────

class TestConversations:
    def test_empty_conversations(self, client):
        r = client.get("/api/conversations")
        assert r.status_code == 200
        data = r.json()
        assert data["conversations"] == []
        assert data["total"] == 0

    def test_response_shape(self, client):
        r = client.get("/api/conversations")
        assert "conversations" in r.json()
        assert "total" in r.json()

    def test_status_filter_param_accepted(self, client):
        r = client.get("/api/conversations?status=pending&stage=general")
        assert r.status_code == 200

    def test_get_conversations_includes_intent_and_suggested_reply(self, client):
        conv = _conv()
        app.state.tracker.upsert_hr_conversation(conv)
        app.state.tracker.update_hr_analysis(
            conv.conv_id,
            "greeting",
            "你好，方便聊聊岗位吗？",
            reply_status="pending",
        )

        data = client.get("/api/conversations").json()["conversations"]
        assert data[0]["intent"] == "greeting"
        assert data[0]["suggested_reply"] == "你好，方便聊聊岗位吗？"
        assert data[0]["needs_reply"] is True
        assert data[0]["reply_status"] == "pending"

    def test_pending_replies_endpoint_returns_approval_queue(self, client):
        conv = _conv()
        app.state.tracker.upsert_hr_conversation(conv)
        app.state.tracker.update_hr_analysis(
            conv.conv_id,
            "info_request",
            "我这边补充一下项目经历。",
            reply_status="approved",
        )

        data = client.get("/api/conversations/pending-replies").json()
        assert len(data) == 1
        assert data[0]["conv_id"] == conv.conv_id
        assert data[0]["intent"] == "info_request"
        assert data[0]["reply_status"] == "approved"

    def test_approve_reply_endpoint_updates_status(self, client):
        conv = _conv()
        app.state.tracker.upsert_hr_conversation(conv)
        app.state.tracker.update_hr_analysis(
            conv.conv_id,
            "greeting",
            "你好，感谢联系。",
            reply_status="pending",
        )

        r = client.post(f"/api/conversations/{conv.conv_id}/approve-reply")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        cached = app.state.tracker.get_hr_conversation(conv.conv_id)
        assert cached is not None
        assert cached.reply_status == "approved"

    def test_revise_reply_endpoint_updates_draft(self, client):
        conv = _conv()
        app.state.tracker.upsert_hr_conversation(conv)
        app.state.tracker.update_hr_analysis(
            conv.conv_id,
            "greeting",
            "你好，感谢联系。",
            reply_status="pending",
        )

        r = client.post(f"/api/conversations/{conv.conv_id}/revise-reply", json={"draft": "我周四下午方便。"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

        cached = app.state.tracker.get_hr_conversation(conv.conv_id)
        assert cached is not None
        assert cached.reply_status == "revision"
        assert cached.reply_text == "我周四下午方便。"

    def test_dismiss_reply_endpoint_marks_dismissed(self, client):
        conv = _conv()
        app.state.tracker.upsert_hr_conversation(conv)
        app.state.tracker.update_hr_analysis(
            conv.conv_id,
            "greeting",
            "你好，感谢联系。",
            reply_status="pending",
        )

        r = client.post(f"/api/conversations/{conv.conv_id}/dismiss-reply")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        cached = app.state.tracker.get_hr_conversation(conv.conv_id)
        assert cached is not None
        assert cached.reply_status == "dismissed"

    def test_mark_sent_endpoint_clears_reply_fields(self, client):
        conv = _conv()
        app.state.tracker.upsert_hr_conversation(conv)
        app.state.tracker.update_hr_analysis(
            conv.conv_id,
            "greeting",
            "你好，感谢联系。",
            reply_status="approved",
        )
        app.state.tracker.update_reply_approval(conv.conv_id, "revision", "我周四下午方便。")

        r = client.post(f"/api/conversations/{conv.conv_id}/mark-sent")
        assert r.status_code == 200
        assert r.json()["ok"] is True

        cached = app.state.tracker.get_hr_conversation(conv.conv_id)
        assert cached is not None
        assert cached.reply_status == "sent"
        assert cached.reply_text == ""


# ── Pending applications（多站点扩展 Layer 2 审批队列）──────────────────────────

def _pending_fields() -> list:
    return [
        {"field_id": "name", "label": "姓名", "kind": "demographic", "candidate_value": "张三"},
        {"field_id": "id_number", "label": "证件号码", "kind": "government_id", "candidate_value": ""},
    ]


class TestPendingApplications:
    def test_empty_list(self, client):
        r = client.get("/api/pending-applications")
        assert r.status_code == 200
        assert r.json() == {"applications": [], "total": 0}

    def test_list_filters_by_status(self, client):
        id1 = app.state.tracker.add_pending_application(
            site_name="huawei", job_title="后端工程师", fields=_pending_fields(),
        )
        app.state.tracker.add_pending_application(
            site_name="hytera", job_title="测试工程师", fields=_pending_fields(),
        )
        app.state.tracker.decide_pending_application(id1, "approved", fields=_pending_fields())

        r = client.get("/api/pending-applications?status=pending")
        data = r.json()
        assert data["total"] == 1
        assert data["applications"][0]["site_name"] == "hytera"

    def test_get_single_application(self, client):
        app_id = app.state.tracker.add_pending_application(
            site_name="huawei", job_title="后端工程师", fields=_pending_fields(),
        )
        r = client.get(f"/api/pending-applications/{app_id}")
        assert r.status_code == 200
        assert r.json()["site_name"] == "huawei"

    def test_get_nonexistent_returns_404(self, client):
        r = client.get("/api/pending-applications/999")
        assert r.status_code == 404

    def test_approve_writes_final_fields(self, client):
        app_id = app.state.tracker.add_pending_application(
            site_name="huawei", job_title="后端工程师", fields=_pending_fields(),
        )
        edited = _pending_fields()
        edited[1]["candidate_value"] = "110101199001011234"

        r = client.post(f"/api/pending-applications/{app_id}/approve", json={"fields": edited})
        assert r.status_code == 200
        assert r.json()["ok"] is True

        rec = app.state.tracker.get_pending_application(app_id)
        assert rec.status == "approved"
        assert rec.fields[1]["candidate_value"] == "110101199001011234"

    def test_approve_saves_new_demographic_fact_to_personal_info(self, client):
        """审批人填的、personal_info 里原来没有的 demographic 字段，批准时应
        自动存回 identity.yaml——用户 2026-08-13 提出的自动保存需求。"""
        app_id = app.state.tracker.add_pending_application(
            site_name="bambulab", job_title="项目管理", fields=[
                {"field_id": "学校名称", "label": "学校名称", "kind": "demographic", "candidate_value": "深圳大学"},
            ],
        )
        r = client.post(
            f"/api/pending-applications/{app_id}/approve",
            json={"fields": [{"field_id": "学校名称", "label": "学校名称", "kind": "demographic", "candidate_value": "深圳大学"}]},
        )
        assert r.status_code == 200
        assert r.json()["saved_new_facts"] == ["学校名称"]

        from multisite.personal_info_loader import load_personal_info
        result = load_personal_info(srv.DATA_DIR / "personal_info", srv.DATA_DIR / "info_pool.yaml")
        assert result["学校名称"] == "深圳大学"

    def test_approve_does_not_save_government_id_or_open_question(self, client):
        app_id = app.state.tracker.add_pending_application(
            site_name="bambulab", job_title="项目管理", fields=[
                {"field_id": "身份证号", "label": "身份证号", "kind": "government_id", "candidate_value": "110101199001011234"},
                {"field_id": "自我评价", "label": "自我评价", "kind": "open_question", "candidate_value": "熟悉后端开发"},
            ],
        )
        r = client.post(
            f"/api/pending-applications/{app_id}/approve",
            json={"fields": [
                {"field_id": "身份证号", "label": "身份证号", "kind": "government_id", "candidate_value": "110101199001011234"},
                {"field_id": "自我评价", "label": "自我评价", "kind": "open_question", "candidate_value": "熟悉后端开发"},
            ]},
        )
        assert r.status_code == 200
        assert r.json()["saved_new_facts"] == []

        from multisite.personal_info_loader import load_personal_info
        result = load_personal_info(srv.DATA_DIR / "personal_info", srv.DATA_DIR / "info_pool.yaml")
        assert result == {}

    def test_approve_requires_fields_list(self, client):
        app_id = app.state.tracker.add_pending_application(
            site_name="huawei", job_title="后端工程师", fields=_pending_fields(),
        )
        r = client.post(f"/api/pending-applications/{app_id}/approve", json={})
        assert r.status_code == 400

    def test_reject_records_reason(self, client):
        app_id = app.state.tracker.add_pending_application(
            site_name="huawei", job_title="后端工程师", fields=_pending_fields(),
        )
        r = client.post(f"/api/pending-applications/{app_id}/reject", json={"reason": "岗位不合适"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

        rec = app.state.tracker.get_pending_application(app_id)
        assert rec.status == "rejected"
        assert rec.reason == "岗位不合适"

    def test_reject_without_body(self, client):
        app_id = app.state.tracker.add_pending_application(
            site_name="huawei", job_title="后端工程师", fields=_pending_fields(),
        )
        r = client.post(f"/api/pending-applications/{app_id}/reject")
        assert r.status_code == 200

    def test_approve_already_decided_returns_409(self, client):
        app_id = app.state.tracker.add_pending_application(
            site_name="huawei", job_title="后端工程师", fields=_pending_fields(),
        )
        app.state.tracker.decide_pending_application(app_id, "rejected")

        r = client.post(f"/api/pending-applications/{app_id}/approve", json={"fields": _pending_fields()})
        assert r.status_code == 409

    def test_actions_on_nonexistent_return_404(self, client):
        r = client.post("/api/pending-applications/999/approve", json={"fields": []})
        assert r.status_code == 404
        r = client.post("/api/pending-applications/999/reject")
        assert r.status_code == 404


# ── Personal info（多站点扩展表单填写用的身份事实，跟 info_pool 去重后）──────────

class TestPersonalInfo:
    def test_empty_state(self, client):
        r = client.get("/api/personal-info")
        assert r.status_code == 200
        assert r.json() == {"basic": {"name": "", "phone": "", "email": ""}, "identity": {}}

    def test_basic_reflects_info_pool(self, client):
        pool_path = srv.DATA_DIR / "info_pool.yaml"
        pool_path.parent.mkdir(parents=True, exist_ok=True)
        pool_path.write_text(
            yaml.safe_dump({"basic_info": {"name": "张三", "phone": "13800000000", "email": "zhangsan@example.com", "city": "深圳"}}, allow_unicode=True),
            encoding="utf-8",
        )
        r = client.get("/api/personal-info")
        assert r.status_code == 200
        assert r.json()["basic"] == {"name": "张三", "phone": "13800000000", "email": "zhangsan@example.com"}

    def test_save_and_reload_identity(self, client):
        r = client.put("/api/personal-info", json={"identity": {"gender": "男", "birth_date": "2000-01-01"}})
        assert r.status_code == 200
        assert r.json()["identity"] == {"gender": "男", "birth_date": "2000-01-01"}

        r = client.get("/api/personal-info")
        assert r.json()["identity"] == {"gender": "男", "birth_date": "2000-01-01"}

    def test_save_rejects_government_id_field(self, client):
        r = client.put("/api/personal-info", json={"identity": {"id_number": "110101199001011234"}})
        assert r.status_code == 400
        assert client.get("/api/personal-info").json()["identity"] == {}

    def test_save_requires_identity_object(self, client):
        r = client.put("/api/personal-info", json={})
        assert r.status_code == 400


# ── Workflow status / stop / trigger ─────────────────────────────────────────

class TestWorkflow:
    def test_status_not_running(self, client):
        r = client.get("/api/workflow/status")
        assert r.status_code == 200
        assert r.json()["running"] is None

    def test_stop_when_no_workflow(self, client):
        r = client.post("/api/workflow/stop")
        assert r.status_code == 200
        assert r.json()["ok"] is False

    def test_stop_when_workflow_running(self, client):
        app.state.emitter.current_workflow = "apply"
        r = client.post("/api/workflow/stop")
        assert r.json()["ok"] is True
        assert r.json()["stopping"] == "apply"
        app.state.emitter.current_workflow = None  # cleanup

    def test_apply_starts_and_returns_started(self, client):
        # Idle queue -> the item runs immediately, so the response says "started".
        # Patch the runner and wait for the worker to consume the item under the
        # patch so no real W1 run leaks out after the patch context exits.
        import threading
        ran = threading.Event()
        # The runner now lives on OrchestrationService; patch it there. It returns a
        # (log_line, summary) pair, which the queue runner unpacks.
        with patch("services.workflow_orchestration.OrchestrationService._run_apply_workflow",
                   side_effect=lambda *a, **k: (ran.set(), ("ok", {}))[1]):
            r = client.post("/api/workflow/apply", json={})
            assert r.status_code == 200
            assert r.json()["status"] == "started"
            assert ran.wait(5)
        # run_item sets the mutex; the patched runner skips finish, so clear it.
        app.state.emitter.current_workflow = None

    def test_apply_dry_run_flag_propagated(self, client):
        # Hold the worker (busy) so the enqueued item stays pending and inspectable.
        app.state.emitter.current_workflow = "busy"
        try:
            client.post("/api/workflow/apply", json={"dry_run": True})
            pending = app.state.workflow_queue.snapshot()["pending"]
            assert pending and pending[0]["params"]["dry_run"] is True
        finally:
            app.state.workflow_queue.clear()
            app.state.emitter.current_workflow = None

    def test_apply_enqueues_when_busy(self, client):
        # No longer 409s: a trigger while another workflow runs enqueues behind it.
        app.state.emitter.current_workflow = "w2"
        try:
            r = client.post("/api/workflow/apply", json={})
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "queued"
            assert body["running"] is True
            assert len(app.state.workflow_queue.snapshot()["pending"]) == 1
        finally:
            app.state.workflow_queue.clear()
            app.state.emitter.current_workflow = None

    def test_check_starts_and_returns_started(self, client):
        import threading
        ran = threading.Event()
        with patch("services.workflow_orchestration.OrchestrationService._run_check_workflow",
                   side_effect=lambda *a, **k: (ran.set(), ("ok", {}))[1]):
            r = client.post("/api/workflow/check", json={})
            assert r.status_code == 200
            assert r.json()["status"] == "started"
            assert ran.wait(5)
        app.state.emitter.current_workflow = None

    def test_check_enqueues_when_busy(self, client):
        app.state.emitter.current_workflow = "w1"
        try:
            r = client.post("/api/workflow/check", json={})
            assert r.status_code == 200
            assert r.json()["status"] == "queued"
            assert len(app.state.workflow_queue.snapshot()["pending"]) == 1
        finally:
            app.state.workflow_queue.clear()
            app.state.emitter.current_workflow = None

    def test_apply_limit_none_when_zero(self, client):
        """apply_limit=0 should be treated as no limit (None) in the enqueued params."""
        app.state.emitter.current_workflow = "busy"
        try:
            client.post("/api/workflow/apply", json={"apply_limit": 0})
            pending = app.state.workflow_queue.snapshot()["pending"]
            assert pending and pending[0]["params"]["max_cards"] is None
        finally:
            app.state.workflow_queue.clear()
            app.state.emitter.current_workflow = None

    def test_apply_limit_passed_when_positive(self, client):
        app.state.emitter.current_workflow = "busy"
        try:
            client.post("/api/workflow/apply", json={"apply_limit": 3})
            pending = app.state.workflow_queue.snapshot()["pending"]
            assert pending and pending[0]["params"]["max_cards"] == 3
        finally:
            app.state.workflow_queue.clear()
            app.state.emitter.current_workflow = None


# ── Session check ─────────────────────────────────────────────────────────────

class TestSessionCheck:
    def test_session_check_valid_session(self, client):
        mock_result = {"valid": True, "name": "张三", "degree": "本科"}
        with patch("dashboard.server._check_session_via_browser", return_value=mock_result):
            r = client.get("/api/check/session")
        assert r.status_code == 200
        data = r.json()
        assert data["valid"] is True
        assert data["name"] == "张三"

    def test_session_check_invalid_session(self, client):
        mock_result = {"valid": False, "reason": "跳转到登录页"}
        with patch("dashboard.server._check_session_via_browser", return_value=mock_result):
            r = client.get("/api/check/session")
        assert r.json()["valid"] is False

    def test_session_check_blocked_by_workflow_running(self, client):
        app.state.emitter.current_workflow = "w1"
        try:
            r = client.get("/api/check/session")
            assert r.status_code == 200
            data = r.json()
            assert data["valid"] is None
            assert "运行" in data["reason"]
        finally:
            app.state.emitter.current_workflow = None


# ── Preview search ────────────────────────────────────────────────────────────

class TestPreviewSearch:
    def test_preview_no_chrome_returns_500(self, client):
        with patch("dashboard.server._find_chrome_exe", return_value=None):
            r = client.post("/api/preview/search")
        assert r.status_code == 500
        assert "Chrome" in r.json()["detail"]

    def test_preview_ok_returns_url(self, client, tmp_path):
        fake_chrome = str(tmp_path / "chrome.exe")

        with patch("dashboard.server._find_chrome_exe", return_value=fake_chrome), \
             patch("subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock()
            r = client.post("/api/preview/search")

        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert "zhipin.com" in data["url"]
        mock_popen.assert_called_once()

    def test_preview_url_uses_profile_keywords(self, client, tmp_path):
        (tmp_path / "data" / "profile.yaml").write_text(
            "keywords: [Python]\ncities: [北京]\n", encoding="utf-8"
        )
        fake_chrome = str(tmp_path / "chrome.exe")

        with patch("dashboard.server._find_chrome_exe", return_value=fake_chrome), \
             patch("subprocess.Popen", return_value=MagicMock()):
            r = client.post("/api/preview/search")

        assert "Python" in r.json()["url"]


# ── Checkpoint 1：选岗审批（pending_jobs）─────────────────────────────────────

def _add_job(url="https://x/1", category="产品", **kw):
    return app.state.tracker.add_pending_job(site_name="bambulab", url=url, category=category, **kw)


class TestCheckpoint1Jobs:
    def test_empty_list_still_returns_categories(self, client):
        """列表空的时候类别表也必须有——前端的类别下拉靠它渲染，返回空列表会让
        "还没跑过选岗"表现成"下拉是空的"，两种完全不同的情况长得一样。"""
        r = client.get("/api/checkpoint1/jobs")
        assert r.status_code == 200
        data = r.json()
        assert data["jobs"] == [] and data["total"] == 0
        assert isinstance(data["categories"], list)

    def test_list_returns_both_category_columns(self, client):
        _add_job(category="产品", title="产品经理")
        job = client.get("/api/checkpoint1/jobs").json()["jobs"][0]
        assert job["category"] == "产品"
        assert job["category_agent"] == "产品"

    def test_list_filters_by_status(self, client):
        a = _add_job(url="https://x/1")
        _add_job(url="https://x/2")
        app.state.tracker.decide_pending_job(a, "approved")

        assert client.get("/api/checkpoint1/jobs").json()["total"] == 2
        assert client.get("/api/checkpoint1/jobs?status=pending").json()["total"] == 1
        assert client.get("/api/checkpoint1/jobs?status=approved").json()["total"] == 1

    def test_approve_without_category_keeps_agent_value(self, client):
        job_id = _add_job(category="产品")
        r = client.post(f"/api/checkpoint1/jobs/{job_id}/approve", json={})
        assert r.status_code == 200 and r.json()["ok"] is True

        job = app.state.tracker.get_pending_job(job_id)
        assert job.status == "approved"
        assert job.category == "产品" and job.category_agent == "产品"

    def test_approve_with_corrected_category_never_touches_agent_value(self, client):
        """整条链上唯一的归类纠错点。改完还要能看出 agent 当初报的是什么，
        否则纠错信号当场蒸发（用户 2026-08-14 要求留作训练数据）。"""
        job_id = _add_job(category="开发")
        r = client.post(f"/api/checkpoint1/jobs/{job_id}/approve", json={"category": "AI NATIVE"})
        assert r.status_code == 200

        job = app.state.tracker.get_pending_job(job_id)
        assert job.category == "AI NATIVE"
        assert job.category_agent == "开发"

    def test_reject_records_reason(self, client):
        job_id = _add_job()
        r = client.post(f"/api/checkpoint1/jobs/{job_id}/reject", json={"reason": "其实是客服岗"})
        assert r.status_code == 200

        job = app.state.tracker.get_pending_job(job_id)
        assert job.status == "rejected" and job.reason == "其实是客服岗"

    def test_missing_job_is_404(self, client):
        assert client.post("/api/checkpoint1/jobs/9999/approve", json={}).status_code == 404
        assert client.post("/api/checkpoint1/jobs/9999/reject", json={}).status_code == 404

    def test_deciding_twice_is_409(self, client):
        job_id = _add_job()
        assert client.post(f"/api/checkpoint1/jobs/{job_id}/approve", json={}).status_code == 200
        assert client.post(f"/api/checkpoint1/jobs/{job_id}/reject", json={}).status_code == 409


class TestCheckpoint1Batch:
    def test_batch_approve_applies_per_job_categories(self, client):
        a = _add_job(url="https://x/1", category="开发")
        b = _add_job(url="https://x/2", category="开发")

        r = client.post("/api/checkpoint1/batch", json={
            "decision": "approved", "ids": [a, b],
            "categories": {str(a): "AI NATIVE"},
        })
        assert r.status_code == 200
        assert sorted(r.json()["decided"]) == sorted([a, b])

        assert app.state.tracker.get_pending_job(a).category == "AI NATIVE"
        assert app.state.tracker.get_pending_job(b).category == "开发"
        # 两条的 agent 原值都得留着
        assert app.state.tracker.get_pending_job(a).category_agent == "开发"

    def test_already_decided_rows_are_skipped_not_fatal(self, client):
        """批量的语义是"把这些都处理掉"。一条冲突就整批打回，会留下一半已处理
        一半没处理的状态，比跳过更难收拾。"""
        a = _add_job(url="https://x/1")
        b = _add_job(url="https://x/2")
        app.state.tracker.decide_pending_job(a, "approved")

        r = client.post("/api/checkpoint1/batch", json={"decision": "approved", "ids": [a, b]})
        assert r.status_code == 200
        data = r.json()
        assert data["decided"] == [b]
        assert data["skipped"] == [a]

    def test_nonexistent_ids_are_skipped(self, client):
        a = _add_job()
        r = client.post("/api/checkpoint1/batch", json={"decision": "approved", "ids": [a, 9999]})
        assert r.json()["decided"] == [a] and r.json()["skipped"] == [9999]

    def test_batch_reject_records_shared_reason(self, client):
        a = _add_job(url="https://x/1")
        b = _add_job(url="https://x/2")
        client.post("/api/checkpoint1/batch", json={
            "decision": "rejected", "ids": [a, b], "reason": "方向不符",
        })
        for job_id in (a, b):
            job = app.state.tracker.get_pending_job(job_id)
            assert job.status == "rejected" and job.reason == "方向不符"

    def test_invalid_decision_is_400(self, client):
        assert client.post("/api/checkpoint1/batch",
                           json={"decision": "maybe", "ids": [1]}).status_code == 400

    def test_empty_ids_is_400(self, client):
        assert client.post("/api/checkpoint1/batch",
                           json={"decision": "approved", "ids": []}).status_code == 400


class TestCheckpoint1Review:
    def test_review_corrects_category_without_deciding(self, client):
        """改类别和批准是两件事：批准之前先纠正、或批准之后才发现归错了，
        都得能单独做。"""
        job_id = _add_job(category="开发")
        r = client.post(f"/api/checkpoint1/jobs/{job_id}/review", json={"category": "AI NATIVE"})
        assert r.status_code == 200

        job = app.state.tracker.get_pending_job(job_id)
        assert job.category == "AI NATIVE"
        assert job.category_agent == "开发"
        assert job.status == "pending", "review 不该动审批状态"

    def test_marking_golden_returns_the_updated_row(self, client):
        # 前端拿返回值直接替换本地那一行，不重新拉整个列表。
        job_id = _add_job(category="开发")
        r = client.post(f"/api/checkpoint1/jobs/{job_id}/review",
                        json={"category": "AI NATIVE", "is_golden": True})
        assert r.json()["job"]["is_golden"] is True
        assert r.json()["job"]["category"] == "AI NATIVE"

    def test_golden_row_reaches_the_prompt(self, client):
        """端到端：页面上点"确认"之后，这条纠正真的会出现在选岗 agent 的 prompt 里。
        少了这一环，整个 golden set 就只是个没人读的标记。"""
        from multisite.preferences import render_golden_examples

        job_id = _add_job(category="开发", title="数据算法工程师")
        client.post(f"/api/checkpoint1/jobs/{job_id}/review",
                    json={"category": "AI NATIVE", "is_golden": True})

        text = render_golden_examples(app.state.tracker)
        assert "数据算法工程师" in text
        assert "AI NATIVE" in text and "开发" in text

    def test_unconfirmed_correction_stays_out_of_the_prompt(self, client):
        from multisite.preferences import render_golden_examples

        job_id = _add_job(category="开发", title="仿真算法工程师")
        client.post(f"/api/checkpoint1/jobs/{job_id}/review", json={"category": "AI NATIVE"})

        assert "仿真算法工程师" not in render_golden_examples(app.state.tracker)

    def test_undo_golden(self, client):
        from multisite.preferences import render_golden_examples

        job_id = _add_job(category="开发", title="图形算法工程师")
        client.post(f"/api/checkpoint1/jobs/{job_id}/review",
                    json={"category": "AI NATIVE", "is_golden": True})
        client.post(f"/api/checkpoint1/jobs/{job_id}/review", json={"is_golden": False})

        assert app.state.tracker.get_pending_job(job_id).category == "AI NATIVE", \
            "撤销 golden 不该把类别也退回去"
        assert "图形算法工程师" not in render_golden_examples(app.state.tracker)

    def test_empty_patch_is_400(self, client):
        job_id = _add_job()
        assert client.post(f"/api/checkpoint1/jobs/{job_id}/review", json={}).status_code == 400

    def test_missing_job_is_404(self, client):
        assert client.post("/api/checkpoint1/jobs/9999/review",
                           json={"is_golden": True}).status_code == 404


class TestCheckpoint1Sites:
    """站点信息（投递上限 + 现场笔记）。

    **一个站可能有好几条互不相干的上限**：真机拿到的第一条证据就是
    「在"27届秋招（研发类）"**招聘项目中**……最多可以投递 2 次」——按站点存
    会把研发类和非研发类的额度当成同一个，低估实际可投数。
    """

    def test_site_appears_even_with_no_limit_recorded(self, client):
        """有岗位但没读到上限时，站点本身也得出现。
        整个 key 缺失的话前端什么都不显示，看起来跟“没有限制”一样。"""
        _add_job()
        info = client.get("/api/checkpoint1/jobs").json()["sites"]["bambulab"]
        assert info["limits"] == [], "没记到就是空列表，不是编一条 unknown"
        assert info["brief"] is None

    def test_returns_the_recorded_limit_with_scope(self, client):
        _add_job()
        app.state.tracker.upsert_site_limit(
            "bambulab", "limited", scope="bucket", scope_name="27届秋招（研发类）",
            max_applications=2, applied_count=0, evidence="最多可以投递 2 次")
        limits = client.get("/api/checkpoint1/jobs").json()["sites"]["bambulab"]["limits"]
        assert len(limits) == 1
        assert limits[0]["scope"] == "bucket"
        assert limits[0]["scope_name"] == "27届秋招（研发类）"
        assert limits[0]["max_applications"] == 2

    def test_one_site_can_carry_several_bucket_limits(self, client):
        """这条就是主键从 site_name 改成 (site_name, scope_name) 的理由。"""
        _add_job()
        t = app.state.tracker
        t.upsert_site_limit("bambulab", "limited", scope="bucket",
                            scope_name="研发类", max_applications=2, evidence="e1")
        t.upsert_site_limit("bambulab", "limited", scope="bucket",
                            scope_name="非研发类", max_applications=2, evidence="e2")
        limits = client.get("/api/checkpoint1/jobs").json()["sites"]["bambulab"]["limits"]
        assert sorted(l["scope_name"] for l in limits) == ["研发类", "非研发类"]

    def test_approved_count_is_global_not_filtered(self, client):
        """**这条守的是一个真会犯的错**：approved_here 如果数的是过滤后的
        列表，看「待审批」页时分母恒为 0，超额告警永远不会亮。"""
        a = _add_job(url="https://x/1")
        _add_job(url="https://x/2")
        app.state.tracker.decide_pending_job(a, "approved")

        r = client.get("/api/checkpoint1/jobs?status=pending").json()
        assert len(r["jobs"]) == 1
        assert r["sites"]["bambulab"]["approved_here"] == 1

    def test_counts_are_per_site(self, client):
        a = app.state.tracker.add_pending_job(site_name="siteA", url="https://a/1")
        app.state.tracker.add_pending_job(site_name="siteB", url="https://b/1")
        app.state.tracker.decide_pending_job(a, "approved")

        sites = client.get("/api/checkpoint1/jobs").json()["sites"]
        assert sites["siteA"]["approved_here"] == 1
        assert sites["siteB"]["approved_here"] == 0

    def test_brief_is_returned(self, client):
        _add_job()
        app.state.tracker.upsert_site_brief("bambulab", "分成研发类和非研发类两个招聘项目。")
        info = client.get("/api/checkpoint1/jobs").json()["sites"]["bambulab"]
        assert "非研发类" in info["brief"]["brief"]


class TestCheckpoint1ManualSiteLimit:
    """人工填写上限。

    存在理由：**不能假设 agent 一定拿得到我们以为它拿得到的信息**
    （用户 2026-08-14）。三态保证了“没找到”不会被伪装成“没有限制”，
    但只做到诚实不够——人得有地方把自己知道的填进去。
    """

    def test_set_a_limit_manually(self, client):
        r = client.put("/api/checkpoint1/site-limit/bambulab",
                       json={"status": "limited", "max_applications": 3, "evidence": "我自己看的"})
        assert r.status_code == 200
        got = app.state.tracker.get_site_limit("bambulab")
        assert got.status == "limited" and got.max_applications == 3
        assert got.evidence == "我自己看的"

    def test_set_no_limit(self, client):
        client.put("/api/checkpoint1/site-limit/s", json={"status": "no_limit"})
        got = app.state.tracker.get_site_limit("s")
        assert got.status == "no_limit" and got.max_applications is None

    def test_reset_to_unknown_actually_clears_it(self, client):
        """人主动退回未知必须真的清掉。tracker 里那条
        “unknown 不覆盖已知”保护是防 agent 用无知覆盖已知，
        不该拦住人的主动重置。"""
        client.put("/api/checkpoint1/site-limit/s", json={"status": "limited", "max_applications": 3})
        client.put("/api/checkpoint1/site-limit/s", json={"status": "unknown"})
        assert app.state.tracker.get_site_limit("s") is None

    def test_limited_without_a_number_is_400(self, client):
        r = client.put("/api/checkpoint1/site-limit/s", json={"status": "limited"})
        assert r.status_code == 400
        assert app.state.tracker.get_site_limit("s") is None

    def test_bad_status_is_400(self, client):
        assert client.put("/api/checkpoint1/site-limit/s",
                          json={"status": "maybe"}).status_code == 400

    def test_manual_value_shows_up_in_the_list_response(self, client):
        _add_job()
        client.put("/api/checkpoint1/site-limit/bambulab",
                   json={"status": "limited", "max_applications": 3})
        limits = client.get("/api/checkpoint1/jobs").json()["sites"]["bambulab"]["limits"]
        assert len(limits) == 1
        assert limits[0]["status"] == "limited" and limits[0]["max_applications"] == 3


class TestApproveEnqueuesFill:
    """批准一个岗位 = 给它排一个 m2（填表）任务。

    没有这一步的话，“批准”只是把行标成 approved，之后永远不会有任何
    事发生——这正是 2026-08-14 之前的真实状态（库里躺着一条 approved 没人管）。

    **每个用例都必须挂住 worker**（`emitter.current_workflow` 置为真值）：
    不挂的话队列会真的把 m2 捡起来执行，而 m2 会通过 npx 启动一个真实
    Chrome。这是本文件已有的约定（见 test_apply_dry_run_flag_propagated），
    我第一版漏了，测试当场就把任务跑掉了。
    """

    @staticmethod
    def _pending():
        return app.state.workflow_queue.snapshot()["pending"]

    @pytest.fixture(autouse=True)
    def _hold_worker(self, client):
        # **必须依赖 client**：autouse fixture 默认排在显式请求的 fixture 前面，
        # 而 client 会重建 app.state.emitter，把这里设的 busy 标志冲掉——worker
        # 于是照常把 m2 捡起来跑（去启动真实 Chrome）。加上这个参数强制排在它后面。
        app.state.emitter.current_workflow = "busy"
        try:
            yield
        finally:
            app.state.workflow_queue.clear()
            app.state.emitter.current_workflow = None

    def test_single_approve_queues_one_fill_item(self, client):
        job_id = _add_job()
        r = client.post(f"/api/checkpoint1/jobs/{job_id}/approve", json={})
        assert r.status_code == 200

        queued = r.json()["queued"]
        assert len(queued) == 1 and queued[0]["job_id"] == job_id
        pending = self._pending()
        assert [it["workflow"] for it in pending] == ["m2"]
        assert pending[0]["params"]["pending_job_id"] == job_id

    def test_batch_approve_queues_one_item_per_job(self, client):
        """一个岗位一个 item，不是一个 item 处理一批——中途哪个挂了
        一目了然，也不用回答“第 3 个挂了后面还跑不跑”。"""
        ids = [_add_job(url=f"https://x/{i}") for i in range(3)]
        r = client.post("/api/checkpoint1/batch", json={"decision": "approved", "ids": ids})

        assert len(r.json()["queued"]) == 3
        pending = self._pending()
        assert len(pending) == 3
        assert sorted(it["params"]["pending_job_id"] for it in pending) == sorted(ids)

    def test_reject_queues_nothing(self, client):
        job_id = _add_job()
        client.post(f"/api/checkpoint1/jobs/{job_id}/reject", json={"reason": "x"})
        assert self._pending() == []

    def test_batch_reject_queues_nothing(self, client):
        ids = [_add_job(url=f"https://x/{i}") for i in range(2)]
        client.post("/api/checkpoint1/batch", json={"decision": "rejected", "ids": ids})
        assert self._pending() == []

    def test_already_decided_job_is_not_queued(self, client):
        # 409 那条路径不能顺手再排一个填表任务。
        job_id = _add_job()
        client.post(f"/api/checkpoint1/jobs/{job_id}/approve", json={})
        before = len(self._pending())
        assert client.post(f"/api/checkpoint1/jobs/{job_id}/approve", json={}).status_code == 409
        assert len(self._pending()) == before

    def test_enqueue_can_be_turned_off(self, client):
        # 只想标个 approved 不想现在跑（比如批一堆然后晚上再跑）。
        job_id = _add_job()
        r = client.post(f"/api/checkpoint1/jobs/{job_id}/approve", json={"enqueue": False})
        assert r.json()["queued"] == []
        assert self._pending() == []


class TestCheckpoint1BucketCounts:
    """按招聘项目分别统计已批准数。

    投递上限常常是按项目算的（拓竹：「在"27届秋招（研发类）"招聘项目中
    最多可以投递 2 次」）。拿全站总数去比一个项目的上限会**低估**额度——
    研发类 2 个 + 非研发类 1 个，两个桶都没满，却会报“超了 1 个”。
    """

    def test_counts_are_split_by_bucket(self, client):
        t = app.state.tracker
        a = t.add_pending_job(site_name="bambulab", url="https://x/1", bucket="研发类")
        b = t.add_pending_job(site_name="bambulab", url="https://x/2", bucket="研发类")
        c = t.add_pending_job(site_name="bambulab", url="https://x/3", bucket="非研发类")
        for jid in (a, b, c):
            t.decide_pending_job(jid, "approved")

        info = client.get("/api/checkpoint1/jobs").json()["sites"]["bambulab"]
        assert info["approved_here"] == 3
        assert info["approved_by_bucket"] == {"研发类": 2, "非研发类": 1}
        assert info["buckets"] == ["研发类", "非研发类"] or info["buckets"] == ["非研发类", "研发类"]

    def test_legacy_rows_without_bucket_land_in_their_own_slot(self, client):
        """bucket='' 是加这一列之前的旧数据。它们算不进任何项目的名额，
        得单独分一档让前端能说清楚，而不是静默归到某个桶里。"""
        t = app.state.tracker
        old = t.add_pending_job(site_name="bambulab", url="https://x/1")  # 没 bucket
        t.decide_pending_job(old, "approved")

        info = client.get("/api/checkpoint1/jobs").json()["sites"]["bambulab"]
        assert info["approved_by_bucket"] == {"": 1}
        assert info["buckets"] == []

    def test_pending_jobs_are_not_counted(self, client):
        t = app.state.tracker
        t.add_pending_job(site_name="bambulab", url="https://x/1", bucket="研发类")
        info = client.get("/api/checkpoint1/jobs").json()["sites"]["bambulab"]
        assert info["approved_by_bucket"] == {}

    def test_bucket_reaches_the_job_payload(self, client):
        # 前端要按岗位的 bucket 把"本次选中"分摊到各个项目上。
        t = app.state.tracker
        t.add_pending_job(site_name="bambulab", url="https://x/1", bucket="研发类")
        job = client.get("/api/checkpoint1/jobs").json()["jobs"][0]
        assert job["bucket"] == "研发类"


class TestPoolPendingFlow:
    """机器改池必须走人工确认。

    池是求职者全部信息的唯一主库，而 build_pool 让 LLM **整体重写 sections**，
    一次错误保存就把内容覆盖掉了。原先只有"写前快照 + 事后回滚"，那是
    发现丢了东西之后的补救（用户 2026-08-15）。
    """

    @staticmethod
    def _seed_pool(sections=None, **basic):
        from services import info_pool
        pool = {"basic_info": dict(basic), "self_description": "",
                "sections": list(sections or [])}
        info_pool.save_pool(pool, str(srv.DATA_DIR / "info_pool.yaml"))
        return pool

    @staticmethod
    def _seed_pending(proposed, source="build"):
        from services import pool_diff
        return pool_diff.save_pending(proposed, source=source,
                                      pool_path=str(srv.DATA_DIR / "info_pool.yaml"))

    def test_no_pending_reports_false(self, client):
        assert client.get("/api/pool/pending").json() == {"pending": False}

    def test_pending_returns_a_diff(self, client):
        self._seed_pool([{"name": "教育经历", "blocks": [
            {"title": "甲大学", "time": "", "bullets": ["旧"], "summary": ""}]}])
        self._seed_pending({"basic_info": {}, "self_description": "", "sections": [
            {"name": "教育经历", "blocks": [
                {"title": "甲大学", "time": "", "bullets": ["新"], "summary": ""}]}]})

        r = client.get("/api/pool/pending").json()
        assert r["pending"] is True and r["source"] == "build"
        blk = r["diff"]["sections"][0]["blocks"][0]
        assert blk["kind"] == "changed"
        assert {"op": "+", "text": "新"} in blk["bullets"]

    def test_diff_is_recomputed_against_the_current_pool(self, client):
        """人可能在提案生成之后又手动编辑过池。用当时算好的 diff
        会让他看到一份跟现状对不上的对照。"""
        self._seed_pool(name="张三")
        self._seed_pending({"basic_info": {"name": "李四"}, "self_description": "", "sections": []})
        # 人随后自己把名字也改成了李四 → 提案不再构成变更
        self._seed_pool(name="李四")

        r = client.get("/api/pool/pending").json()
        assert r["diff"]["has_changes"] is False

    def test_apply_only_writes_the_ticked_items(self, client):
        from services import info_pool
        self._seed_pool(name="张三", phone="123")
        self._seed_pending({"basic_info": {"name": "李四", "phone": "999"},
                            "self_description": "", "sections": []})

        r = client.post("/api/pool/pending/apply", json={"accepted": ["basic_info␟name"]})
        assert r.status_code == 200

        # basic_info 会被块库规范化成固定 6 个字段（缺的补空串），所以只比关心的两个。
        pool = info_pool.load_pool(str(srv.DATA_DIR / "info_pool.yaml"))
        assert pool["basic_info"]["name"] == "李四", "勾了的要生效"
        assert pool["basic_info"]["phone"] == "123", "没勾的必须保持现状"
        assert client.get("/api/pool/pending").json() == {"pending": False}, "落盘后提案要清掉"

    def test_apply_nothing_leaves_the_pool_untouched(self, client):
        from services import info_pool
        self._seed_pool(name="张三")
        self._seed_pending({"basic_info": {"name": "李四"}, "self_description": "", "sections": []})

        client.post("/api/pool/pending/apply", json={"accepted": []})
        assert info_pool.load_pool(str(srv.DATA_DIR / "info_pool.yaml"))["basic_info"]["name"] == "张三"

    def test_content_the_proposal_never_mentioned_survives(self, client):
        """**这条守的是整个功能的初衷。** LLM 重写时可能压根不提某个分区，
        那些内容不能因此消失——它们从来没被摆到人面前确认过。"""
        from services import info_pool
        self._seed_pool([
            {"name": "教育经历", "blocks": [{"title": "甲大学", "time": "", "bullets": [], "summary": ""}]},
            {"name": "游戏经历", "blocks": [{"title": "某游戏项目", "time": "", "bullets": [], "summary": ""}]},
        ])
        self._seed_pending({"basic_info": {}, "self_description": "", "sections": [
            {"name": "教育经历", "blocks": [
                {"title": "甲大学", "time": "", "bullets": ["补充"], "summary": ""}]}]})

        client.post("/api/pool/pending/apply", json={"accepted": ["教育经历␟甲大学"]})
        pool = info_pool.load_pool(str(srv.DATA_DIR / "info_pool.yaml"))
        assert [s["name"] for s in pool["sections"]] == ["教育经历", "游戏经历"]

    def test_apply_without_a_pending_is_404(self, client):
        assert client.post("/api/pool/pending/apply",
                           json={"accepted": []}).status_code == 404

    def test_bad_payload_is_400(self, client):
        self._seed_pool()
        self._seed_pending({"basic_info": {"name": "x"}, "self_description": "", "sections": []})
        assert client.post("/api/pool/pending/apply", json={}).status_code == 400

    def test_discard_leaves_the_pool_alone(self, client):
        from services import info_pool
        self._seed_pool(name="张三")
        self._seed_pending({"basic_info": {"name": "李四"}, "self_description": "", "sections": []})

        assert client.delete("/api/pool/pending").status_code == 200
        assert client.get("/api/pool/pending").json() == {"pending": False}
        assert info_pool.load_pool(str(srv.DATA_DIR / "info_pool.yaml"))["basic_info"]["name"] == "张三"

    def test_direct_pool_edit_still_writes_through(self, client):
        """人在池编辑页直接改内容**不走**确认——那时人就是作者，
        给自己的编辑出 diff 让自己确认是纯仪式。"""
        from services import info_pool
        self._seed_pool(name="张三")
        r = client.put("/api/pool", json={"basic_info": {"name": "我自己改的"},
                                          "self_description": "", "sections": []})
        assert r.status_code == 200
        assert info_pool.load_pool(str(srv.DATA_DIR / "info_pool.yaml"))["basic_info"]["name"] == "我自己改的"
        assert client.get("/api/pool/pending").json() == {"pending": False}
