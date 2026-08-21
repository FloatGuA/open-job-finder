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
        # **全程暂停 worker**：它是后台线程，测试结束、monkeypatch 撤销之后才可能
        # 把任务捡起来执行——那时写日志用的已经是恢复后的真实路径，m2 还会去启动
        # 真实浏览器。没有任何测试需要 worker 真的执行，它们只看 snapshot()。
        _q.pause()

    # Redirect every path that server.py resolves at runtime
    monkeypatch.setattr(srv, "DATA_DIR", data_dir)
    monkeypatch.setattr(srv, "CONTROL_PATH", data_dir / "control.json")
    monkeypatch.setattr(srv, "PROFILE_PATH", data_dir / "profile.yaml")
    monkeypatch.setattr(srv, "CONFIG_PATH", tmp_path / "config.yaml")
    monkeypatch.setattr(srv, "BOSS_DISTRICTS_PATH", data_dir / "boss_districts.json")
    monkeypatch.setattr(srv, "BOSS_POSITIONS_PATH", data_dir / "boss_positions.json")
    monkeypatch.setattr(srv, "BOSS_INDUSTRIES_PATH", data_dir / "boss_industries.json")
    monkeypatch.setattr(srv, "RUNS_DIR", tmp_path / "runs")
    # **这三个是模块级常量，_write_schedule_log 等直接读它们**——不重定向的话，
    # 测试里跑出来的每一条调度日志都写进真实的 data/schedule_log.jsonl。
    # 2026-08-15 在真实日志里查出 108 条测试产生的 ms_fill error 才发现，
    # 而且它同时解释了长期没查明的"duration=0 幽灵成功"（2115/2845 条）。
    monkeypatch.setattr(srv, "SCHEDULE_LOG_PATH", data_dir / "schedule_log.jsonl")
    monkeypatch.setattr(srv, "SELFCHECK_LOG_PATH", data_dir / "selfcheck_log.jsonl")
    monkeypatch.setattr(srv, "REGRESSION_SMOKE_LOG", data_dir / "regression_smoke_log.jsonl")
    # OrchestrationService 是模块单例，data_dir 在**首次构建时按值捕获**——不重置的话
    # 后面所有测试都拿着第一个测试（或真实启动）的目录跑，patch 再多也够不着它。
    srv._orch_service = None
    # Prevent real LLM client creation. configured_provider_names() must return a
    # real list (not an auto-generated MagicMock) -- /api/config/llm JSON-encodes it.
    def _fake_router(*a, **kw):
        router = MagicMock()
        router.configured_provider_names.return_value = []
        return router
    monkeypatch.setattr(srv, "build_model_router", _fake_router)

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    # Teardown: 先清空队列再让 monkeypatch 撤销——留在队列里的任务会在补丁失效
    # 之后被 worker 执行，写进真实数据目录。
    _q2 = getattr(app.state, "workflow_queue", None)
    if _q2 is not None:
        _q2.clear()

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


class TestResumePdfStatusApi:
    """简历池要能看到「哪几份真的能发出去」。

    此前界面上有两个互不相干的列表（简历 / 导出存档），**没有任何地方把它们连起来**，
    于是 2026-08-16 那三次 m2 用了一份比简历还旧的 PDF，全程无提示。
    """

    def test_resume_list_carries_pdf_state(self, client):
        from services.resume_store import ResumeStore
        from dashboard.server import DATA_DIR

        item = ResumeStore(str(DATA_DIR)).create("游戏岗版", target="游戏")
        got = client.get("/api/resumes").json()

        entry = next(i for i in got["items"] if i["slug"] == item["slug"])
        assert entry["pdf_state"] == "missing"      # 没导出过 = 发不出去

    def test_export_filename_carries_the_slug(self, client, monkeypatch):
        """导出的文件名要带 slug，否则两份同名简历的 PDF 分不清谁是谁。"""
        from services import resume_tailor
        from services.resume_store import ResumeStore
        from dashboard.server import DATA_DIR

        written = {}

        def fake_render(html, out):
            written["path"] = out
            with open(out, "wb") as f:
                f.write(b"%PDF-1.4")

        monkeypatch.setattr(resume_tailor, "render_html_to_pdf", fake_render)
        item = ResumeStore(str(DATA_DIR)).create("游戏岗版", target="游戏")

        r = client.post("/api/resume/print-pdf",
                        json={"html": "<html></html>", "name": "游戏岗版", "slug": item["slug"]})
        assert r.status_code == 200
        assert item["slug"] in written["path"]

