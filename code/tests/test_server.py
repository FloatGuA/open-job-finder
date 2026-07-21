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
    monkeypatch.setattr(srv, "ATTACHMENT_RESUME_PATH", data_dir / "resume_attachment.pdf")
    monkeypatch.setattr(srv, "BOSS_DISTRICTS_PATH", data_dir / "boss_districts.json")
    monkeypatch.setattr(srv, "BOSS_POSITIONS_PATH", data_dir / "boss_positions.json")
    monkeypatch.setattr(srv, "BOSS_INDUSTRIES_PATH", data_dir / "boss_industries.json")
    monkeypatch.setattr(srv, "RUNS_DIR", tmp_path / "runs")
    # Prevent real LLM client creation
    monkeypatch.setattr(srv, "build_model_router", lambda *a, **kw: MagicMock())

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


# ── Attachment resume status ───────────────────────────────────────────────────

class TestAttachmentResume:
    def test_no_local_file(self, client):
        r = client.get("/api/check/attachment-resume")
        assert r.status_code == 200
        data = r.json()
        assert data["local_file"]["exists"] is False
        assert data["local_file"]["size_kb"] == 0

    def test_local_file_exists(self, client, tmp_path):
        attachment = tmp_path / "data" / "resume_attachment.pdf"
        attachment.write_bytes(b"%PDF-1.4 " + b"x" * 2048)  # >1 KB so size_kb rounds to > 0
        r = client.get("/api/check/attachment-resume")
        data = r.json()
        assert data["local_file"]["exists"] is True
        assert data["local_file"]["size_kb"] > 0

    def test_response_contains_boss_profile_url(self, client):
        assert "boss_profile_url" in client.get("/api/check/attachment-resume").json()


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
        with patch("dashboard.server.parse_resume_file", return_value={"name": "张三", "skills": ["Python"]}):
            r = client.post(
                "/api/resume/upload",
                files=_upload_file(b"%PDF-1.4 minimal content", "my_resume.pdf"),
            )
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["attachment_saved"] is True

    def test_upload_docx_ok(self, client):
        with patch("dashboard.server.parse_resume_file", return_value={"name": "李四"}):
            r = client.post(
                "/api/resume/upload",
                files=_upload_file(b"PK fake docx bytes", "cv.docx"),
            )
        assert r.status_code == 200
        assert r.json()["attachment_saved"] is False  # only PDF saves attachment

    def test_upload_pdf_saves_attachment_copy(self, client, tmp_path):
        with patch("dashboard.server.parse_resume_file", return_value={}):
            client.post(
                "/api/resume/upload",
                files=_upload_file(b"%PDF-1.4 content", "resume.pdf"),
            )
        assert (tmp_path / "data" / "resume_attachment.pdf").exists()


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
        with patch("dashboard.server._run_apply_workflow",
                   side_effect=lambda p: (ran.set(), "ok")[1]):
            r = client.post("/api/workflow/apply", json={})
            assert r.status_code == 200
            assert r.json()["status"] == "started"
            assert ran.wait(5)
        # _queue_runner sets the mutex; the patched runner skips finish_workflow, so clear it.
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
        with patch("dashboard.server._run_check_workflow",
                   side_effect=lambda p: (ran.set(), "ok")[1]):
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