class TestM1ConsoleEntry:
    """m1 从 Dashboard 控制台触发所需的后端支撑。

    m1 的参数里有一个**每次都一样**的东西：站点的招聘入口页。让人每次手打一遍
    URL 是最容易出错的一环（打错了 agent 会在一个不存在的页面上兜圈子直到步数
    耗尽），所以它要能像 W1/W2 的参数一样「设为默认」存下来。
    """

    @pytest.fixture()
    def configured(self, client):
        """「设为默认」的允许键来自 config.yaml 的对应节（w1/w2 同一机制）。
        测试沙箱的 config 是最小的，所以把这个前提显式摆出来——真实部署由下面
        `test_factory_config_declares_m1` 守着。"""
        app.state.config["m1"] = {"site": "", "search_url": "", "max_pages": 8}
        return client

    def test_factory_config_declares_m1(self):
        """出厂 config.yaml 必须有 m1 节：没有它，允许键集合是空的，
        「设为默认」会**静默存不进任何东西**（返回 200，下次打开还是空）。"""
        import yaml

        cfg = yaml.safe_load(
            (Path(__file__).resolve().parent.parent / "config.yaml").read_text(encoding="utf-8"))
        assert set(cfg["m1"]) >= {"site", "search_url", "max_pages"}

    def test_m1_defaults_round_trip(self, configured):
        client = configured
        r = client.post("/api/workflow/defaults", json={
            "workflow": "m1",
            "updates": {"site": "acme", "search_url": "https://acme.example/campus/",
                        "max_pages": 3},
        })
        assert r.status_code == 200
        m1 = r.json()["m1"]
        assert m1["site"] == "acme"
        assert m1["search_url"] == "https://acme.example/campus/"
        assert m1["max_pages"] == 3

    def test_m1_defaults_are_readable_after_saving(self, configured):
        client = configured
        client.post("/api/workflow/defaults", json={
            "workflow": "m1", "updates": {"search_url": "https://acme.example/campus/"}})
        assert client.get("/api/workflow/defaults").json()["m1"]["search_url"] == \
            "https://acme.example/campus/"

    def test_unknown_keys_are_dropped(self, configured):
        client = configured
        # 白名单来自 config.yaml 的 m1 节；垃圾键不该混进 user_settings.yaml。
        r = client.post("/api/workflow/defaults", json={
            "workflow": "m1", "updates": {"search_url": "https://a/", "nonsense": 1}})
        assert "nonsense" not in r.json()["m1"]

    def test_batch_enqueue_accepts_every_valid_workflow(self, client):
        """批量入队的白名单是**第三份**手抄的 workflow 列表（单个入队、run 日志
        筛选各一份）。前两份都因为漏了 m1/m2 出过问题，这份也漏了。"""
        from services.workflow_queue import VALID_WORKFLOWS

        app.state.emitter.current_workflow = 'busy'   # 挂住 worker，别真跑起来
        try:
            r = client.post("/api/workflow/queue/batch", json={
                "items": [{"workflow": wf, "params": {}} for wf in VALID_WORKFLOWS]})
            assert r.status_code == 200, r.text
            assert len(r.json()["ids"]) == len(VALID_WORKFLOWS)
        finally:
            app.state.workflow_queue.clear()
            app.state.emitter.current_workflow = None

    def test_run_logs_can_be_filtered_by_m1_and_m2(self, client):
        # 日志文件叫 m1_*.jsonl，端点的 pipeline 白名单是另写的一份——不同步的
        # 表现是"日志在磁盘上，一按筛选就 400"。
        for wf in ("m1", "m2"):
            assert client.get(f"/api/runs?pipeline={wf}").status_code == 200


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

class TestDiscardPendingApplication:
    """DELETE /api/pending-applications/{id} —— Checkpoint 2 的"这条我不要了"。

    Checkpoint 1 早就有清除入口，Checkpoint 2 只有批准/拒绝——重复记录只能手动
    开库删。补上这条对称的入口（用户 2026-08-22）。
    """

    def _screenshot(self, name: str = "shot.png") -> str:
        from dashboard.server import DATA_DIR

        d = DATA_DIR / "multisite_screenshots"
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(b"\x89PNG\r\n")
        return name

    def test_discard_removes_the_row(self, client):
        app_id = app.state.tracker.add_pending_application(
            site_name="huawei", job_title="后端工程师", fields=_pending_fields(),
        )
        r = client.delete(f"/api/pending-applications/{app_id}")
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert app.state.tracker.get_pending_application(app_id) is None

    def test_discard_takes_the_screenshot_with_it(self, client):
        """截图跟着行一起删——分两处删就会留孤儿。这次清库时手动扫出 3 张没有
        任何行引用的截图，就是没人删过它们。"""
        from dashboard.server import DATA_DIR

        name = self._screenshot()
        app_id = app.state.tracker.add_pending_application(
            site_name="huawei", job_title="后端工程师", fields=_pending_fields(),
            screenshot=name,
        )
        client.delete(f"/api/pending-applications/{app_id}")
        assert not (DATA_DIR / "multisite_screenshots" / name).exists()

    def test_discard_refuses_an_approved_application(self, client):
        """批准过就是给 Layer 3 放行过——那件事撤不回来，记录也不该消失。"""
        app_id = app.state.tracker.add_pending_application(
            site_name="huawei", job_title="后端工程师", fields=_pending_fields(),
        )
        app.state.tracker.decide_pending_application(app_id, "approved", fields=_pending_fields())

        r = client.delete(f"/api/pending-applications/{app_id}")
        assert r.status_code == 409
        assert app.state.tracker.get_pending_application(app_id) is not None

    def test_approved_application_keeps_its_screenshot(self, client):
        """拒绝删这行的时候，截图也不能顺手删掉——否则记录还在、证据没了。"""
        from dashboard.server import DATA_DIR

        name = self._screenshot("approved.png")
        app_id = app.state.tracker.add_pending_application(
            site_name="huawei", job_title="后端工程师", fields=_pending_fields(),
            screenshot=name,
        )
        app.state.tracker.decide_pending_application(app_id, "approved", fields=_pending_fields())

        client.delete(f"/api/pending-applications/{app_id}")
        assert (DATA_DIR / "multisite_screenshots" / name).exists()

    def test_discard_nonexistent_returns_404(self, client):
        r = client.delete("/api/pending-applications/999")
        assert r.status_code == 404

    def test_discard_a_rejected_application(self, client):
        app_id = app.state.tracker.add_pending_application(
            site_name="huawei", job_title="后端工程师", fields=_pending_fields(),
        )
        app.state.tracker.decide_pending_application(app_id, "rejected", reason="不合适")
        r = client.delete(f"/api/pending-applications/{app_id}")
        assert r.status_code == 200
        assert app.state.tracker.get_pending_application(app_id) is None

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
        # 这两条**需要 worker 真的跑**（下面 ran.wait 等的就是它），所以显式恢复
        # 队列。fixture 默认把队列暂停了——后台 worker 会在测试结束、monkeypatch
        # 撤销之后才执行任务，写进真实数据目录（真实日志里查出过 108 条这种垃圾）。
        # 这里 runner 已被 patch，恢复是安全的；下一个测试的 fixture 会重新暂停。
        app.state.workflow_queue.resume()
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
        # 这两条**需要 worker 真的跑**（下面 ran.wait 等的就是它），所以显式恢复
        # 队列。fixture 默认把队列暂停了——后台 worker 会在测试结束、monkeypatch
        # 撤销之后才执行任务，写进真实数据目录（真实日志里查出过 108 条这种垃圾）。
        # 这里 runner 已被 patch，恢复是安全的；下一个测试的 fixture 会重新暂停。
        app.state.workflow_queue.resume()
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

def _add_job(url="https://x/1", category="产品", site_name="bambulab", **kw):
    return app.state.tracker.add_pending_job(site_name=site_name, url=url, category=category, **kw)


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


class TestCheckpoint1Undo:
    """撤销批准/拒绝——2026-08-20 真机事故：误批了两个岗位，approved 之后没有
    任何撤销入口，只能由维护者直接跑 SQL 改库。而批准之后另一个按钮会把简历
    传进企业申请表，不可撤销，所以撤销入口本身必须存在。"""

    def test_undo_approved_job(self, client):
        job_id = _add_job()
        client.post(f"/api/checkpoint1/jobs/{job_id}/approve", json={})

        r = client.post(f"/api/checkpoint1/jobs/{job_id}/undo")

        assert r.status_code == 200 and r.json()["ok"] is True
        assert app.state.tracker.get_pending_job(job_id).status == "pending"

    def test_undo_rejected_job(self, client):
        job_id = _add_job()
        client.post(f"/api/checkpoint1/jobs/{job_id}/reject", json={"reason": "其实是客服岗"})

        r = client.post(f"/api/checkpoint1/jobs/{job_id}/undo")

        assert r.status_code == 200
        job = app.state.tracker.get_pending_job(job_id)
        assert job.status == "pending" and job.reason is None

    def test_undo_missing_job_is_404(self, client):
        assert client.post("/api/checkpoint1/jobs/9999/undo").status_code == 404

    def test_undo_already_pending_job_is_a_no_op(self, client):
        job_id = _add_job()
        r = client.post(f"/api/checkpoint1/jobs/{job_id}/undo")
        assert r.status_code == 200 and r.json()["ok"] is True
        assert app.state.tracker.get_pending_job(job_id).status == "pending"


class TestCheckpoint1Resume:
    """审批页要能看到「批了会发哪份简历」——2026-08-20 真机事故：一个「服务运营」
    岗位批准后实际兜底发了「游戏岗版」，页面上完全看不出来，是有人事后手动跑匹配
    函数才发现。Checkpoint 1 是唯一的人工决策点，判断所需的信息必须都在这一页上。

    **必须复用 `ResumeLibrary.pick`**——分叉出第二份匹配逻辑，后果是"审批页显示的"
    和"实际发出去的"不是同一份，比不显示还糟。
    """

    def _put(self, file, target, allow_send=True, name=None):
        import os

        from dashboard.server import DATA_DIR
        from services.resume_library import ResumeLibrary
        lib = ResumeLibrary(str(DATA_DIR))
        os.makedirs(lib.library_dir, exist_ok=True)
        with open(os.path.join(lib.library_dir, file), "wb") as f:
            f.write(b"%PDF-1.4")
        lib.update_meta(file, name=name or os.path.splitext(file)[0],
                        target=target, allow_send=allow_send)
        return lib

    def test_job_carries_resume_field_with_expected_keys(self, client):
        self._put("game.pdf", "游戏 策划")
        _add_job(title="游戏策划（关卡方向）")

        job = client.get("/api/checkpoint1/jobs").json()["jobs"][0]
        assert set(job["resume"].keys()) == {"file", "name", "matched", "reason", "state"}

    def test_matched_job_reports_the_matching_file(self, client):
        self._put("game.pdf", "游戏 策划", name="游戏岗版")
        _add_job(title="游戏策划（关卡方向）")

        job = client.get("/api/checkpoint1/jobs").json()["jobs"][0]
        assert job["resume"]["matched"] is True
        assert job["resume"]["file"] == "game.pdf"
        assert job["resume"]["name"] == "游戏岗版"

    def test_unmatched_job_uses_the_designated_fallback(self, client):
        lib = self._put("game.pdf", "游戏 策划")
        lib.set_fallback("game.pdf")
        _add_job(title="服务运营专员")

        job = client.get("/api/checkpoint1/jobs").json()["jobs"][0]
        assert job["resume"]["matched"] is False
        assert job["resume"]["file"] == "game.pdf"

    def test_unmatched_with_no_fallback_shows_nothing_sendable(self, client):
        """挑不中又没指定兜底 → 审批页必须明说"没有可发的"，
        **而不是显示一份其实发不出去的**。批之前就得看见。"""
        self._put("game.pdf", "游戏 策划")
        _add_job(title="服务运营专员")

        r = client.get("/api/checkpoint1/jobs").json()["jobs"][0]["resume"]
        assert r["file"] == "" and r["matched"] is False and r["state"] == "missing"

    def test_an_unticked_resume_is_not_offered(self, client):
        """没勾「允许发送」的不该出现在审批页的"会发这份"里——它发不出去。"""
        self._put("game.pdf", "游戏 策划", allow_send=False)
        _add_job(title="游戏策划（关卡方向）")

        assert client.get("/api/checkpoint1/jobs").json()["jobs"][0]["resume"]["file"] == ""

    def test_an_empty_library_does_not_crash(self, client):
        _add_job(title="游戏策划（关卡方向）")
        r = client.get("/api/checkpoint1/jobs")
        assert r.status_code == 200
        assert r.json()["jobs"][0]["resume"]["file"] == ""

    def test_endpoint_resume_choice_matches_the_send_path(self, client):
        """防分叉守门：端点显示的必须和真正发送时 `ResumeLibrary.pick` 的结果一致。
        将来若有人在端点里另写一份匹配逻辑，这条会红。"""
        from dashboard.server import DATA_DIR
        from services.resume_library import ResumeLibrary

        self._put("game.pdf", "游戏 策划")
        self._put("agent.pdf", "AI Agent")
        _add_job(title="游戏策划（关卡方向）", url="https://x/c1")

        shown = client.get("/api/checkpoint1/jobs").json()["jobs"][0]["resume"]
        direct = ResumeLibrary(str(DATA_DIR)).pick(job_title="游戏策划（关卡方向）", jd_text="")
        assert shown["file"] == direct["file"]


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


class TestCheckpoint1ResumePickUsesTheJd:
    """挑简历时喂给 `pick_resume` 的是岗位 JD，不是那一句归类理由。

    参数名就叫 `jd_text`，传 `why` 是 `jd` 还不存在时的遗留（`jd` 是计划 B 才开始
    落库的）。`why` 是分类模型写的一句话（"职责涉及大模型应用"），而 JD 是几百字
    的正文——**关键词匹配拿一句话去匹，等于把绝大部分信号扔了**。

    **两个调用方必须同时改**：`server.py` 的 Checkpoint 1 列表（显示"批了会发哪份"）
    和 `workflow_orchestration.py` 的 m2（实际发出去的那份）。只改一处的话，
    审批页显示的和实际发出去的就不是同一份——**比不显示还糟**
    （这条约束在 server.py 那段注释里已经写明）。

    换之前在真实数据上量过：70 条待审批里，改用 jd 会改变选择的是 **0 条**——
    所以这是零风险的清理，不是一次赌博。
    """

    def test_the_endpoint_passes_the_jd(self, client, monkeypatch):
        seen = {}

        from services.resume_library import ResumeLibrary
        real = ResumeLibrary.pick

        def spy(self, job_title="", jd_text=""):
            seen["jd_text"] = jd_text
            seen["job_title"] = job_title
            return real(self, job_title=job_title, jd_text=jd_text)

        monkeypatch.setattr(ResumeLibrary, "pick", spy)
        _add_job(url="https://x/jd", title="后端工程师", jd="岗位描述\n负责后端服务开发",
                 why="一句话理由")
        client.get("/api/checkpoint1/jobs")
        assert "负责后端服务开发" in seen["jd_text"], \
            f"喂给匹配器的不是 JD：{seen['jd_text']!r}"
        assert seen["job_title"] == "后端工程师"


class TestCheckpoint2CanSeeWhereItCameFrom:
    """填表审批要能看到「这条是从哪个岗位来的」，包括那个岗位的 JD。

    **为什么**：Checkpoint 2 判断的是"这份申请能不能提交"，而判断依据一半在
    Checkpoint 1 那边——岗位是什么、为什么当初选它、JD 写了什么。
    `source_job_id` 这条链一直存在（1:N），但界面从来没用过它，
    于是审批的人要自己翻回选岗页去对。

    **单开一个端点、只在选中时拉**：JD 有几千字，塞进列表会让每次刷新都拖着
    几十份 JD，而列表上根本不显示它。
    """

    def test_it_returns_the_job_the_application_came_from(self, client):
        job_id = _add_job(title="服务运营 - 数据分析", url="https://x/src",
                          jd="岗位描述\n负责数据看板搭建", why="对上了运营方向")
        app_id = app.state.tracker.add_pending_application(
            site_name="bambulab", job_title="服务运营 - 数据分析", fields=[],
            source_job_id=job_id)

        r = client.get(f"/api/pending-applications/{app_id}/source-job")
        assert r.status_code == 200
        got = r.json()
        assert got["id"] == job_id
        assert got["title"] == "服务运营 - 数据分析"
        assert "负责数据看板搭建" in got["jd"]
        assert got["why"] == "对上了运营方向"

    def test_an_application_with_no_source_job_is_404(self, client):
        """`--job-url` 调试路径的记录没有来源岗位——**是诚实的空**，
        前端据此不显示这一块，而不是显示一个空壳。"""
        app_id = app.state.tracker.add_pending_application(
            site_name="s", job_title="t", fields=[], source_job_id=None)
        assert client.get(f"/api/pending-applications/{app_id}/source-job").status_code == 404

    def test_a_dangling_source_job_id_is_404_not_a_500(self, client):
        """岗位被「清掉候选」删掉了，填表记录还在——这条链会断，端点要好好回答。"""
        app_id = app.state.tracker.add_pending_application(
            site_name="s", job_title="t", fields=[], source_job_id=999999)
        assert client.get(f"/api/pending-applications/{app_id}/source-job").status_code == 404

    def test_an_unknown_application_is_404(self, client):
        assert client.get("/api/pending-applications/999999/source-job").status_code == 404


class TestIndexHtmlIsNeverCached:
    """`index.html` **绝不能被浏览器缓存**。

    JS/CSS 的文件名带内容哈希（`index-DN_z1tMQ.js`），新构建 = 新 URL，本来不会
    拿到旧的。但**指向它们的 `index.html` 一旦被缓存，用户就永远拿到旧的那份**
    ——它引用的是上一次构建的哈希文件名，于是前端改了多少次都不生效。

    2026-08-21 真机：修好了 PDF 内联返回、验过响应头正确，用户刷新后**行为一点没变**，
    因为跑的还是旧 JS。这个坑会伪装成"你的修复没生效"，而且每次前端改动都可能撞上。

    带哈希的静态资源反过来——它们可以被永久缓存，URL 变了自然就换新的。
    """

    def test_the_page_is_served_with_no_store(self, client):
        r = client.get("/")
        assert r.status_code == 200
        cc = r.headers.get("cache-control", "").lower()
        assert "no-store" in cc or "no-cache" in cc, f"index.html 会被缓存：{cc!r}"


class TestResumeLibraryFileServing:
    """库里的 PDF 要能**在页面里显示**，不是一点就下载。

    **真机（2026-08-21）**：`FileResponse(..., filename=...)` 会带上
    `content-disposition: attachment`，浏览器一律当下载处理——于是预览用的 iframe
    请求它时不是渲染而是下载，用户看到的现象是"点一下就自动下载"，
    而**预览其实是坏的**。给 filename 的本意只是"下载时叫什么名字"，
    副作用却是"强制下载"。
    """

    def _put(self, file="a.pdf"):
        import os

        from dashboard.server import DATA_DIR
        from services.resume_library import ResumeLibrary
        lib = ResumeLibrary(str(DATA_DIR))
        os.makedirs(lib.library_dir, exist_ok=True)
        with open(os.path.join(lib.library_dir, file), "wb") as f:
            f.write(b"%PDF-1.4 test")
        return lib

    def test_it_is_served_inline_not_as_an_attachment(self, client):
        self._put()
        r = client.get("/api/resume/library/a.pdf")
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert "attachment" not in r.headers.get("content-disposition", "").lower()

    def test_a_missing_file_is_404(self, client):
        assert client.get("/api/resume/library/nope.pdf").status_code == 404


class TestRevealInFolder:
    """「在文件夹中显示」——这是个装在自己机器上的应用，文件本来就在磁盘上，
    再下载一份到 Downloads 里没有意义。

    **命令用 list 形式拼、绝不 shell=True**（项目既有约定）：文件名来自文件夹，
    拼进 shell 字符串就是注入面。路径还要先过 `path_of` 挡穿越。
    """

    def _put(self, file="a.pdf"):
        import os

        from dashboard.server import DATA_DIR
        from services.resume_library import ResumeLibrary
        lib = ResumeLibrary(str(DATA_DIR))
        os.makedirs(lib.library_dir, exist_ok=True)
        with open(os.path.join(lib.library_dir, file), "wb") as f:
            f.write(b"%PDF-1.4")
        return lib

    def test_it_asks_the_os_to_select_that_file(self, client, monkeypatch):
        seen = {}

        import subprocess
        monkeypatch.setattr(subprocess, "Popen", lambda args, **kw: seen.setdefault("args", args))

        lib = self._put()
        r = client.post("/api/resume/library/a.pdf/reveal")
        assert r.status_code == 200
        args = seen["args"]
        assert isinstance(args, list), "必须用 list 形式，不能拼 shell 字符串"
        assert any("a.pdf" in str(x) for x in args)
        assert any(lib.library_dir.replace("/", "\\") in str(x).replace("/", "\\")
                   for x in args), args

    def test_a_missing_file_is_404_and_runs_nothing(self, client, monkeypatch):
        import subprocess
        called = []
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: called.append(a))

        assert client.post("/api/resume/library/nope.pdf/reveal").status_code == 404
        assert called == [], "文件不存在就不该去动系统命令"

    def test_a_traversing_filename_is_refused(self, client, monkeypatch):
        import subprocess
        called = []
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: called.append(a))

        r = client.post("/api/resume/library/..%2F..%2Fsecret.pdf/reveal")
        assert r.status_code in (400, 404)
        assert called == []


class TestClearOneSitesManual:
    """删掉一个站的操作手册，逼下一次 m1 重新勘察。

    **为什么必须有这条路**：手册是 `survey_structure` 探出来的结论缓存，而
    `validate_manual` 只验三条（总数定位符、维度非空、页面结构）——**一份手册
    可以在它永远发现不了的地方是错的**。

    真机（2026-08-21）：joinqq 的手册是在 `set_filter_option` 存在之前探的，
    那时勘察 agent 勾任何 checkbox 都会失败，做不了"勾一个、回读总数"那个实测，
    于是三个字段全靠猜——`工作城市.multi_select` 记成 False（实为 True）、
    `应聘项目.multi_select` 记成 True（实为互斥）、`filter_interaction` 记成
    direct_click（实际要展开两层）。**而没有任何办法让它重探**：手册一旦存下，
    每次 run 都会命中快速路径复用它，错误被无限期继承。

    `survey_structure` 的"1 秒返回"因此是个双刃的信号——它可能是手册复用生效，
    也可能是在复用一份全是猜测的手册。
    """

    def _manual(self):
        from multisite.site_manual import SiteManual
        return SiteManual.from_dict({
            "job_url_source": "link_in_row", "url_template": "", "pagination": "none",
            "filter_interaction": "direct_click", "filters_survive_reload": False,
            "total_count_locator": "", "row_split": "container_per_row",
            "row_anchor": "Apply", "dimensions": [], "important_notes": ""})

    def test_deletes_it_so_the_next_run_re_surveys(self, client):
        app.state.tracker.upsert_site_manual("bambulab", self._manual())
        r = client.delete("/api/checkpoint1/sites/bambulab/manual")
        assert r.status_code == 200
        assert r.json()["deleted"] == 1
        assert app.state.tracker.get_site_manual("bambulab") is None

    def test_only_the_named_site(self, client):
        app.state.tracker.upsert_site_manual("bambulab", self._manual())
        app.state.tracker.upsert_site_manual("joinqq", self._manual())
        client.delete("/api/checkpoint1/sites/bambulab/manual")
        assert app.state.tracker.get_site_manual("joinqq") is not None

    def test_it_does_not_touch_the_candidates(self, client):
        """只删手册，候选池一行不动——两件事分开，误点一个不会连累另一个。"""
        job_id = _add_job()
        app.state.tracker.upsert_site_manual("bambulab", self._manual())
        client.delete("/api/checkpoint1/sites/bambulab/manual")
        assert app.state.tracker.get_pending_job(job_id) is not None

    def test_no_manual_is_a_no_op_not_an_error(self, client):
        assert client.delete("/api/checkpoint1/sites/nope/manual").json()["deleted"] == 0


class TestClearOneSitesCandidates:
    """按站点清掉候选池。

    **为什么需要它**：多站点候选池此前只有 `reset_multisite.py` 一条清理路径，
    而它是**全站清空**——会连别的站的候选和 `pending_applications`（里面有真实
    投递过的记录）一起删。想重收一个站，代价是把所有站的东西都赔进去。
    用户的心智模型是「每个站点投递完就删了相关的数据库」，那需要的正是按站点清。

    **必须重收得回来**：`known_urls` 取的是 `pending_jobs` 的全部 URL、**不看状态**，
    所以"标记成拒绝"不等于清掉——那些岗位会被永久跳过。只有真删行才收得回来。

    **已批准的一行都不动**：`pending_applications.source_job_id` 回指这些行，
    删掉就断了"这个申请是从哪个岗位来的"这条链，而那是已经对外发生过的事。
    """

    def _job(self, site, status="pending", url=None):
        jid = _add_job(url=url or f"https://{site}/{status}/x", site_name=site)
        if status != "pending":
            app.state.tracker.decide_pending_job(jid, status, reason="")
        return jid

    def test_deletes_only_the_named_site(self, client):
        self._job("joinqq")
        keep = self._job("bambulab")
        r = client.delete("/api/checkpoint1/sites/joinqq/jobs")
        assert r.status_code == 200
        assert r.json()["deleted"] == 1
        left = {j.site_name for j in app.state.tracker.get_pending_jobs()}
        assert left == {"bambulab"}
        assert app.state.tracker.get_pending_job(keep) is not None

    def test_keeps_approved_rows(self, client):
        approved = self._job("joinqq", "approved", url="https://joinqq/a")
        self._job("joinqq", "pending", url="https://joinqq/b")
        r = client.delete("/api/checkpoint1/sites/joinqq/jobs")
        assert r.json()["deleted"] == 1, "只该删掉那条待审批的"
        assert app.state.tracker.get_pending_job(approved) is not None, \
            "已批准的行不能删——pending_applications.source_job_id 回指它"

    def test_rejected_rows_go_too(self, client):
        """拒绝过的也要真删掉，否则 `known_urls` 会让它们永远收不回来。"""
        self._job("joinqq", "rejected")
        assert client.delete("/api/checkpoint1/sites/joinqq/jobs").json()["deleted"] == 1

    def test_unknown_site_is_a_no_op_not_an_error(self, client):
        assert client.delete("/api/checkpoint1/sites/nope/jobs").json()["deleted"] == 0


class TestM1CandidatesPerBucketDefault:
    """`candidates_per_bucket` 必须能存成 m1 的默认值。

    **这条测试对着一种静默失败**：`POST /api/workflow/defaults` 只接受
    `config.yaml[<workflow>]` 里**已经存在**的键
    （`allowed = set(config.get(workflow).keys())`），别的键**无声丢掉、
    仍然返回 200**。前端点了「设为默认」会显示成功、下次打开却是老值，
    而且不会有任何报错。

    同一个形状在 W2 接简历时踩过：参数逐个枚举传递，漏一处开关永远传不到、
    没有任何提示。**新增一个运行参数，出厂 config.yaml 里必须同时有它。**
    """

    def test_it_is_in_the_factory_config(self):
        """校验的是**仓库里的出厂 config.yaml**，不是测试沙箱那份最小配置——
        沙箱写的是 `llm: {}`，用它做断言等于什么都没验。"""
        import yaml
        cfg = yaml.safe_load(
            (Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))
        assert "candidates_per_bucket" in (cfg.get("m1") or {}), \
            "config.yaml 的 m1 节缺 candidates_per_bucket，设为默认会被静默丢弃"

    def test_saving_it_actually_persists(self, client):
        """端点这一侧：键在 config 里时，保存必须真的落下去。"""
        app.state.config["m1"] = {"candidates_per_bucket": 15}
        r = client.post("/api/workflow/defaults",
                        json={"workflow": "m1", "updates": {"candidates_per_bucket": 5}})
        assert r.status_code == 200
        assert r.json()["m1"]["candidates_per_bucket"] == 5, \
            "端点返回 200 但值没落下——正是那种静默丢弃"


class TestCheckpoint1SiteManual:
    """站点操作手册要跟着站点信息一起返回，`important_notes` 尤其不能只存不看。

    **`important_notes` 是 agent 唯一的逃生舱**：手册的字段都是闭集，agent 遇到
    设计没覆盖的情况时只能写进这里。它此前**写进库了但零消费方**——没有端点、
    没有 UI，agent 每次填了都没人看得到，等于这个逃生舱通向一堵墙。
    （同一种形状在最终评审里抓到过一次：`render_golden_examples` 零调用方，
    人工标的 `is_golden` 教不到任何东西，而端点还在写它。）
    """

    def _manual(self, **over):
        from multisite.site_manual import SiteManual
        d = {"job_url_source": "link_in_row", "url_template": "", "pagination": "none",
             "filter_interaction": "direct_click", "filters_survive_reload": False,
             "total_count_locator": "", "row_split": "container_per_row",
             "row_anchor": "Apply", "dimensions": [], "important_notes": ""}
        d.update(over)
        return SiteManual.from_dict(d)

    def test_site_without_a_manual_says_none(self, client):
        """没探过的站是 `None`，不是一份空手册——前端要能区分"还没探"和"探了但字段是空"。"""
        _add_job()
        info = client.get("/api/checkpoint1/jobs").json()["sites"]["bambulab"]
        assert info["manual"] is None

    def test_returns_the_recorded_manual(self, client):
        _add_job()
        app.state.tracker.upsert_site_manual("bambulab", self._manual())
        info = client.get("/api/checkpoint1/jobs").json()["sites"]["bambulab"]
        assert info["manual"]["row_split"] == "container_per_row"
        assert info["manual"]["job_url_source"] == "link_in_row"

    def test_important_notes_reach_the_client(self, client):
        note = "筛选器要先展开分组才点得到，展开动作没有可见反馈"
        _add_job()
        app.state.tracker.upsert_site_manual("bambulab", self._manual(important_notes=note))
        info = client.get("/api/checkpoint1/jobs").json()["sites"]["bambulab"]
        assert info["manual"]["important_notes"] == note

    def test_manual_carries_when_it_was_recorded(self, client):
        """手册会过期（站点改版）。没有时间戳的话，人看到一份手册也判断不了它是
        今天探的还是三个月前的。"""
        _add_job()
        app.state.tracker.upsert_site_manual("bambulab", self._manual())
        info = client.get("/api/checkpoint1/jobs").json()["sites"]["bambulab"]
        assert info["manual"]["updated_at"], "手册没带记录时间"


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

    def test_approving_does_not_start_filling(self, client):
        """**批准只是标记，不再立刻开跑。**

        旧行为是批准即入队 m2，于是点第一个岗位的批准之后浏览器立刻被占住，
        剩下的岗位连看都没法看（用户 2026-08-16 实测）。审批是「逐个判断」，
        填表是「批量执行」，把它们绑在一起等于强迫你一次只能审一个。
        """
        job_id = _add_job()
        r = client.post(f"/api/checkpoint1/jobs/{job_id}/approve", json={})

        assert r.status_code == 200
        assert r.json()["job"]["status"] == "approved"
        assert self._pending() == []          # 一个都没排进队列

    def test_batch_approving_does_not_start_filling(self, client):
        ids = [_add_job(url=f"https://x/{i}") for i in range(3)]
        client.post("/api/checkpoint1/batch", json={"decision": "approved", "ids": ids})
        assert self._pending() == []

    def test_start_fill_queues_every_approved_job_of_that_site(self, client):
        """看完一个站的所有岗位之后，点一次按钮把它们一起排进去。"""
        ids = [_add_job(url=f"https://x/{i}") for i in range(3)]
        client.post("/api/checkpoint1/batch", json={"decision": "approved", "ids": ids[:2]})

        r = client.post("/api/checkpoint1/sites/bambulab/start-fill")

        assert r.status_code == 200
        pending = self._pending()
        assert [it["workflow"] for it in pending] == ["m2", "m2"]
        assert sorted(it["params"]["pending_job_id"] for it in pending) == sorted(ids[:2])

    def test_start_fill_skips_jobs_that_already_have_an_application(self, client):
        """已经填过表的不重排——重跑一次等于再往企业系统传一次简历。

        判断依据是 `pending_applications.source_job_id`（m2 落库时写的回指）。
        """
        ids = [_add_job(url=f"https://x/{i}") for i in range(2)]
        client.post("/api/checkpoint1/batch", json={"decision": "approved", "ids": ids})
        app.state.tracker.add_pending_application(
            site_name="bambulab", job_title="t", fields=[], source_job_id=ids[0])

        client.post("/api/checkpoint1/sites/bambulab/start-fill")

        pending = self._pending()
        assert [it["params"]["pending_job_id"] for it in pending] == [ids[1]]

    def test_start_fill_only_touches_the_named_site(self, client):
        here = _add_job(url="https://x/here")
        there = _add_job(url="https://y/there", site_name="other")
        client.post("/api/checkpoint1/batch", json={"decision": "approved",
                                                    "ids": [here, there]})

        client.post("/api/checkpoint1/sites/bambulab/start-fill")

        assert [it["params"]["pending_job_id"] for it in self._pending()] == [here]

    def test_clicking_start_fill_twice_does_not_double_queue(self, client):
        """连点两次（或不确定点没点过）不能把同一个岗位排两遍——那等于再往企业
        系统传一次简历。已经在队列里但还没跑完的，`pending_applications` 里还没有
        回指记录，所以光按"填过表没有"过滤是不够的，队列本身也要看。"""
        ids = [_add_job(url=f"https://x/{i}") for i in range(2)]
        client.post("/api/checkpoint1/batch", json={"decision": "approved", "ids": ids})

        client.post("/api/checkpoint1/sites/bambulab/start-fill")
        client.post("/api/checkpoint1/sites/bambulab/start-fill")

        assert len(self._pending()) == 2

    def test_start_fill_reports_how_many_it_queued(self, client):
        """按钮要能显示「还有 N 个待填表」，所以端点得把数字给出来。"""
        ids = [_add_job(url=f"https://x/{i}") for i in range(2)]
        client.post("/api/checkpoint1/batch", json={"decision": "approved", "ids": ids})

        body = client.post("/api/checkpoint1/sites/bambulab/start-fill").json()

        assert body["queued"] == 2
        assert client.post("/api/checkpoint1/sites/bambulab/start-fill").json()["queued"] == 0

    def test_site_info_reports_how_many_await_filling(self, client):
        """按钮上要显示「开始填表 N」，所以列表接口得带这个数字。

        **由后端算**：差集逻辑（已批准 − 已填表 − 已在队列）已经在 start-fill 里，
        前端再算一遍就是同一规则两份实现，而两份必然漂移。
        """
        ids = [_add_job(url=f"https://x/{i}") for i in range(3)]
        client.post("/api/checkpoint1/batch", json={"decision": "approved", "ids": ids[:2]})

        sites = client.get("/api/checkpoint1/jobs").json()["sites"]
        assert sites["bambulab"]["fill_pending"] == 2

        client.post("/api/checkpoint1/sites/bambulab/start-fill")
        sites = client.get("/api/checkpoint1/jobs").json()["sites"]
        assert sites["bambulab"]["fill_pending"] == 0   # 排进队列的不再算待填

    def test_reject_queues_nothing(self, client):
        job_id = _add_job()
        client.post(f"/api/checkpoint1/jobs/{job_id}/reject", json={"reason": "x"})
        assert self._pending() == []

    def test_already_decided_job_is_not_queued(self, client):
        # 409 那条路径不能顺手再排一个填表任务。
        job_id = _add_job()
        client.post(f"/api/checkpoint1/jobs/{job_id}/approve", json={})
        before = len(self._pending())
        assert client.post(f"/api/checkpoint1/jobs/{job_id}/approve", json={}).status_code == 409
        assert len(self._pending()) == before

    def test_undo_then_reapprove_a_filled_job_never_reenters_the_fill_pool(self, client):
        """撤销的核心正确性：撤销**不需要**区分"填过表没有"。

        一个已经填过表的岗位（`pending_applications.source_job_id` 指回它）撤销后
        重新批准，`source_job_id` 那条回指记录仍在，差集依旧把它排除——不会二次
        把简历传进企业申请表。这条守的正是撤销设计能成立的前提。
        """
        job_id = _add_job()
        client.post(f"/api/checkpoint1/jobs/{job_id}/approve", json={})
        app.state.tracker.add_pending_application(
            site_name="bambulab", job_title="t", fields=[], source_job_id=job_id)

        client.post(f"/api/checkpoint1/jobs/{job_id}/undo")
        client.post(f"/api/checkpoint1/jobs/{job_id}/approve", json={})

        awaiting = srv._jobs_awaiting_fill("bambulab")
        assert job_id not in [j.id for j in awaiting]


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


class TestPendingApplicationScreenshot:
    """表单截图给审批人看——字段名常常不够判断该填什么
    （「学校名称」是问本科还是硕士？），得看它在页面上属于哪个分区。"""

    def test_screenshot_field_roundtrips(self, client):
        app_id = app.state.tracker.add_pending_application(
            site_name="s", job_title="x", fields=[], screenshot="20260815_form.png")
        got = client.get(f"/api/pending-applications/{app_id}").json()
        assert got["screenshot"] == "20260815_form.png"

    def test_defaults_to_empty(self, client):
        app_id = app.state.tracker.add_pending_application(site_name="s", job_title="x", fields=[])
        assert client.get(f"/api/pending-applications/{app_id}").json()["screenshot"] == ""

    def test_serves_an_existing_screenshot(self, client):
        d = srv.DATA_DIR / "multisite_screenshots"
        d.mkdir(parents=True, exist_ok=True)
        (d / "shot.png").write_bytes(b"\x89PNG\r\n\x1a\n fake")
        r = client.get("/api/pending-applications/screenshot/shot.png")
        assert r.status_code == 200 and r.headers["content-type"] == "image/png"

    def test_missing_screenshot_is_404(self, client):
        assert client.get("/api/pending-applications/screenshot/nope.png").status_code == 404

    @pytest.mark.parametrize("evil", ["../config.yaml", "..%2Fx", "a/b.png"])
    def test_path_traversal_is_rejected(self, client, evil):
        """截图名来自数据库，但端点是公开的——不能拿它当任意文件读取器。

        三种码都算拦住了，拦的位置不同：422 是 FastAPI 路由层（路径参数不含 `/`，
        压根没匹配上），400 是处理函数里的显式校验，404 是文件不存在。**断言只关心
        "没把文件发出去"**，写死某一个码等于把实现细节焊进测试。
        """
        r = client.get(f"/api/pending-applications/screenshot/{evil}")
        assert r.status_code in (400, 404, 422), f"意外放行：{r.status_code}"
        assert r.status_code != 200
