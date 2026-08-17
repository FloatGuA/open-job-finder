import json
import logging
import os
import re
import asyncio
import queue
import threading
import time
import json as _json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

logger = logging.getLogger(__name__)

import uvicorn
import yaml
from fastapi import BackgroundTasks, Body, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sse_starlette.sse import EventSourceResponse

from services.boss_search_url import (
    build_search_url as _build_boss_search_url_shared,
    _flatten_filter_labels,
    BOSS_DISTRICTS_PATH as _BOSS_DISTRICTS_PATH,
    BOSS_POSITIONS_PATH as _BOSS_POSITIONS_PATH,
    BOSS_INDUSTRIES_PATH as _BOSS_INDUSTRIES_PATH,
)
from services.config_manager import get_config_manager
from services.console_utf8 import force_utf8_stdout
from services.llm_client import build_model_router, load_config
from services.onboarding import OnboardingChecker
from services.progress_emitter import ProgressEmitter, ProgressEvent, event_to_dict

# uvicorn 进程的 stdout 在 Windows 上默认是 GBK，而 m1/m2 的 agent 追踪经由本进程
# 打印——2026-08-16 一句带 ✅ 的话就抛 UnicodeEncodeError，异常冒泡打死了整条 run，
# 已经找到的 8 个岗位全丢。CLI 那条路径一直有这层保护，控制台这条没有。
force_utf8_stdout()
from services.prompt_manager import EDITABLE_PROMPTS, PromptManager
from services.tracker import ApplicationTracker
from tools.biz_logic.wechat_id import wechat_id_from
from services import artifact_cleanup, run_log_reader
from services.run_logger import reconcile_orphaned_runs
from services.scheduler_service import SchedulerService
from services.workflow_orchestration import OrchestrationService


BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BASE_DIR.parent / "logs" / "runs"
DASHBOARD_DIR = BASE_DIR / "dashboard"
STATIC_DIR = DASHBOARD_DIR / "static"
DATA_DIR = BASE_DIR / "data"
CONFIG_PATH = BASE_DIR / "config.yaml"
CONTROL_PATH = DATA_DIR / "control.json"
PROFILE_PATH = DATA_DIR / "profile.yaml"
BOSS_DISTRICTS_PATH = DATA_DIR / "boss_districts.json"
BOSS_POSITIONS_PATH = DATA_DIR / "boss_positions.json"
BOSS_INDUSTRIES_PATH = DATA_DIR / "boss_industries.json"
SCHEDULE_CONFIG_PATH = DATA_DIR / "schedule.yaml"
SCHEDULE_LOG_PATH = DATA_DIR / "schedule_log.jsonl"
SELFCHECK_LOG_PATH = DATA_DIR / "selfcheck_log.jsonl"
REGRESSION_SMOKE_LOG = DATA_DIR / "regression_smoke_log.jsonl"

app = FastAPI(title="OpenJobFinder Dashboard")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


# Schedule params use the SAME canonical keys the workflows consume (resolve_params
# + run_w1 / run_w2): W1 score_threshold/max_cards/dry_run/headless, W2
# max_conversations/no_response_days/stale_conv_days/dry_run/headless. Legacy keys
# (limit / apply_limit / days / generate_resume) are gone; _load_schedule_config
# drops them from older saved files so the scheduler never runs on stale params.
_SCHEDULE_DEFAULTS = {
    "apply": {
        "enabled": False,
        "times": [],
        "interval_enabled": False,
        "interval_minutes": 0,
        "params": {
            "score_threshold": 0,
            "max_cards": 15,
            "dry_run": False,
            "headless": True,
        },
    },
    "check": {
        "enabled": False,
        "times": [],
        "interval_enabled": False,
        "interval_minutes": 0,
        "params": {
            "max_conversations": 200,
            "no_response_days": 14,
            "stale_conv_days": 30,
            "auto_send_adapted_resume": False,
            "dry_run": False,
            "headless": True,
        },
    },
    # Recurring real-run self-check: every interval_minutes, optionally probe infra
    # (login/DB/LLM), then run a REAL W1 (max_cards=w1_max) and W2
    # (max_conversations=w2_max) in sequence. Doubles as health check + 常态化运行.
    "selfcheck": {
        "enabled": False,
        "interval_minutes": 720,
        "w1_max": 10,
        "w2_max": 300,
        "with_probes": True,
    },
}

_scheduler_service: "SchedulerService | None" = None
_orch_service: "OrchestrationService | None" = None


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_runtime_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    return load_config(str(CONFIG_PATH)) or {}


def _initialize_state() -> None:
    if getattr(app.state, "tracker", None) is not None:
        return

    config = _load_runtime_config()
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    app.state.config = config
    app.state.tracker = ApplicationTracker(db_path=str(DATA_DIR / "jobs.db"))
    app.state.onboarding = OnboardingChecker(
        profile_path=str(DATA_DIR / "profile.yaml"),
        session_path=str(DATA_DIR / "session.json"),
        config=config,
    )
    app.state.model_router = build_model_router(config)
    app.state.emitter = getattr(app.state, "emitter", None) or ProgressEmitter()
    app.state.paused = _read_control_status()["paused"]
    if not hasattr(app.state, "browser_session"):
        from services.browser_session import BrowserSession
        # Headed: interactive "open in Boss" actions are meant to be watched.
        app.state.browser_session = BrowserSession(DATA_DIR, headless=False)
    if getattr(app.state, "workflow_queue", None) is None:
        from services.workflow_queue import WorkflowQueue
        # Single sequential worker: every workflow start (manual / scheduled /
        # explicit queue add / composed chain) is enqueued and run one at a time.
        # is_busy defers the worker while a non-queue browser op owns the session.
        app.state.workflow_queue = WorkflowQueue(
            runner=_get_orch().run_item,
            is_busy=lambda: bool(getattr(app.state.emitter, "current_workflow", None)),
        )
        # item_id -> raw runner summary, for callers blocking on a queued item
        # (the regression smoke). Bounded in _queue_runner.
        app.state.smoke_summaries = {}


def _serialize_record(record) -> dict[str, Any]:
    # T030 dropped decision/critic_verdict/resume_path/error_msg/responded_at/
    # apply_attempted/updated_at from ApplicationRecord. Only serialize fields the
    # current schema actually has, or this AttributeErrors on every /api/jobs call.
    return {
        "job_id": record.job_id,
        "title": record.title,
        "company": record.company,
        "city": record.city or "",
        "salary": record.salary or "",
        "status": record.status,
        "score": record.score,
        "applied_at": record.applied_at,
        "url": record.url,
        "created_at": record.created_at,
    }


# WeChat-card parsing lives in tools/biz_logic/wechat_id.py -- deterministic text
# parsing that Boss occasionally changes the wording of, so it needs exactly one
# home. It used to sit here with a comment saying it "mirrors Chat.tsx"; the
# frontend's copy has been removed in favour of the wechat_id this API returns.
_wechat_id_from = wechat_id_from


def _analysis_state(conv, active_window_days: int) -> str:
    """会话的「意图分析是否是最新的」——ok / pending / stale。

    存在的理由：LLM 分析失败时 AnalyzeStep 刻意**不写库**（不污染数据、不推进水位线，
    这样下轮才会重试）。代价是 `intent` 列留着上一轮的旧值，UI 无法分辨「这就是分析
    结论」和「这次没分析成，你看到的是旧的」。两者靠 last_analyzed_ts 可以确定性区分。

    判定必须严格镜像 `tools/biz_logic/filter_conversations` 的分支顺序，否则 UI 会
    承诺一件流水线不会做的事：
      - ok      水位线追平消息时间（或没有真实时间戳，脏检查同样不会挑它）
      - pending 水位线落后 **且** 在活跃窗口内 → 下轮 W2 会重新分析
      - stale   水位线落后 **但** 超出活跃窗口 → too_old 优先级高于 unanalyzed，
                永远不会再被分析（这是 filter 里有意的取舍，不是 bug）
    """
    analyzed = int(getattr(conv, "last_analyzed_ts", 0) or 0)
    last_ts = int(getattr(conv, "last_msg_ts", 0) or 0)
    if not last_ts or analyzed >= last_ts:
        return "ok"
    if active_window_days and active_window_days > 0:
        cutoff_ms = int((time.time() - active_window_days * 86400) * 1000)
        if last_ts < cutoff_ms:
            return "stale"
    return "pending"


def _serialize_conversation(
    conv, messages: list[dict], job_url: str, job_title: str = "", active_window_days: int = 0
) -> dict[str, Any]:
    """Derive the dashboard's conversation shape from the T030 schema.

    HRConversation no longer carries messages / last_msg_text / last_msg_from /
    last_synced / status / suggested_reply / needs_reply / reply_draft. The
    frontend (Chat.tsx, Dashboard.tsx) still expects that shape, so we derive it
    here from the fields that do exist: message history lives in the hr_messages
    table; suggested_reply/reply_draft both map to reply_text; last_synced maps to
    created_at; status maps to stage; needs_reply is derived from reply_status.
    """
    msgs = [
        {"sender": m["sender"], "text": m["text"], "time": m.get("msg_time") or ""}
        for m in messages
    ]
    reply_text = conv.reply_text or ""
    wechat_id = _wechat_id_from(msgs)
    wechat_dismissed = bool(getattr(conv, "wechat_dismissed", False))
    return {
        "conv_id": conv.conv_id,
        "hr_name": conv.hr_name,
        "hr_title": getattr(conv, "hr_title", "") or "",
        "company": conv.company,
        "wechat_id": wechat_id,
        "wechat_dismissed": wechat_dismissed,
        # 待加微信：HR 已发来微信号（number card）且用户尚未点掉提醒
        "wechat_pending": bool(wechat_id) and not wechat_dismissed,
        "messages": msgs,
        "last_msg_text": msgs[-1]["text"] if msgs else conv.last_msg_preview,
        "last_msg_from": msgs[-1]["sender"] if msgs else "",
        "last_msg_preview": conv.last_msg_preview,
        "last_synced": conv.created_at,
        # ISO 时间：最后一条已记录消息的入库时间（hr_messages.created_at，按 id 升序末条），
        # 供前端算「距上次沟通 N 天」。无消息时回退到会话创建时间。
        "last_msg_at": messages[-1]["created_at"] if messages else conv.created_at,
        "job_id": conv.job_id,
        "job_url": job_url,
        # 在招岗位名：会话表不存岗位名（hr_title 是 HR 的职务，不是岗位），岗位名在
        # applications.title，按 job_id 关联（conv_id==job_id 的硬关联）。W1 投过的岗位
        # 才有；HR 主动发起、非 W1 投递的会话可能为空。
        "job_title": job_title,
        "status": conv.stage,
        "stage": conv.stage,
        "intent": conv.intent,
        # intent 是否是最新一次分析的结果（见 _analysis_state）。'pending'/'stale' 时
        # intent 是上一轮的旧值，不能当作本轮结论展示。
        "analysis_state": _analysis_state(conv, active_window_days),
        "suggested_reply": reply_text,
        "needs_reply": conv.reply_status in ("pending", "approved", "revision"),
        "reply_status": conv.reply_status,
        "reply_draft": reply_text,
        # Manual resume-send queue state (null | 'queued'): frontend shows a
        # "待发简历" tag + cancel button when queued (mirrors the reply flow).
        "resume_status": conv.resume_status,
        "matched_resume": conv.matched_resume,
        "matched_resume_reason": conv.matched_resume_reason,
        "message_count": len(msgs),
    }


def _write_control_file(paused: bool) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "paused": paused,
        "paused_at": _utcnow_iso() if paused else None,
    }
    with CONTROL_PATH.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False)


def _read_control_status() -> dict[str, Any]:
    if not CONTROL_PATH.exists():
        return {"paused": False, "paused_at": None}

    try:
        with CONTROL_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file) or {}
    except (json.JSONDecodeError, OSError):
        return {"paused": False, "paused_at": None}

    return {
        "paused": bool(data.get("paused", False)),
        "paused_at": data.get("paused_at"),
    }


def _load_json_file(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (json.JSONDecodeError, OSError):
        return default


def _validate_run_pipeline(pipeline: str | None) -> str | None:
    # 引用队列的白名单，不手抄一份——手抄的那份漏了 m1/m2，表现为"日志在磁盘上
    # 但按 pipeline 一筛就 400"。
    from services.workflow_queue import VALID_WORKFLOWS

    if pipeline is not None and pipeline not in VALID_WORKFLOWS:
        raise HTTPException(status_code=400,
                            detail=f"pipeline must be one of {'|'.join(VALID_WORKFLOWS)}")
    return pipeline


def _write_schedule_log(entry: dict) -> None:
    """Append one JSON line to schedule_log.jsonl. Thread-safe via GIL + append mode."""
    SCHEDULE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SCHEDULE_LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(_json.dumps(entry, ensure_ascii=False) + "\n")


def _write_selfcheck_log(entry: dict) -> None:
    """Append one JSON line to selfcheck_log.jsonl (full-cycle self-check history)."""
    SELFCHECK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SELFCHECK_LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(_json.dumps(entry, ensure_ascii=False) + "\n")


def _get_last_run_time(workflow: str) -> "datetime | None":
    """Return the most recent triggered_at timestamp for a workflow from schedule_log.jsonl."""
    if not SCHEDULE_LOG_PATH.exists():
        return None
    last: datetime | None = None
    try:
        for line in SCHEDULE_LOG_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entry = _json.loads(line)
            except _json.JSONDecodeError:
                continue
            if entry.get("workflow") != workflow:
                continue
            if entry.get("result") not in ("success", "error"):
                continue
            t = datetime.fromisoformat(entry["triggered_at"])
            if last is None or t > last:
                last = t
    except Exception:
        pass
    return last


def _load_schedule_config() -> dict:
    import copy
    import yaml as _yaml

    defaults = copy.deepcopy(_SCHEDULE_DEFAULTS)
    if not SCHEDULE_CONFIG_PATH.exists():
        return defaults
    try:
        with SCHEDULE_CONFIG_PATH.open("r", encoding="utf-8") as file:
            data = _yaml.safe_load(file) or {}
        for workflow in ("apply", "check"):
            if workflow not in data:
                continue
            workflow_data = data[workflow]
            defaults[workflow]["enabled"] = bool(workflow_data.get("enabled", False))
            defaults[workflow]["times"] = list(workflow_data.get("times", []))
            defaults[workflow]["interval_enabled"] = bool(workflow_data.get("interval_enabled", False))
            # fallback: old YAML may have stored interval_hours before the field was renamed
            raw_minutes = workflow_data.get("interval_minutes")
            if raw_minutes is None:
                raw_minutes = int(workflow_data.get("interval_hours", 0)) * 60
            defaults[workflow]["interval_minutes"] = int(raw_minutes)
            # Only carry over keys in the current schema; legacy keys from older
            # saved files (limit / apply_limit / days / generate_resume) are dropped
            # so the scheduler runs on the canonical workflow param model.
            saved_params = workflow_data.get("params") or {}
            for key in defaults[workflow]["params"]:
                if key in saved_params:
                    defaults[workflow]["params"][key] = saved_params[key]
        sc = data.get("selfcheck")
        if isinstance(sc, dict):
            d = defaults["selfcheck"]
            d["enabled"] = bool(sc.get("enabled", d["enabled"]))
            d["interval_minutes"] = int(sc.get("interval_minutes", d["interval_minutes"]))
            d["w1_max"] = int(sc.get("w1_max", d["w1_max"]))
            d["w2_max"] = int(sc.get("w2_max", d["w2_max"]))
            d["with_probes"] = bool(sc.get("with_probes", d["with_probes"]))
        return defaults
    except Exception:
        return defaults


def _save_schedule_config(cfg: dict) -> None:
    import yaml as _yaml

    SCHEDULE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SCHEDULE_CONFIG_PATH.open("w", encoding="utf-8") as file:
        _yaml.safe_dump(cfg, file, allow_unicode=True, sort_keys=False)


def _get_orch() -> OrchestrationService:
    """Lazily build the single OrchestrationService, wiring in the state accessor and
    the two log writers it needs. Cheap; constructs no runners."""
    global _orch_service
    if _orch_service is None:
        _orch_service = OrchestrationService(
            get_state=lambda: app.state,
            ensure_state=_initialize_state,
            data_dir=DATA_DIR,
            write_schedule_log=_write_schedule_log,
            write_selfcheck_log=_write_selfcheck_log,
            smoke_log_path=REGRESSION_SMOKE_LOG,
        )
    return _orch_service


# Thin module-level aliases kept for the scheduler injection and endpoints that
# already reference these names; the implementations now live on the service.
def _is_rate_limited_today() -> bool:
    return _get_orch().is_rate_limited_today()


def _run_selfcheck_cycle(*, w1_max: int, w2_max: int, with_probes: bool, trigger_type: str) -> dict:
    return _get_orch().run_selfcheck_cycle(
        w1_max=w1_max, w2_max=w2_max, with_probes=with_probes, trigger_type=trigger_type)


def _sched_enqueue(wf: str, params: dict, source: str, coalesce: bool):
    """The scheduler's queue hook: ensure app.state exists, then enqueue.

    The SchedulerService itself knows nothing about app.state; server owns that
    coupling and hands it in here.
    """
    _initialize_state()
    return app.state.workflow_queue.enqueue(wf, params, source=source, coalesce=coalesce)


def _get_scheduler() -> SchedulerService:
    """Lazily build the single SchedulerService, wiring in the cross-cutting pieces
    it consumes but does not own (rate-limit gate, self-check cycle, schedule log)."""
    global _scheduler_service
    if _scheduler_service is None:
        _scheduler_service = SchedulerService(
            load_config=_load_schedule_config,
            get_last_run_time=_get_last_run_time,
            enqueue=_sched_enqueue,
            rate_limited_today=_is_rate_limited_today,
            run_selfcheck=_run_selfcheck_cycle,
            write_schedule_log=_write_schedule_log,
        )
    return _scheduler_service


def _rebuild_scheduler(cfg: dict, restore_interval_times: bool = False) -> None:
    """Thin wrapper kept for the endpoints that already call it."""
    _get_scheduler().rebuild(cfg, restore_interval_times=restore_interval_times)


@app.on_event("startup")
async def startup() -> None:
    _initialize_state()
    app.state.emitter = getattr(app.state, "emitter", None) or ProgressEmitter()
    _get_scheduler().rebuild(_load_schedule_config(), restore_interval_times=True)
    reconciled = reconcile_orphaned_runs()
    if reconciled:
        logger.info("Reconciled %d orphaned run(s) left 'running' by a prior hard kill: %s",
                    len(reconciled), ", ".join(reconciled))


@app.on_event("shutdown")
async def shutdown() -> None:
    if _scheduler_service is not None:
        _scheduler_service.shutdown()
    tracker = getattr(app.state, "tracker", None)
    if tracker is not None:
        tracker.close()


@app.get("/", response_class=HTMLResponse)
async def index() -> HTMLResponse:
    index_path = STATIC_DIR / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Dashboard frontend not found.")
    return HTMLResponse(index_path.read_text(encoding="utf-8"))


@app.get("/api/jobs")
async def get_jobs(status: str | None = None, page: int = 1, page_size: int = 20) -> JSONResponse:
    _initialize_state()
    if page < 1 or page_size < 1:
        raise HTTPException(status_code=400, detail="page and page_size must be >= 1")

    tracker = app.state.tracker
    records = tracker.get_by_status(status) if status else tracker.get_all()
    total = len(records)
    start = (page - 1) * page_size
    end = start + page_size
    page_records = records[start:end]
    hr_names = tracker.get_hr_names_by_job_ids([r.job_id for r in page_records])
    jobs = [{**_serialize_record(r), "hr_name": hr_names.get(r.job_id, "")} for r in page_records]

    return JSONResponse(
        {
            "jobs": jobs,
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    )


@app.get("/api/runs")
async def get_runs(pipeline: str | None = None) -> JSONResponse:
    pipeline = _validate_run_pipeline(pipeline)
    runs = [
        summary
        for path in run_log_reader.iter_run_files(RUNS_DIR, pipeline)
        if (summary := run_log_reader.summarize_run_file(path)) is not None
    ]
    runs.sort(key=lambda item: item.get("started_at") or item["filename"], reverse=True)
    return JSONResponse({"runs": runs, "total": len(runs)})


@app.get("/api/runs/{run_id}")
async def get_run_detail(run_id: str) -> JSONResponse:
    path = run_log_reader.find_run_file(RUNS_DIR, run_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    detail = run_log_reader.parse_run_detail(path)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} is empty")
    return JSONResponse(detail)


@app.get("/api/runs/{run_id}/events")
async def get_run_events(run_id: str) -> JSONResponse:
    """Full persisted event stream for one run, in frontend ProgressEvent shape, so
    WorkflowTrack can replay a finished run's complete view (not the capped buffer)."""
    path = run_log_reader.find_run_file(RUNS_DIR, run_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return JSONResponse({"events": run_log_reader.parse_run_events(path)})


@app.get("/api/multisite/stages")
async def get_multisite_stages() -> JSONResponse:
    """m1/m2 的 LangGraph 节点顺序——前端第 2 层「地铁站」的骨架。

    **从图定义导出，不手维护**：W1/W2 的 SKELETON 是手抄的静态模板，已经漂移过
    （见 PITFALLS.md）。m1 = 队列里的 select_only 路径（只跑到 Checkpoint 1）。
    """
    from multisite.layer1_agent import stage_names
    return JSONResponse({"m1": list(stage_names(True)), "m2": list(stage_names(False))})


@app.get("/api/apply-failure/{name}")
async def get_apply_failure_screenshot(name: str) -> FileResponse:
    """Serve a saved apply-failure screenshot (capture_screenshot writes these to
    data/apply_failures/). Reject path traversal — only a bare .png filename is allowed."""
    if "/" in name or "\\" in name or ".." in name or not name.endswith(".png"):
        raise HTTPException(status_code=400, detail="invalid name")
    path = DATA_DIR / "apply_failures" / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="screenshot not found")
    return FileResponse(str(path), media_type="image/png")


@app.get("/api/ops/artifacts")
async def get_ops_artifacts() -> JSONResponse:
    """Failed-run JSONL logs + W1 apply-failure screenshots in one listing — both
    accumulate real HR/company PII on disk with no automatic cleanup (see
    services/artifact_cleanup.py docstring). A manual review-then-delete entry
    point, not an automatic purge: the user decides what's still worth keeping."""
    apply_failures_dir = DATA_DIR / "apply_failures"
    return JSONResponse({
        "run_logs": artifact_cleanup.list_failed_run_logs(RUNS_DIR),
        "screenshots": artifact_cleanup.list_apply_failure_screenshots(apply_failures_dir),
    })


@app.post("/api/ops/artifacts/delete")
async def delete_ops_artifacts(request: Request) -> JSONResponse:
    """Bulk-delete selected run logs / screenshots by filename. Each name is
    validated independently (path traversal, extension) so one bad entry in a
    batch does not abort the rest — the response reports per-file outcome."""
    data = await request.json()
    run_log_names = data.get("run_logs") or []
    screenshot_names = data.get("screenshots") or []
    apply_failures_dir = DATA_DIR / "apply_failures"

    run_log_results = {
        name: artifact_cleanup.delete_run_log(RUNS_DIR, name) for name in run_log_names
    }
    screenshot_results = {
        name: artifact_cleanup.delete_screenshot(apply_failures_dir, name) for name in screenshot_names
    }
    return JSONResponse({
        "run_logs": run_log_results,
        "screenshots": screenshot_results,
        "deleted_count": sum(run_log_results.values()) + sum(screenshot_results.values()),
    })


@app.get("/api/jobs/{job_id}")
async def get_job(job_id: str) -> JSONResponse:
    _initialize_state()
    record = app.state.tracker.get(job_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    return JSONResponse(_serialize_record(record))


@app.delete("/api/jobs/pending")
async def delete_pending_jobs() -> JSONResponse:
    """Delete all non-APPLIED job records (e.g. FOUND / SCORED).

    This resets the candidate pool so the next W1 run searches for fresh results
    instead of retrying stale carryover records.
    """
    _initialize_state()
    deleted = app.state.tracker.delete_non_applied()
    return JSONResponse({"deleted": deleted})


@app.delete("/api/jobs/error")
async def delete_error_jobs() -> JSONResponse:
    """Delete all ERROR application records."""
    _initialize_state()
    deleted = app.state.tracker.delete_by_status("ERROR")
    return JSONResponse({"deleted": deleted})


@app.post("/api/browse")
async def browse_url(body: dict[str, Any] = Body(...)) -> JSONResponse:
    """Open a URL in the automation browser (shares the Boss直聘 session profile)."""
    url = body.get("url", "")
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    _initialize_state()
    if app.state.emitter.current_workflow:
        return JSONResponse(
            {"ok": False, "reason": "工作流正在运行，请稍后再试"},
            status_code=409,
        )

    def _navigate() -> None:
        # Shared interactive browser (BrowserSession) — one owner, no legacy BrowserAgent.
        page = app.state.browser_session.get_page()
        page.get(url, timeout=30)

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _navigate)
        return JSONResponse({"ok": True})
    except Exception as exc:
        return JSONResponse({"ok": False, "reason": str(exc)}, status_code=500)


@app.get("/api/stats")
async def get_stats() -> JSONResponse:
    _initialize_state()
    tracker = app.state.tracker
    onboarding = app.state.onboarding
    config = app.state.config

    from services.settings_resolver import resolve_params
    stats = tracker.get_stats()
    daily_limit = int(resolve_params("w1", {}, config, DATA_DIR).get("daily_limit", 0))
    applied_today = stats.get("applied_today", 0)

    response = {
        "stats": {
            "total": stats.get("total", 0),
            "by_status": stats.get("by_status", {}),
            "applied_today": applied_today,
            "daily_limit": daily_limit,
            "remaining_today": max(0, daily_limit - applied_today),
            # "responded" = HR replied → conversation entered CHATTING. tracker
            # get_stats() exposes this as "chatting" (there is no "responded" key).
            "responded": stats.get("chatting", 0),
            "interviews": stats.get("interviews", 0),
            "offers": stats.get("offers", 0),
        },
        "onboarding": onboarding.check_all(),
    }
    return JSONResponse(response)


@app.get("/api/architecture")
async def get_architecture() -> JSONResponse:
    """Live overlay for the architecture navigator (static structure lives in the
    frontend; this only supplies the runtime counts + current agent state)."""
    _initialize_state()
    tracker = app.state.tracker
    counts = tracker.get_lifecycle_counts()
    return JSONResponse({**counts, "running": app.state.emitter.current_workflow})


@app.post("/api/pause")
async def pause_scheduler() -> JSONResponse:
    _initialize_state()
    _write_control_file(paused=True)
    app.state.paused = True
    return JSONResponse({"paused": True, "message": "Scheduler paused."})


@app.post("/api/resume")
async def resume_scheduler() -> JSONResponse:
    _initialize_state()
    if CONTROL_PATH.exists():
        CONTROL_PATH.unlink()
    app.state.paused = False
    return JSONResponse({"paused": False, "message": "Scheduler resumed."})


def _parse_resume_upload(path: str, suffix: str) -> tuple[dict, str]:
    """上传简历 → 解析成动态分区文档（v2.16 起入信息池，池是唯一源头）。

    PDF 走视觉解析（vision 链 codex_cli→claude_cli）；两个 CLI 都失败**直接抛错**——不回落
    弱的 pdfminer 文本路径，宁可报错让用户知道（用户 2026-08-01 定，fail fast）。
    DOCX 无页面图可渲染，走文本解析（docx 文本 → LLM 结构化）。
    返回 (parsed_doc, method)，method ∈ {vision, text}。
    """
    from services import resume_blocks as rb
    from services.resume_parser import _extract_text_from_docx

    mr = app.state.model_router
    pm = _resume_prompt_manager()
    if suffix == ".pdf":
        return rb.parse_resume_vision(path, mr, pm), "vision"
    return rb.parse_resume_to_blocks(_extract_text_from_docx(path), mr, pm), "text"


@app.post("/api/resume/upload")
async def upload_resume(file: UploadFile = File(...)) -> JSONResponse:
    _initialize_state()
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".pdf", ".docx"}:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX files are supported.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    saved_path = DATA_DIR / f"resume_raw_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}{suffix}"

    try:
        MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
        content = await file.read()
        if len(content) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=400, detail="File too large. Maximum size is 10 MB.")
        saved_path.write_bytes(content)
        parsed, method = _parse_resume_upload(str(saved_path), suffix)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    from services import info_pool
    if not (parsed["basic_info"].get("name") or any(s["blocks"] for s in parsed["sections"])):
        raise HTTPException(status_code=400, detail="Resume parsing failed: no meaningful content detected.")
    # 解析结果**不直接落池**，先变成一份待确认提案（2026-08-15）。池是求职者全部
    # 信息的唯一主库，机器产生的变更一律要人过一眼——见 services/pool_diff.py。
    from services import pool_diff
    pool_path = str(DATA_DIR / "info_pool.yaml")
    current = info_pool.load_pool(pool_path)
    proposed = info_pool.merge_parsed(current, parsed)
    diff = pool_diff.diff_pools(current, proposed)
    if diff["has_changes"]:
        pool_diff.save_pending(proposed, source="upload", pool_path=pool_path)

    return JSONResponse(
        {
            "success": True,
            "message": "Resume parsed. Review the proposed changes.",
            "method": method,
            "sections_found": [s["name"] for s in parsed["sections"] if s["blocks"]],
            "pending": diff["has_changes"],
        }
    )


@app.get("/api/resume/blocks")
async def get_resume_blocks() -> JSONResponse:
    """当前激活简历的内容（不存在返回空结构）。

    原先直接读 data/resume_blocks.yaml —— 那是激活份的第二份副本，2026-08-15 删了。
    """
    from services.resume_store import ResumeStore
    return JSONResponse(ResumeStore(str(DATA_DIR)).load_active())


@app.put("/api/resume/blocks")
async def put_resume_blocks(body: dict[str, Any] = Body(...)) -> JSONResponse:
    """整存编辑后的块库；只接受已知结构的键，避免存入垃圾字段。

    经 ResumeStore 写入当前激活简历 {slug}.yaml（唯一存储位）。
    """
    from services.resume_store import ResumeStore
    ResumeStore(str(DATA_DIR)).save_active_blocks(_clean_doc_body(body))
    return JSONResponse({"ok": True})


def _clean_doc_body(body: dict) -> dict:
    """请求体 → 动态分区文档（白名单清洗，池与简历共用同一形状）。"""
    from services import resume_blocks
    clean = resume_blocks.empty_blocks()
    bi = body.get("basic_info") or {}
    for k in clean["basic_info"]:
        if k in bi:
            clean["basic_info"][k] = str(bi[k] or "")
    clean["self_description"] = str(body.get("self_description") or "")
    clean["sections"] = resume_blocks.clean_sections(body.get("sections"))
    return clean


# ── 信息池（v2.16：求职者全部信息的主库；上传解析入池，简历从池组合）──────────
@app.get("/api/interview-prep")
async def get_interview_prep() -> JSONResponse:
    """面试 Prep 卡片（「面试准备」页专用，与产品功能无关）。内容在 data/ 下，不入 git。"""
    from services import interview_prep
    return JSONResponse(interview_prep.load_prep(str(DATA_DIR / "interview_prep.yaml")))


@app.get("/api/pool")
async def get_pool() -> JSONResponse:
    """读信息池；首次自动从激活简历迁移初始化。"""
    from services import info_pool
    return JSONResponse(info_pool.load_pool(str(DATA_DIR / "info_pool.yaml")))


@app.put("/api/pool")
async def put_pool(body: dict[str, Any] = Body(...)) -> JSONResponse:
    from services import info_pool
    info_pool.save_pool(_clean_doc_body(body), str(DATA_DIR / "info_pool.yaml"))
    return JSONResponse({"ok": True})


@app.post("/api/pool/build")
async def build_pool_endpoint(body: dict[str, Any] | None = None) -> JSONResponse:
    """用 LLM 把自我描述融进信息池，产出一份**待确认提案**（不直接落盘）。

    这是整个 diff 确认流程最初的动机：LLM 在这里是**整体重写 sections**，可能把它
    没提到的块弄丢。原先靠"写前快照 + 事后回滚"兜底，那是内容已被覆盖之后的补救。
    现在改成事前把关——回包只带 diff，人勾选之后才写池。
    """
    _initialize_state()
    body = body or {}
    from services import info_pool, pool_diff
    pool_path = str(DATA_DIR / "info_pool.yaml")
    current = info_pool.load_pool(pool_path)
    proposed = info_pool.build_pool(current, str(body.get("self_description") or ""),
                                    app.state.model_router, _resume_prompt_manager())
    diff = pool_diff.diff_pools(current, proposed)
    if diff["has_changes"]:
        pool_diff.save_pending(proposed, source="build", pool_path=pool_path)
    return JSONResponse({"pending": diff["has_changes"], "diff": diff})


# ── 信息池变更提案（机器改池必须人工勾选确认）──────────────────────────────────

@app.get("/api/pool/pending")
async def get_pool_pending() -> JSONResponse:
    """当前待确认的提案 + 它相对**此刻**池内容的 diff。

    diff 每次现算，不存下来：人可能在提案生成之后又手动编辑过池，用当时算好的
    diff 会让他看到一份跟现状对不上的对照。
    """
    from services import info_pool, pool_diff
    pool_path = str(DATA_DIR / "info_pool.yaml")
    rec = pool_diff.load_pending(pool_path)
    if rec is None:
        return JSONResponse({"pending": False})
    diff = pool_diff.diff_pools(info_pool.load_pool(pool_path), rec["proposed"])
    return JSONResponse({"pending": True, "source": rec.get("source", ""),
                         "created_at": rec.get("created_at", ""), "diff": diff})


@app.post("/api/pool/pending/apply")
async def apply_pool_pending(body: dict[str, Any] = Body(...)) -> JSONResponse:
    """把勾中的变更落进池。没勾的一律保持现状。"""
    from services import info_pool, pool_diff
    pool_path = str(DATA_DIR / "info_pool.yaml")
    rec = pool_diff.load_pending(pool_path)
    if rec is None:
        return JSONResponse({"ok": False, "error": "没有待确认的提案"}, status_code=404)
    keys = body.get("accepted")
    if not isinstance(keys, list):
        return JSONResponse({"ok": False, "error": "accepted must be a list"}, status_code=400)
    current = info_pool.load_pool(pool_path)
    merged = pool_diff.apply_selection(current, rec["proposed"], keys)
    info_pool.save_pool(merged, pool_path)   # save_pool 仍然写前留快照，多一层兜底
    pool_diff.clear_pending(pool_path)
    return JSONResponse({"ok": True, "applied": len(keys)})


@app.delete("/api/pool/pending")
async def discard_pool_pending() -> JSONResponse:
    """整份丢弃提案，池不动。"""
    from services import pool_diff
    pool_diff.clear_pending(str(DATA_DIR / "info_pool.yaml"))
    return JSONResponse({"ok": True})


# ── 信息池快照（每次保存前留档，可回滚）────────────────────────────────────────
@app.get("/api/pool/snapshots")
async def list_pool_snapshots() -> JSONResponse:
    """历史版本 + 当前版本（前端把当前也列进去并打绿灯，避免盲跳回滚）。"""
    from services import info_pool
    p = str(DATA_DIR / "info_pool.yaml")
    return JSONResponse({
        "snapshots": info_pool.list_snapshots(p),
        "current": info_pool.current_summary(p),
    })


@app.post("/api/pool/snapshots/{fname}/restore")
async def restore_pool_snapshot(fname: str) -> JSONResponse:
    from services import info_pool
    try:
        return JSONResponse(info_pool.restore_snapshot(fname, str(DATA_DIR / "info_pool.yaml")))
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail=fname)


@app.post("/api/resume/compose")
async def compose_resume(body: dict[str, Any] = Body(...)) -> JSONResponse:
    """AI 组合：按岗位 JD 从信息池挑块+排序 → 落成一份新简历并激活。

    LLM 只挑 id（judge），块内容由 code 从池复制（不杜撰）；basic_info 取池值。
    """
    _initialize_state()
    from services import info_pool, resume_blocks, resume_tailor
    from services.resume_store import ResumeStore
    job = {
        "title": str(body.get("job_title") or ""),
        "company": str(body.get("company") or ""),
        "jd_text": str(body.get("jd_text") or ""),
    }
    if not (job["title"] or job["jd_text"]):
        raise HTTPException(status_code=400, detail="job_title 或 jd_text 至少给一个")
    pool = info_pool.load_pool(str(DATA_DIR / "info_pool.yaml"))
    if not any(s["blocks"] for s in pool["sections"]):
        raise HTTPException(status_code=400, detail="信息池为空，先上传简历或在信息池里添加内容")
    sections = resume_tailor.generate_composed_sections(pool, job, app.state.model_router, _resume_prompt_manager())
    if not sections:
        raise HTTPException(status_code=502, detail="AI 没有挑出任何有效内容，请重试或检查信息池概括")
    doc = resume_blocks.empty_blocks()
    doc["basic_info"] = dict(pool.get("basic_info") or {})
    doc["sections"] = sections
    store = ResumeStore(str(DATA_DIR))
    item = store.create(
        name=str(body.get("name") or "").strip() or (job["title"] + " 定制" if job["title"] else "AI 定制简历"),
        target=job["title"], blocks=doc,
    )
    store.activate(item["slug"])
    return JSONResponse({"resume": item, "sections": [s["name"] for s in sections]})


# ── 多份简历管理（v2.15 简历制作台：每份独立完整，存储只在 resumes/{slug}.yaml）──
@app.get("/api/resumes")
async def list_resumes() -> JSONResponse:
    """简历列表，每项带上 `pdf_state`（ready / stale / missing）。

    **跟列表一起返回而不是单开端点**：界面上原本有两个互不相干的列表（简历、导出
    存档），谁也不知道某一份到底能不能发出去——2026-08-16 那三次 m2 就是用了一份
    比简历还旧的 PDF，全程没有任何提示。分两次请求只会让"状态还没到"变成一种可能
    的中间状态。
    """
    from services.resume_store import ResumeStore

    store = ResumeStore(str(DATA_DIR))
    index = store.list()
    status = store.pdf_status()
    for item in index.get("items") or []:
        st = status.get(item["slug"]) or {}
        item["pdf_state"] = st.get("state", "missing")
        item["pdf_exported_at"] = st.get("exported_at", "")
    return JSONResponse(index)


@app.post("/api/resumes")
async def create_resume(body: dict[str, Any] = Body(...)) -> JSONResponse:
    from services.resume_store import ResumeStore
    item = ResumeStore(str(DATA_DIR)).create(
        name=str(body.get("name") or ""),
        target=str(body.get("target") or ""),
        copy_from_active=bool(body.get("copy_from_active", True)),
    )
    return JSONResponse(item)


@app.get("/api/resumes/{slug}/blocks")
async def get_resume_doc(slug: str) -> JSONResponse:
    """读某一份简历的内容（不激活它）——已保存简历列表的预览用。"""
    from services.resume_store import ResumeStore
    try:
        return JSONResponse(ResumeStore(str(DATA_DIR)).get_blocks(slug))
    except (KeyError, ValueError):
        raise HTTPException(status_code=404, detail=f"resume not found: {slug}")


@app.put("/api/resumes/{slug}")
async def update_resume_meta(slug: str, body: dict[str, Any] = Body(...)) -> JSONResponse:
    from services.resume_store import ResumeStore
    try:
        item = ResumeStore(str(DATA_DIR)).update_meta(
            slug,
            name=str(body["name"]) if "name" in body else None,
            target=str(body["target"]) if "target" in body else None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail=f"resume not found: {slug}")
    return JSONResponse(item)


@app.post("/api/resumes/{slug}/activate")
async def activate_resume(slug: str) -> JSONResponse:
    from services.resume_store import ResumeStore
    try:
        idx = ResumeStore(str(DATA_DIR)).activate(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"resume not found: {slug}")
    return JSONResponse(idx)


@app.delete("/api/resumes/{slug}")
async def delete_resume(slug: str) -> JSONResponse:
    from services.resume_store import ResumeStore
    try:
        ResumeStore(str(DATA_DIR)).delete(slug)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return JSONResponse({"ok": True})


# ── 导出存档（最近生成）─────────────────────────────────────────────────────
@app.get("/api/resume/exports")
async def list_resume_exports() -> JSONResponse:
    from services.resume_store import ResumeStore
    return JSONResponse({"exports": ResumeStore(str(DATA_DIR)).list_exports()})


@app.get("/api/resume/exports/{fname}")
async def download_resume_export(fname: str):
    from services.resume_store import ResumeStore
    try:
        path = ResumeStore(str(DATA_DIR)).export_file(fname)
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail=fname)
    return FileResponse(path, media_type="application/pdf", filename=fname)


@app.delete("/api/resume/exports/{fname}")
async def delete_resume_export(fname: str) -> JSONResponse:
    from services.resume_store import ResumeStore
    try:
        ResumeStore(str(DATA_DIR)).delete_export(fname)
    except (ValueError, FileNotFoundError):
        raise HTTPException(status_code=404, detail=fname)
    return JSONResponse({"ok": True})


# v2.16：旧 /api/resume/blocks/build（自述融入当前简历）已由 POST /api/pool/build 取代——
# 自我描述属于「关于我」的信息，融入目标是信息池而非某一份简历。


# ── 功能二：岗位特化生成（预制模板 / 简历方案 / 招呼语 / 渲染 PDF）────────────
def _resume_prompt_manager() -> PromptManager:
    """简历端点用的 PromptManager：带上用户 prompt 注入（各 resume_* 的 task 注入 + global）。"""
    from services.profile_loader import ProfileLoader
    injection = ProfileLoader(str(PROFILE_PATH)).load().prompt_injection
    return PromptManager(injection=injection)


def _tailor_job_from_body(body: dict) -> dict:
    """从 body 取岗位信息；有 job_id 且 tracker 有记录则补全 title/company。"""
    job = {
        "title": str(body.get("job_title") or ""),
        "company": str(body.get("company") or ""),
        "jd_text": str(body.get("jd_text") or ""),
    }
    jid = body.get("job_id")
    if jid and not (job["title"] and job["company"]):
        rec = app.state.tracker.get(str(jid))
        if rec:
            job["title"] = job["title"] or (rec.title or "")
            job["company"] = job["company"] or (rec.company or "")
    return job


@app.get("/api/resume/templates")
async def get_resume_templates() -> JSONResponse:
    from services import resume_tailor
    return JSONResponse({"templates": resume_tailor.load_templates(str(DATA_DIR / "resume_templates.yaml"))})


@app.put("/api/resume/templates")
async def put_resume_templates(body: dict[str, Any] = Body(...)) -> JSONResponse:
    from services import resume_tailor
    items = body.get("templates")
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="templates must be a list")
    clean = [
        {
            "name": str(t.get("name", "")),
            "keywords": [str(k) for k in (t.get("keywords") or []) if str(k).strip()],
            "blocks": t.get("blocks") or [],
            "greeting_style": str(t.get("greeting_style", "")),
        }
        for t in items if isinstance(t, dict)
    ]
    resume_tailor.save_templates(clean, str(DATA_DIR / "resume_templates.yaml"))
    return JSONResponse({"ok": True, "templates": clean})


@app.post("/api/resume/tailor/resume")
async def tailor_resume(body: dict[str, Any] = Body(...)) -> JSONResponse:
    _initialize_state()
    from services import resume_blocks, resume_tailor
    job_id = str(body.get("job_id") or "")
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    job = _tailor_job_from_body(body)
    from services import info_pool
    pool = info_pool.load_pool(str(DATA_DIR / "info_pool.yaml"))
    templates = resume_tailor.load_templates(str(DATA_DIR / "resume_templates.yaml"))
    tmpl = resume_tailor.match_template(templates, job["title"], job["jd_text"])
    sections = resume_tailor.generate_resume_sections(pool, job, tmpl, app.state.model_router, _resume_prompt_manager())
    plan = resume_tailor._set_plan_part(
        job_id, "resume", sections, job_title=job["title"], company=job["company"],
        path=str(DATA_DIR / "resume_plans.yaml"),
    )
    return JSONResponse(plan)


@app.post("/api/resume/tailor/greeting")
async def tailor_greeting(body: dict[str, Any] = Body(...)) -> JSONResponse:
    _initialize_state()
    from services import resume_blocks, resume_tailor
    job_id = str(body.get("job_id") or "")
    if not job_id:
        raise HTTPException(status_code=400, detail="job_id is required")
    job = _tailor_job_from_body(body)
    from services import info_pool
    pool = info_pool.load_pool(str(DATA_DIR / "info_pool.yaml"))
    templates = resume_tailor.load_templates(str(DATA_DIR / "resume_templates.yaml"))
    tmpl = resume_tailor.match_template(templates, job["title"], job["jd_text"])
    greeting = resume_tailor.generate_greeting(pool, job, tmpl, app.state.model_router, _resume_prompt_manager())
    plan = resume_tailor._set_plan_part(
        job_id, "greeting", greeting, job_title=job["title"], company=job["company"],
        path=str(DATA_DIR / "resume_plans.yaml"),
    )
    return JSONResponse(plan)


@app.get("/api/resume/plan/{job_id}")
async def get_resume_plan(job_id: str) -> JSONResponse:
    from services import resume_tailor
    return JSONResponse(resume_tailor.get_plan(job_id, str(DATA_DIR / "resume_plans.yaml")))


@app.get("/api/resume/plan/{job_id}/pdf")
async def get_resume_plan_pdf(job_id: str):
    """把已生成的简历方案渲染成 PDF（Chromium CDP）并返回。"""
    _initialize_state()
    from services import resume_tailor
    from services.resume_store import ResumeStore
    plan = resume_tailor.get_plan(job_id, str(DATA_DIR / "resume_plans.yaml"))
    sections = (plan.get("resume") or {}).get("sections") or []
    if not sections:
        raise HTTPException(status_code=404, detail="该岗位还没有生成简历方案")
    blocks = ResumeStore(str(DATA_DIR)).load_active()
    html = resume_tailor.render_resume_html(blocks.get("basic_info") or {}, sections)
    out = DATA_DIR / "resume_pdfs" / f"{job_id}.pdf"
    resume_tailor.render_html_to_pdf(html, str(out))
    return FileResponse(str(out), media_type="application/pdf", filename=f"resume_{job_id}.pdf")


@app.post("/api/resume/print-pdf")
async def print_resume_pdf(body: dict[str, Any] = Body(...)):
    """把前端块库预览的自包含 HTML 用 Chromium 打印成 PDF 返回。

    与右侧实时预览**同源**（同一份 HTML）——预览所见即导出所得，避免前端预览与后端
    渲染两套排版漂移。HTML 是用户本人简历内容、本地单用户工具，直接打印可接受。
    """
    _initialize_state()
    from services import resume_tailor
    from services.resume_store import ResumeStore
    html = str(body.get("html") or "")
    if not html.strip():
        raise HTTPException(status_code=400, detail="html is required")
    # 每次导出按时间戳存档（「最近生成」列表的数据源），不互相覆盖，滚动上限修剪。
    # 存档文件名带 slug：两份同名简历（真实数据里就有两份「游戏岗版」）否则分不清
    # 谁是谁，而分不清的后果是给 A 岗位发了 B 的简历。不给 slug 就按激活份存。
    store = ResumeStore(str(DATA_DIR))
    slug = str(body.get("slug") or "") or (store.list().get("active") or "")
    out = store.export_path_for(slug) if slug else store.export_path(
        str(body.get("name") or "resume"))
    resume_tailor.render_html_to_pdf(html, out)
    return FileResponse(out, media_type="application/pdf", filename=os.path.basename(out))


@app.get("/api/onboarding/status")
async def onboarding_status() -> JSONResponse:
    _initialize_state()
    return JSONResponse(app.state.onboarding.check_all())


@app.get("/api/control/status")
async def control_status() -> JSONResponse:
    _initialize_state()
    status = _read_control_status()
    app.state.paused = status["paused"]
    return JSONResponse(status)


@app.get("/api/profile")
async def get_profile() -> JSONResponse:
    _initialize_state()
    # Read through the singleton so this endpoint and /api/config/system cannot
    # disagree about what profile.yaml currently says.
    profile = get_config_manager(str(CONFIG_PATH), str(PROFILE_PATH)).get_profile()
    if not profile:
        return JSONResponse({"keywords": [], "cities": [], "experience": [], "degree": [], "salary": "", "scale": []})
    return JSONResponse({
        # `name` 已于 v2.22.0 从 profile.yaml / Profile / 前端类型一并删除：
        # 全流程不消费它（Boss 招呼由平台自动发送），保留只会让人以为它是必填的。
        "keywords": profile.get("keywords") or [],
        "cities": profile.get("cities") or [],
        "experience": profile.get("experience") or [],
        "degree": profile.get("degree") or [],
        "salary": profile.get("salary") or "",
        "scale": profile.get("scale") or [],
        "job_types": profile.get("job_types") or [],
        "financing": profile.get("financing") or [],
        "districts": profile.get("districts") or [],
        "position_types": profile.get("position_types") or [],
        "industries": profile.get("industries") or [],
        "prompt_injection": profile.get("prompt_injection") or {},
    })


@app.post("/api/profile")
async def save_profile(request: Request) -> JSONResponse:
    _initialize_state()
    data = await request.json()
    # Field isolation: only overwrite the profile keys actually present in this
    # request. Settings now saves in independent sections (search filters vs prompt
    # injection, on different tabs) -- a partial save that omits keywords must NOT
    # blank keywords. save_profile() merges into the cached dict through the
    # singleton, so keys we don't touch (incl. those managed outside the dashboard:
    # boss_online, greeting_template, ...) survive and the cache stays in step.
    _ALLOWED = {
        "name", "keywords", "cities", "experience", "degree", "salary", "scale",
        "job_types", "financing", "districts", "position_types", "industries",
        "prompt_injection",
    }
    cm = get_config_manager(str(CONFIG_PATH), str(PROFILE_PATH))
    updates = {k: v for k, v in data.items() if k in _ALLOWED}
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if updates:
        cm.save_profile(updates)
    return JSONResponse({"ok": True})


# ── Prompt 模板（用户显示/编辑/恢复默认）──────────────────────────────────────
# 覆盖层落在 code/data/prompts_override/（gitignore）；save 校验占位符集与默认一致，
# 防止改坏 prompt 让 W1/W2 的 render 抛错。


@app.get("/api/prompts")
async def get_prompts() -> JSONResponse:
    _initialize_state()
    pm = PromptManager()
    out = []
    for name in EDITABLE_PROMPTS:
        default = pm.get_default(name)
        out.append({
            "name": name,
            "content": pm.load(name),   # 生效值（覆盖或默认）
            "default": default,
            "modified": pm.is_modified(name),
            "placeholders": sorted(pm.extract_placeholders(default)),
        })
    return JSONResponse(out)


@app.post("/api/prompts/{name}")
async def save_prompt(name: str, request: Request) -> JSONResponse:
    _initialize_state()
    if name not in EDITABLE_PROMPTS:
        return JSONResponse({"error": f"unknown prompt: {name}"}, status_code=404)
    data = await request.json()
    content = data.get("content", "")
    pm = PromptManager()
    try:
        pm.save_override(name, content)
    except ValueError as exc:
        # 占位符校验失败 → 400，前端提示，不写入。
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "modified": True})


@app.post("/api/prompts/{name}/reset")
async def reset_prompt(name: str) -> JSONResponse:
    _initialize_state()
    if name not in EDITABLE_PROMPTS:
        return JSONResponse({"error": f"unknown prompt: {name}"}, status_code=404)
    PromptManager().reset_override(name)
    return JSONResponse({"ok": True, "modified": False})


@app.get("/api/config/llm")
async def get_llm_config() -> JSONResponse:
    _initialize_state()
    config = _load_runtime_config()
    caps = config.get("llm", {}).get("capabilities", {})
    capabilities: dict[str, str] = {}
    for level in ("fast", "balanced", "powerful"):
        providers = caps.get(level) or []
        capabilities[level] = providers[0].get("type", "") if providers else ""

    tool_providers = config.get("llm", {}).get("tool_providers", {})

    available = app.state.model_router.configured_provider_names()

    return JSONResponse({
        "capabilities": capabilities,
        "tool_providers": tool_providers,
        "available_providers": available,
    })


@app.post("/api/config/llm")
async def save_llm_config(request: Request) -> JSONResponse:
    _initialize_state()
    data = await request.json()

    # Through config_manager, not inline yaml: the singleton caches config.yaml, so
    # writing the file behind its back left get_system_config() serving the pre-edit
    # copy (/api/config/system reads through the singleton and would show stale data).
    tp = data.get("tool_providers") or {}
    cm = get_config_manager(str(CONFIG_PATH), str(PROFILE_PATH))
    cm.save_llm_settings(
        capabilities={
            level: (data.get("capabilities") or {}).get(level, "")
            for level in ("fast", "balanced", "powerful")
        },
        tool_providers={
            "score_job":      tp.get("score_job") or None,
            "analyze_intent": tp.get("analyze_intent") or None,
        },
    )

    new_config = _load_runtime_config()
    app.state.config = new_config
    app.state.model_router = build_model_router(new_config)
    return JSONResponse({"ok": True})


@app.get("/api/config/system")
async def get_config_system() -> JSONResponse:
    cm = get_config_manager(str(CONFIG_PATH), str(PROFILE_PATH))
    cfg = cm.get_system_config()
    return JSONResponse({
        "w1": cfg.get("w1", {}),
        "w2": cfg.get("w2", {}),
        "llm_capabilities": list(cfg.get("llm", {}).get("capabilities", {}).keys()),
    })


@app.get("/api/filters/districts")
async def get_districts(city: str = "") -> JSONResponse:
    """Return district/metro items for the specified city."""
    districts = _load_json_file(BOSS_DISTRICTS_PATH, {})
    if not isinstance(districts, dict):
        return JSONResponse({"items": []})
    if city:
        return JSONResponse({"items": districts.get(city) or []})
    if districts:
        first_city = next(iter(districts.keys()))
        return JSONResponse({"items": districts.get(first_city) or []})
    return JSONResponse({"items": []})


@app.get("/api/filters/positions")
async def get_positions() -> JSONResponse:
    """Return position type list (flat or tree)."""
    items = _load_json_file(BOSS_POSITIONS_PATH, [])
    if not isinstance(items, list):
        items = []
    return JSONResponse({"items": items})


@app.get("/api/filters/industries")
async def get_industries() -> JSONResponse:
    """Return industry list (flat or tree)."""
    items = _load_json_file(BOSS_INDUSTRIES_PATH, [])
    if not isinstance(items, list):
        items = []
    return JSONResponse({"items": items})


def _write_session_sentinel() -> None:
    """Write the data/session.json sentinel after a confirmed login.

    OnboardingChecker.check_all() keys "session ready" on this file's existence;
    cookies themselves auto-persist in browser_profile/. Kept when login moved
    off BrowserAgent.save_session() onto BrowserSession.
    """
    import json as _json

    path = DATA_DIR / "session.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps({"saved": _utcnow_iso()}), encoding="utf-8")


def _check_session_via_browser() -> dict:
    """Logged-in check via the shared BrowserSession (one browser, hardened verify)."""
    profile_exists = (
        (DATA_DIR / "browser_profile_dp").exists()
        or (DATA_DIR / "browser_profile").exists()
    )
    if not profile_exists:
        return {
            "valid": False,
            "reason": "browser_profile 不存在，请先运行 python main.py --onboarding",
        }
    res = app.state.browser_session.verify()
    if res["ok"]:
        return {"valid": True, "name": res["username"]}
    return {"valid": False, "reason": res["reason"]}


@app.get("/api/check/session")
async def check_session_status() -> JSONResponse:
    """Verify Boss直聘 session using VerifySessionStep."""
    _initialize_state()
    emitter = getattr(app.state, "emitter", None)
    if emitter and emitter.current_workflow:
        return JSONResponse({"valid": None, "reason": "工作流正在运行，浏览器占用中，请稍后再验证"})
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _check_session_via_browser)
    return JSONResponse(result)


@app.post("/api/session/save-login")
async def save_login_session() -> JSONResponse:
    """Persist login: verify the shared browser is logged in, then write the sentinel."""
    _initialize_state()

    def _persist() -> bool:
        res = app.state.browser_session.verify()
        if res["ok"]:
            _write_session_sentinel()
            return True
        return False

    loop = asyncio.get_event_loop()
    ok = await loop.run_in_executor(None, _persist)
    if ok:
        return JSONResponse({"ok": True})
    return JSONResponse({"ok": False, "reason": "尚未确认登录"}, status_code=400)


@app.post("/api/session/open-login")
async def session_open_login() -> JSONResponse:
    """Open Boss直聘 login page in the shared interactive browser for the user to log in."""
    _initialize_state()
    if app.state.emitter.current_workflow:
        return JSONResponse({"status": "error", "reason": "工作流正在运行，请等待结束后再登录"}, status_code=409)

    def _open() -> None:
        page = app.state.browser_session.get_page()
        try:
            page.get("https://www.zhipin.com/web/user/?ka=header-login", timeout=30)
        except Exception as nav_exc:
            # Boss直聘 may redirect to an anomaly-detection page DrissionPage can't fully
            # load; the window stays visible so the user can finish verification manually.
            logger.warning("Login page navigation raised (browser stays open): %s", nav_exc)

    loop = asyncio.get_event_loop()
    try:
        await loop.run_in_executor(None, _open)
    except Exception as exc:
        return JSONResponse({"status": "error", "reason": str(exc)}, status_code=500)
    return JSONResponse({"status": "browser_opened"})


@app.post("/api/session/confirm-login")
async def session_confirm_login() -> JSONResponse:
    """After the user logged in, verify the shared browser and persist the sentinel."""
    _initialize_state()

    def _verify_and_persist() -> dict:
        res = _check_session_via_browser()
        if res.get("valid"):
            _write_session_sentinel()
        return res

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, _verify_and_persist)
    return JSONResponse({"status": "saved", "session": result})


@app.get("/api/conversations")
async def get_conversations(
    status: str | None = None,
    stage: str | None = None,
) -> JSONResponse:
    _initialize_state()
    tracker = app.state.tracker
    # tracker.get_hr_conversations only filters by stage; the optional status
    # query param filters by reply_status in Python (the frontend only sends stage).
    convs = tracker.get_hr_conversations(stage=stage)
    if status:
        convs = [c for c in convs if c.reply_status == status]
    # 活跃窗口＝W2 的 no_response_days（ScanStep 就是拿它当 active_window_days 传给
    # filter_conversations 的）。用于判断「水位线落后的会话下轮还会不会被重新分析」。
    from services.settings_resolver import resolve_params
    active_window_days = int(
        resolve_params("w2", {}, app.state.config, DATA_DIR).get("no_response_days", 0) or 0
    )
    # Job title/url (在招岗位名 + open-in-Boss link) live on the applications row,
    # not on hr_conversations — batch-fetched by distinct job_id (one query, not one
    # per conversation). Same for messages, keyed by conv_id. At 900+ conversations
    # the old per-conversation tracker.get()/get_hr_messages() loop was the dominant
    # cost of this endpoint (N+1 -> 2 queries total).
    job_ids = sorted({c.job_id for c in convs if c.job_id})
    apps_by_job_id = tracker.get_many(job_ids)
    messages_by_conv = tracker.get_hr_messages_bulk([c.conv_id for c in convs])

    return JSONResponse({
        "conversations": [
            _serialize_conversation(
                c, messages_by_conv.get(c.conv_id, []),
                (apps_by_job_id.get(c.job_id).url or "") if apps_by_job_id.get(c.job_id) else "",
                (apps_by_job_id.get(c.job_id).title or "") if apps_by_job_id.get(c.job_id) else "",
                active_window_days,
            )
            for c in convs
        ],
        "total": len(convs),
    })


@app.get("/api/conversations/pending-replies")
async def get_pending_replies() -> JSONResponse:
    _initialize_state()
    convs = app.state.tracker.get_pending_replies()
    job_urls: dict[str, str] = {}
    for c in convs:
        if c.job_id and c.job_id not in job_urls:
            rec = app.state.tracker.get(c.job_id)
            job_urls[c.job_id] = (rec.url or "") if rec else ""
    return JSONResponse([
        {
            "conv_id": c.conv_id,
            "hr_name": c.hr_name,
            "company": c.company,
            "intent": c.intent or "",
            "suggested_reply": c.reply_text or "",
            "reply_status": c.reply_status or "pending",
            "reply_draft": c.reply_text or "",
            "last_synced": c.created_at,
            "job_url": job_urls.get(c.job_id or "", ""),
        }
        for c in convs
    ])


@app.post("/api/conversations/{conv_id}/approve-reply")
async def approve_reply(conv_id: str) -> JSONResponse:
    _initialize_state()
    tracker = app.state.tracker
    conv = tracker.get_hr_conversation(conv_id)
    if conv is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    tracker.update_reply_approval(conv_id, "approved")
    return JSONResponse({"ok": True})


@app.post("/api/conversations/{conv_id}/revise-reply")
async def revise_reply(conv_id: str, body: dict) -> JSONResponse:
    _initialize_state()
    tracker = app.state.tracker
    conv = tracker.get_hr_conversation(conv_id)
    if conv is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    tracker.update_reply_approval(conv_id, "revision", str(body.get("draft") or ""))
    return JSONResponse({"ok": True})


@app.post("/api/conversations/{conv_id}/cancel-reply")
async def cancel_reply(conv_id: str) -> JSONResponse:
    """Revert an approved/revision reply back to pending (keeps suggested text)."""
    _initialize_state()
    tracker = app.state.tracker
    conv = tracker.get_hr_conversation(conv_id)
    if conv is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    tracker.update_reply_approval(conv_id, "pending")
    return JSONResponse({"ok": True})


@app.post("/api/conversations/{conv_id}/dismiss-reply")
async def dismiss_reply(conv_id: str) -> JSONResponse:
    _initialize_state()
    tracker = app.state.tracker
    conv = tracker.get_hr_conversation(conv_id)
    if conv is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    tracker.update_reply_approval(conv_id, "dismissed")
    return JSONResponse({"ok": True})


@app.post("/api/conversations/{conv_id}/queue-resume")
async def queue_resume(conv_id: str) -> JSONResponse:
    """Manually STAGE a resume send for this conversation (W2 detection-miss fallback).
    DB-only: sets resume_status='queued', browser untouched, so it is fully cancellable
    until W3 actually delivers it. Not an immediate send — mirrors approving a text
    reply. Idempotent (re-queueing a queued conv is a no-op)."""
    _initialize_state()
    tracker = app.state.tracker
    conv = tracker.get_hr_conversation(conv_id)
    if conv is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    tracker.set_resume_status(conv_id, "queued")
    return JSONResponse({"ok": True})


@app.post("/api/conversations/{conv_id}/cancel-resume")
async def cancel_resume(conv_id: str) -> JSONResponse:
    """Un-stage a queued resume send (before W3 delivers it). Clears resume_status."""
    _initialize_state()
    tracker = app.state.tracker
    conv = tracker.get_hr_conversation(conv_id)
    if conv is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    tracker.set_resume_status(conv_id, None)
    return JSONResponse({"ok": True})


@app.post("/api/conversations/dismiss-all-pending-replies")
async def dismiss_all_pending_replies() -> JSONResponse:
    """Bulk-dismiss all replies still awaiting approval (reply_status='pending') in
    one shot. The pending list accumulates drafts from ancient/stale conversations;
    clicking through them one by one is tedious. Approved replies (already triaged,
    waiting for W3 to send) are NOT touched."""
    _initialize_state()
    count = app.state.tracker.dismiss_all_pending_replies()
    return JSONResponse({"ok": True, "dismissed": count})


@app.post("/api/conversations/{conv_id}/dismiss-wechat")
async def dismiss_wechat(conv_id: str) -> JSONResponse:
    """User clicked 已添加/点掉 on the go-add-WeChat reminder -> stop reminding."""
    _initialize_state()
    tracker = app.state.tracker
    conv = tracker.get_hr_conversation(conv_id)
    if conv is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    tracker.dismiss_wechat(conv_id)
    return JSONResponse({"ok": True})


@app.get("/api/conversations/wechat-pending")
async def get_wechat_pending() -> JSONResponse:
    """Conversations where HR sent their WeChat and the user hasn't dismissed the
    reminder yet -> drives the Dashboard strong reminder + 待加微信 filter."""
    _initialize_state()
    tracker = app.state.tracker
    items = []
    job_urls: dict[str, str] = {}
    for c in tracker.get_hr_conversations():
        if bool(getattr(c, "wechat_dismissed", False)):
            continue
        wid = _wechat_id_from(
            [{"sender": m["sender"], "text": m["text"]} for m in tracker.get_hr_messages(c.conv_id)]
        )
        if not wid:
            continue
        if c.job_id and c.job_id not in job_urls:
            rec = tracker.get(c.job_id)
            job_urls[c.job_id] = (rec.url or "") if rec else ""
        items.append({
            "conv_id": c.conv_id,
            "hr_name": c.hr_name,
            "hr_title": getattr(c, "hr_title", "") or "",
            "company": c.company,
            "wechat_id": wid,
            "job_url": job_urls.get(c.job_id or "", ""),
        })
    return JSONResponse({"conversations": items, "total": len(items)})


@app.post("/api/conversations/{conv_id}/reject")
async def reject_conversation(conv_id: str) -> JSONResponse:
    """Reject the whole job: close the conversation and dismiss any draft reply.

    Moves the HR thread to the 'closed' stage so W2's filter_conversations skips
    it by default, and sets reply_status -> 'dismissed' so re-analysis (CASE-
    protected) never drafts a reply again. If HR later sends a new message the
    conversation can still re-surface for one re-analysis (no draft) -- this keeps
    behavior uniform with the existing per-reply dismiss mechanism.
    """
    _initialize_state()
    tracker = app.state.tracker
    conv = tracker.get_hr_conversation(conv_id)
    if conv is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    tracker.reset_hr_conversation_stage(conv_id, "closed")
    tracker.update_reply_approval(conv_id, "dismissed")
    return JSONResponse({"ok": True})


@app.post("/api/conversations/{conv_id}/mark-sent")
async def mark_sent(conv_id: str) -> JSONResponse:
    """Mark a reply as sent (user did it manually in Boss).

    Delegates to tracker: this was the only write endpoint holding its own SQL,
    and the same transition lived in three places with two different meanings.
    """
    _initialize_state()
    if app.state.tracker.mark_reply_sent(conv_id) <= 0:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    return JSONResponse({"ok": True})


# ── Checkpoint 1：选岗审批（pending_jobs）────────────────────────────────────
# 这是两个人工确认点里的**第一个**：确认"这些岗位该不该投"。第二个是下面的
# pending-applications（确认"这些字段填得对不对"）。拆开是因为选错岗和填错字段
# 是两类错误，前者判错的话后者审得再仔细也没用。
#
# 注意函数名不要叫 delete_pending_jobs / list_pending_jobs 之外的通用名——
# 本文件里已经有个 `delete_pending_jobs`（DELETE /api/jobs/pending，删的是
# applications 表里 W1 的非 APPLIED 记录），跟这里完全无关，重名会读错。

@app.get("/api/checkpoint1/jobs")
async def list_checkpoint1_jobs(status: str | None = None) -> JSONResponse:
    """候选岗位 + 可选类别表。

    类别表跟列表一起返回而不是单开一个端点：前端要渲染类别下拉必须有它，分两次请求
    只会让"下拉是空的"变成一种可能的中间状态。
    """
    _initialize_state()
    from multisite import preferences

    tracker = app.state.tracker
    items = tracker.get_pending_jobs(status=status)
    categories = preferences.load_profile().job_seeking.category_names

    # 站点投递上限 + 该站已批准数，一起返回给前端算告警。
    # **已批准数在这里统计（而不是数上面的 items）**：上面按 status 过滤过，
    # 看「待审批」时 items 里一条已批准的都没有，拿它当分母告警永远不会触发。
    all_jobs = tracker.get_pending_jobs()
    sites = sorted({j.site_name for j in all_jobs if j.site_name})
    site_info = {}
    for site in sites:
        limits = tracker.get_site_limits(site)
        brief = tracker.get_site_brief(site)
        here = [j for j in all_jobs if j.site_name == site]
        # 按招聘项目分别统计已批准数——投递上限常常是按项目算的，拿全站总数去比
        # 一个项目的上限会低估额度、把人拦在本来能投的岗位外面。
        # bucket='' 的老记录单独归一档，前端据此知道"这些岗位算不进任何项目"。
        approved_by_bucket: dict = {}
        for j in here:
            if j.status == "approved":
                approved_by_bucket[j.bucket] = approved_by_bucket.get(j.bucket, 0) + 1
        site_info[site] = {
            "site_name": site,
            "approved_here": sum(1 for j in here if j.status == "approved"),
            "approved_by_bucket": approved_by_bucket,
            "buckets": sorted({j.bucket for j in here if j.bucket}),
            # 一个站可能有好几条上限（按招聘项目分）。空列表 = 什么都没记到，
            # 前端要显示"未知"而不是"无限制"。
            # 「开始填表」按钮上显示的数字。跟列表一起返回而不是单开端点：
            # 分两次请求只会让"按钮还不知道该显示几"变成一种可能的中间状态。
            "fill_pending": len(_jobs_awaiting_fill(site)),
            "limits": [vars(l) for l in limits],
            "brief": vars(brief) if brief else None,
        }
    return JSONResponse({
        "jobs": [vars(j) for j in items],
        "total": len(items),
        "categories": categories,
        "sites": site_info,
    })


def _jobs_awaiting_fill(site_name: str) -> list:
    """这个站还等着填表的岗位：已批准 − 已填过表 − 已经排在队列里。

    **只有一份实现**：列表接口要拿它的**数量**（按钮上显示「开始填表 N」），
    start-fill 要拿它的**内容**。两处各算一遍就是同一规则两份实现，必然漂移。

    "已填过表"看 `pending_applications.source_job_id`（m2 落库时写的回指）；
    "已在队列"看队列快照——排着但还没跑到的岗位那时还没有回指记录，光看前者会把
    同一个岗位排第二遍，而那等于再往企业系统传一次简历。
    """
    tracker = app.state.tracker
    already = {a.source_job_id for a in tracker.get_pending_applications()
               if a.source_job_id is not None}
    snap = app.state.workflow_queue.snapshot()
    in_flight = [snap["current"]] if snap.get("current") else []
    for item in list(snap.get("pending") or []) + in_flight:
        if item.get("workflow") == "m2":
            already.add((item.get("params") or {}).get("pending_job_id"))
    return [j for j in tracker.get_pending_jobs(status="approved")
            if j.site_name == site_name and j.id not in already]


@app.post("/api/checkpoint1/sites/{site_name}/start-fill")
async def start_site_fill(site_name: str) -> JSONResponse:
    """把这个站**所有已批准、还没填过表**的岗位一次性排进队列。

    **为什么不在批准时就排**（旧行为）：批准即入队 m2，于是点下第一个岗位的批准，
    浏览器立刻被占住，剩下的岗位连看都没法看（用户 2026-08-16 实测）。审批是「逐个
    判断」，填表是「批量执行」，绑在一起等于强迫人一次只审一个。拆开之后：先把一个
    站的岗位挨个看完、批完，再点一次这个按钮开始跑。

    「还没填过表」的依据是 `pending_applications.source_job_id`——m2 落库时写的回指。
    重排一个已经填过的岗位等于**再往企业系统传一次简历**，所以这里按差集过滤。
    """
    _initialize_state()
    todo = _jobs_awaiting_fill(site_name)
    ids = [app.state.workflow_queue.enqueue(
        "m2", {"pending_job_id": j.id}, source="manual").id for j in todo]
    return JSONResponse({"ok": True, "queued": len(ids), "queue_ids": ids})


@app.put("/api/checkpoint1/site-limit/{site_name}")
async def set_checkpoint1_site_limit(site_name: str, body: dict) -> JSONResponse:
    """人工填写/修正本站的投递数量上限。

    **存在理由**：不能假设 agent 一定拿得到我们以为它拿得到的信息（用户
    2026-08-14）。三态设计保证了"没找到"不会被伪装成"没有限制"，但只做到诚实
    不够——人看见「上限未知」之后得有地方把自己知道的填进去。

    `evidence` 在这里是人写的（"我自己在投递须知里看到的"），跟 agent 抄的原文
    存在同一列：两者都是"这个数字凭什么"的说明，语义相同，没必要分列。
    """
    _initialize_state()
    status = body.get("status")
    if status not in ("unknown", "no_limit", "limited"):
        return JSONResponse({"ok": False, "error": "status must be unknown/no_limit/limited"},
                            status_code=400)
    limit = body.get("max_applications")
    if status == "limited" and not isinstance(limit, int):
        return JSONResponse({"ok": False, "error": "limited requires an integer max_applications"},
                            status_code=400)
    # 人填的上限默认按全站算——人说得清范围，说不清也不会去填这个框。
    scope = body.get("scope") or "site"
    scope_name = str(body.get("scope_name") or "")
    if status == "unknown":
        # 人工清空 = 真的把它退回未知，要绕过 upsert 的"unknown 不覆盖已知"保护
        # （那条是防 agent 用无知覆盖已知，不该拦住人主动重置）。SQL 在
        # tracker.clear_site_limit 里，端点不自持——铁律见 CLAUDE.md。
        app.state.tracker.clear_site_limit(site_name, scope_name)
        return JSONResponse({"ok": True, "limit": None})

    app.state.tracker.upsert_site_limit(
        site_name=site_name,
        status=status,
        scope=scope,
        scope_name=scope_name,
        max_applications=limit if status == "limited" else None,
        applied_count=body.get("applied_count", -1),
        evidence=str(body.get("evidence") or "")[:500],
    )
    got = app.state.tracker.get_site_limit(site_name, scope_name if scope == "bucket" else "")
    return JSONResponse({"ok": True, "limit": vars(got) if got else None})


@app.post("/api/checkpoint1/jobs/{job_id}/review")
async def review_checkpoint1_job(job_id: int, body: dict) -> JSONResponse:
    """纠正类别 / 标记为 golden 案例。**不改审批状态。**

    跟 approve 拆开是因为它们写的是不同的列：这里写 `category` + `is_golden`，
    approve 写 `status/reason/decided_at`。合成一个端点就会出现两条写 `category`
    的路径，正是本项目连抓四例漂移的形状。

    golden = 审批人确认"这条纠正拿去教 agent"，会被渲染进选岗 prompt
    （multisite.preferences.render_golden_examples）。它跟"顺手改了个类别"分开：
    随手一改不见得是标准案例，没确认过的例子进 prompt 只会教偏。
    """
    _initialize_state()
    tracker = app.state.tracker
    if tracker.get_pending_job(job_id) is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    category = body.get("category")
    is_golden = body.get("is_golden")
    if category is None and is_golden is None:
        return JSONResponse({"ok": False, "error": "nothing to update"}, status_code=400)
    tracker.set_pending_job_review(job_id, category=category, is_golden=is_golden)
    job = tracker.get_pending_job(job_id)
    return JSONResponse({"ok": True, "job": vars(job)})


@app.post("/api/checkpoint1/jobs/{job_id}/approve")
async def approve_checkpoint1_job(job_id: int, body: dict | None = None) -> JSONResponse:
    """Checkpoint 1 的 go 信号。

    `category` 是审批人纠正后的类别（不传 = 保留现有值）。端点层可以调两个
    tracker 方法把"改类别"和"批准"一次做完——薄接线是端点的职责；但**列的写入
    实现仍然各只有一份**，这里没有第二段 SQL。
    """
    _initialize_state()
    tracker = app.state.tracker
    if tracker.get_pending_job(job_id) is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    category = (body or {}).get("category")
    if category is not None:
        tracker.set_pending_job_review(job_id, category=category)
    rowcount = tracker.decide_pending_job(job_id, "approved")
    if rowcount == 0:
        return JSONResponse({"ok": False, "error": "already decided"}, status_code=409)
    # **批准只标记，不开跑**：填表由站点级的 start-fill 统一触发，见那个端点的说明。
    return JSONResponse({"ok": True, "job": vars(tracker.get_pending_job(job_id))})


@app.post("/api/checkpoint1/jobs/{job_id}/reject")
async def reject_checkpoint1_job(job_id: int, body: dict | None = None) -> JSONResponse:
    _initialize_state()
    tracker = app.state.tracker
    if tracker.get_pending_job(job_id) is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    rowcount = tracker.decide_pending_job(job_id, "rejected", reason=(body or {}).get("reason"))
    if rowcount == 0:
        return JSONResponse({"ok": False, "error": "already decided"}, status_code=409)
    return JSONResponse({"ok": True})


@app.post("/api/checkpoint1/batch")
async def decide_checkpoint1_batch(body: dict) -> JSONResponse:
    """批量审批。一次选岗能出十几个候选，逐个点太费事。

    **逐条独立处理、不整体回滚**：已经被别处决定过的行返回 0 行，这里记进 skipped
    继续走下一条，而不是让一条冲突把整批打回。批量审批的语义是"把这些都处理掉"，
    中途失败留下一半已处理一半没处理，反而更难收拾。
    """
    _initialize_state()
    tracker = app.state.tracker
    decision = body.get("decision")
    if decision not in ("approved", "rejected"):
        return JSONResponse({"ok": False, "error": "decision must be approved/rejected"},
                            status_code=400)
    ids = body.get("ids")
    if not isinstance(ids, list) or not ids:
        return JSONResponse({"ok": False, "error": "ids must be a non-empty list"}, status_code=400)

    # {id: 纠正后的类别}，只在 approved 时有意义
    categories = body.get("categories") or {}
    reason = body.get("reason")
    decided, skipped = [], []
    for job_id in ids:
        if tracker.get_pending_job(job_id) is None:
            skipped.append(job_id)
            continue
        if decision == "approved":
            corrected = categories.get(str(job_id))
            if corrected is not None:
                tracker.set_pending_job_review(job_id, category=corrected)
        rowcount = tracker.decide_pending_job(
            job_id, decision, reason=reason if decision == "rejected" else None,
        )
        (decided if rowcount else skipped).append(job_id)
    return JSONResponse({"ok": True, "decided": decided, "skipped": skipped})


# ── 跨站点投递审批（多站点扩展 Layer 2；见 docs/multi-site-expansion-design.md）──

@app.get("/api/pending-applications")
async def list_pending_applications(status: str | None = None) -> JSONResponse:
    _initialize_state()
    items = app.state.tracker.get_pending_applications(status=status)
    return JSONResponse({"applications": [vars(a) for a in items], "total": len(items)})


@app.get("/api/pending-applications/screenshot/{name}")
async def get_pending_application_screenshot(name: str):
    """表单整页截图。审批人靠它判断字段在页面上属于哪个分区——字段名本身常常
    不够（「学校名称」是问本科还是硕士？）。"""
    from fastapi.responses import FileResponse

    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="非法文件名")  # 防路径穿越
    path = DATA_DIR / "multisite_screenshots" / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="截图不存在")
    return FileResponse(str(path), media_type="image/png")


@app.get("/api/pending-applications/{application_id}")
async def get_pending_application(application_id: int) -> JSONResponse:
    _initialize_state()
    rec = app.state.tracker.get_pending_application(application_id)
    if rec is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    return JSONResponse(vars(rec))


@app.post("/api/pending-applications/{application_id}/approve")
async def approve_pending_application(application_id: int, body: dict) -> JSONResponse:
    """Layer 2 go-signal. `fields` in the body is the reviewer-edited final field
    list (government_id values filled in by hand) that Layer 3 will act on."""
    _initialize_state()
    tracker = app.state.tracker
    if tracker.get_pending_application(application_id) is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    fields = body.get("fields")
    if not isinstance(fields, list):
        return JSONResponse({"ok": False, "error": "fields must be a list"}, status_code=400)
    rowcount = tracker.decide_pending_application(application_id, "approved", fields=fields)
    if rowcount == 0:
        return JSONResponse({"ok": False, "error": "already decided"}, status_code=409)

    # 审批人顺手填的、personal_info 里原来没有的 demographic 事实，存回去供以后
    # 复用（用户 2026-08-13 提出）。government_id/open_question 不碰，已有 key
    # （含 info_pool.basic_info 里的姓名/电话/邮箱）不覆盖，见
    # multisite/personal_info_loader.py::save_new_facts。
    # 显式传本模块的 DATA_DIR（而非用 save_new_facts 自己的默认值）——测试夹具
    # 靠 monkeypatch DATA_DIR 隔离文件系统，用默认值会绕过隔离、写到真实用户数据。
    from multisite.personal_info_loader import save_new_facts
    saved_new_facts = save_new_facts(fields, DATA_DIR / "personal_info", DATA_DIR / "info_pool.yaml")
    return JSONResponse({"ok": True, "saved_new_facts": saved_new_facts})


@app.post("/api/pending-applications/{application_id}/reject")
async def reject_pending_application(application_id: int, body: dict | None = None) -> JSONResponse:
    _initialize_state()
    tracker = app.state.tracker
    if tracker.get_pending_application(application_id) is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    reason = (body or {}).get("reason")
    rowcount = tracker.decide_pending_application(application_id, "rejected", reason=reason)
    if rowcount == 0:
        return JSONResponse({"ok": False, "error": "already decided"}, status_code=409)
    return JSONResponse({"ok": True})


# ── 个人信息（多站点扩展表单填写用的身份事实；2026-08-13 跟 info_pool 去重）──
# 姓名/电话/邮箱唯一写入口在「简历」页（info_pool.basic_info），这里只读引用，
# 不重复建编辑入口。这里管的是 identity.yaml——性别/出生日期/证件类型等不属于
# 简历抬头信息的身份事实，以及 Layer 2 审批时自动记住的新字段
# （multisite.personal_info_loader.save_new_facts）。

@app.get("/api/personal-info")
async def get_personal_info() -> JSONResponse:
    from multisite.personal_info_loader import load_identity

    # 显式传本模块的 DATA_DIR（而非用 personal_info_loader 自己的默认值）——
    # 测试夹具靠 monkeypatch DATA_DIR 隔离文件系统，用默认值会绕过隔离、读写
    # 真实用户数据（同一坑之前在 approve 端点已踩过一次）。
    pool_path = DATA_DIR / "info_pool.yaml"
    pool_basic: dict = {}
    if pool_path.exists():
        with open(pool_path, encoding="utf-8") as f:
            pool_basic = (yaml.safe_load(f) or {}).get("basic_info") or {}
    basic = {k: pool_basic.get(k, "") for k in ("name", "phone", "email")}
    return JSONResponse({"basic": basic, "identity": load_identity(DATA_DIR / "personal_info")})


@app.put("/api/personal-info")
async def save_personal_info(body: dict) -> JSONResponse:
    from multisite.personal_info_loader import load_identity, save_identity

    identity = body.get("identity")
    if not isinstance(identity, dict):
        return JSONResponse({"ok": False, "error": "identity must be an object"}, status_code=400)
    try:
        save_identity(identity, DATA_DIR / "personal_info")
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return JSONResponse({"ok": True, "identity": load_identity(DATA_DIR / "personal_info")})


@app.post("/api/conversations/{conv_id}/open-in-browser")
async def open_conversation_in_browser(conv_id: str) -> JSONResponse:
    """Navigate the shared interactive browser to this HR conversation in Boss.

    Goes through BrowserSession (one browser owner) + the SAME hardened
    VerifySessionStep and W2 navigate_to_conversation tool the pipeline uses —
    no legacy BrowserAgent / divergent _assert_logged_in. Returns 200 with
    {ok:false, code} for expected outcomes (logged out / not reachable) so the UI
    can show an accurate reason instead of a blanket "session expired".
    """
    _initialize_state()
    tracker = app.state.tracker
    conv = tracker.get_hr_conversation(conv_id)
    if conv is None:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)

    if app.state.emitter.current_workflow:
        return JSONResponse(
            {"ok": False, "code": "workflow_running", "error": "工作流运行中，请稍后再试"},
        )

    def _navigate() -> dict:
        # Locate degradation chain: jobid direct-open (O(1)) → fall back to the chat
        # search box. The search-box locate used to be a SEPARATE "搜索定位" button,
        # but that duplicated this one — it is now folded in here as the internal
        # fallback so there is a single "open this conversation" action.
        from tools.browser.w2.navigate_to_chat_list import NavigateToChatList
        from tools.browser.w2.navigate_to_conversation import NavigateToConversation
        from tools.browser.w3.search_locate_conversation import SearchLocateConversation

        bs = app.state.browser_session
        sess = bs.verify()
        if not sess["ok"]:
            return {"ok": False, "code": sess["code"], "error": sess["reason"]}
        page = bs.get_page()

        boss_id = getattr(conv, "boss_conv_id", "") or ""
        job_id = getattr(conv, "job_id", "") or ""
        # Primary path: both stable ids present → direct-open the conversation URL,
        # no need to load the chat list first.
        if job_id and boss_id and boss_id != "62001":
            res = NavigateToConversation(browser=page).execute(
                conv_id=conv.conv_id, company=conv.company, hr_name=conv.hr_name,
                boss_conv_id=boss_id, job_id=job_id,
            )
            if res.ok and res.data.get("method") == "direct_url":
                return {"ok": True, "method": "direct_url"}

        # Fallback: open the chat list, then locate via the search box (reaches
        # conversations that have sunk below the loaded scroll window).
        nav = NavigateToChatList(browser=page).execute()
        if not nav.ok:
            return {"ok": False, "code": "chat_list_error", "error": nav.error or "无法打开聊天列表"}
        loc = SearchLocateConversation(browser=page).execute(
            conv_id=conv.conv_id, company=conv.company, hr_name=conv.hr_name,
        )
        if loc.ok and loc.data.get("located"):
            return {"ok": True, "method": "search"}
        return {"ok": False, "code": "not_found", "error": "未定位到该会话（可能已沉出列表）"}

    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _navigate)
        return JSONResponse(result)
    except BaseException as exc:
        import traceback
        traceback.print_exc()
        return JSONResponse({"ok": False, "code": "error", "error": str(exc)}, status_code=500)


@app.get("/api/workflow/stream")
async def workflow_stream(request: Request):
    _initialize_state()
    emitter: ProgressEmitter = request.app.state.emitter
    q = emitter.subscribe()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event: ProgressEvent = q.get_nowait()
                    yield {
                        "data": json.dumps(event_to_dict(event), ensure_ascii=False),
                    }
                except queue.Empty:
                    await asyncio.sleep(0.2)
        finally:
            emitter.unsubscribe(q)

    return EventSourceResponse(event_generator())


@app.get("/api/dev/page-inspect")
async def dev_page_inspect() -> JSONResponse:
    """Dump window._PAGE, common user fields, and dialog button DOM from the currently open login browser."""
    _initialize_state()
    bs = app.state.browser_session
    if not bs.is_open():
        return JSONResponse({"error": "没有打开的浏览器"}, status_code=400)

    def _inspect() -> dict:
        page = bs.get_page()
        js = """
(function() {
  var result = {};

  // User identity fields
  if (window._PAGE) {
    result._PAGE = {};
    for (var k in window._PAGE) {
      try { result._PAGE[k] = window._PAGE[k]; } catch(e) {}
    }
  }
  var userCandidates = ['window._PAGE && window._PAGE.uid',
    'window._PAGE && window._PAGE.userId',
    'window._PAGE && window._PAGE.encryptUid'];
  result.userCandidates = {};
  userCandidates.forEach(function(c) {
    try { result.userCandidates[c] = eval(c); } catch(e) { result.userCandidates[c] = null; }
  });

  // ── Dialog button inspection ──
  // Find ALL buttons currently in DOM, capture text + full ancestor class chain
  var buttons = document.querySelectorAll('button, a[class*="btn"]');
  result.buttons = [];
  for (var i = 0; i < buttons.length; i++) {
    var btn = buttons[i];
    var txt = (btn.innerText || btn.textContent || '').trim();
    if (!txt) continue;
    // Walk up to collect classes
    var chain = [];
    var el = btn;
    for (var d = 0; d < 6 && el; d++) {
      chain.push((el.tagName || '').toLowerCase() + (el.className ? '.' + String(el.className).replace(/\\s+/g, '.') : ''));
      el = el.parentElement;
    }
    result.buttons.push({text: txt, tag: btn.tagName, chain: chain.join(' > ')});
  }

  // Targeted: find 留在此页 and its full DOM path
  var stay = null;
  var allBtns = document.querySelectorAll('button');
  for (var j = 0; j < allBtns.length; j++) {
    if ((allBtns[j].innerText || '').includes('\\u7559\\u5728\\u6b64\\u9875')) { stay = allBtns[j]; break; }
  }
  if (stay) {
    var path = [];
    var node = stay;
    for (var k = 0; k < 8 && node; k++) {
      var info = node.tagName + (node.id ? '#'+node.id : '') + (node.className ? '.'+String(node.className).trim().replace(/\\s+/g,'.') : '');
      path.push(info);
      node = node.parentElement;
    }
    result.stay_btn_path = path;
    result.stay_btn_outerHTML = stay.outerHTML;
  } else {
    result.stay_btn_path = null;
  }

  result.url = location.href;
  return result;
})()
"""
        return page.run_js(js) or {}

    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(None, _inspect)
    return JSONResponse(data)


@app.post("/api/dev/restart")
async def dev_restart() -> JSONResponse:
    """Touch server.py to trigger uvicorn --reload hot-restart."""
    import threading as _threading

    def _do_restart() -> None:
        import time as _time
        _time.sleep(0.2)  # let response reach the browser first
        Path(__file__).touch()

    _threading.Thread(target=_do_restart, daemon=True).start()
    return JSONResponse({"status": "restarting"})


@app.post("/api/workflow/stop")
async def workflow_stop() -> JSONResponse:
    _initialize_state()
    emitter: ProgressEmitter = app.state.emitter
    if not emitter.current_workflow:
        return JSONResponse({"ok": False, "detail": "没有正在运行的 workflow"})
    emitter.request_stop()
    return JSONResponse({"ok": True, "stopping": emitter.current_workflow})


@app.get("/api/schedule")
async def get_schedule() -> JSONResponse:
    _initialize_state()
    cfg = _load_schedule_config()
    nrt = _get_scheduler().next_run_times()
    cfg["_next_runs"] = nrt["cron"]
    cfg["_next_interval_runs"] = nrt["interval"]
    cfg["_scheduler_running"] = nrt["running"]
    from services.settings_resolver import resolve_params
    cfg["daily_limit"] = int(resolve_params("w1", {}, app.state.config, DATA_DIR).get("daily_limit", 0))
    return JSONResponse(cfg)


@app.put("/api/schedule")
async def update_schedule(body: dict) -> JSONResponse:
    _initialize_state()
    cfg = _load_schedule_config()
    for workflow in ("apply", "check"):
        if workflow not in body:
            continue
        workflow_body = body[workflow]
        if not isinstance(workflow_body, dict):
            raise HTTPException(status_code=400, detail=f"Invalid schedule payload for {workflow}")
        if "enabled" in workflow_body:
            cfg[workflow]["enabled"] = bool(workflow_body["enabled"])
        if "times" in workflow_body:
            times = workflow_body["times"]
            if not isinstance(times, list):
                raise HTTPException(status_code=400, detail=f"Invalid times payload for {workflow}")
            cfg[workflow]["times"] = [str(time_str) for time_str in times if isinstance(time_str, str)]
        if "interval_enabled" in workflow_body:
            cfg[workflow]["interval_enabled"] = bool(workflow_body["interval_enabled"])
        if "interval_minutes" in workflow_body:
            cfg[workflow]["interval_minutes"] = max(0, int(workflow_body["interval_minutes"]))
        if "params" in workflow_body:
            params = workflow_body["params"]
            if not isinstance(params, dict):
                raise HTTPException(status_code=400, detail=f"Invalid params payload for {workflow}")
            cfg[workflow]["params"].update(params)
    sc_body = body.get("selfcheck")
    if isinstance(sc_body, dict):
        d = cfg["selfcheck"]
        if "enabled" in sc_body:
            d["enabled"] = bool(sc_body["enabled"])
        if "interval_minutes" in sc_body:
            d["interval_minutes"] = max(0, int(sc_body["interval_minutes"]))
        if "w1_max" in sc_body:
            d["w1_max"] = max(0, int(sc_body["w1_max"]))
        if "w2_max" in sc_body:
            d["w2_max"] = max(1, int(sc_body["w2_max"]))
        if "with_probes" in sc_body:
            d["with_probes"] = bool(sc_body["with_probes"])
    _save_schedule_config(cfg)
    _rebuild_scheduler(cfg)
    # daily_limit 是 W1 运行参数（Layer 3）的用户默认 → 写 user_settings.yaml
    from services.settings_resolver import resolve_params, save_user_default
    if "daily_limit" in body:
        new_limit = max(0, int(body["daily_limit"]))
        save_user_default("w1", {"daily_limit": new_limit}, DATA_DIR)
    result_cfg = dict(cfg)
    result_cfg["daily_limit"] = int(resolve_params("w1", {}, app.state.config, DATA_DIR).get("daily_limit", 0))
    return JSONResponse({"ok": True, "config": result_cfg})


@app.get("/api/schedule/log")
async def get_schedule_log(limit: int = 50) -> JSONResponse:
    _initialize_state()
    limit = max(1, int(limit))
    entries: list[dict] = []
    if SCHEDULE_LOG_PATH.exists():
        lines = SCHEDULE_LOG_PATH.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(_json.loads(line))
            except _json.JSONDecodeError:
                continue
            if len(entries) >= limit:
                break
    return JSONResponse({"log": entries, "total": len(entries)})


@app.post("/api/selfcheck")
async def run_selfcheck() -> JSONResponse:
    """Run lightweight infra probes (browser+session / DB / LLM) and return a report.
    Refused while a workflow is running -- the browser probe would collide with it."""
    _initialize_state()
    if app.state.emitter.current_workflow:
        raise HTTPException(status_code=409, detail="有 workflow 正在运行，请结束后再自检")
    from services import selfcheck
    report = selfcheck.run_probes(
        data_dir=DATA_DIR,
        tracker=app.state.tracker,
        model_router=app.state.model_router,
    )
    logger.info("selfcheck: ok=%s probes=%s", report.get("ok"), [
        f"{p['name']}={'ok' if p['ok'] else 'FAIL'}" for p in report.get("probes", [])
    ])
    return JSONResponse(report)


@app.post("/api/regression/pytest")
def run_regression_pytest() -> JSONResponse:
    """Layer 1 regression: run the pytest suite (~10s) and return a parsed report
    grouped by test file. Sync def so FastAPI runs it in a threadpool. Does not
    touch the browser, so it is allowed alongside a running workflow."""
    from services import regression
    report = regression.run_pytest(BASE_DIR)
    logger.info("regression pytest: ok=%s %s/%s passed in %ss",
                report.get("ok"), report.get("passed"), report.get("total"),
                report.get("duration_s"))
    return JSONResponse(report)


@app.post("/api/regression/invariants")
def run_regression_invariants() -> JSONResponse:
    """Layer 2: read-only data-invariant checks over the tracker (status/stage enums,
    reply consistency). Fast, no browser."""
    _initialize_state()
    from services import regression
    report = regression.run_invariants(app.state.tracker)
    logger.info("regression invariants: ok=%s (%d checks)", report.get("ok"),
                len(report.get("checks", [])))
    return JSONResponse(report)


@app.post("/api/regression/smoke")
async def trigger_regression_smoke(background_tasks: BackgroundTasks, body: dict | None = None) -> JSONResponse:
    """Layer 3: trigger real-machine smoke (W1+W2) in the background. Opens a real
    browser, so it's refused while a workflow runs. mode='dry' (default) is a
    harmless read-path check; mode='live' really applies/sends and is additionally
    gated on the Boss daily cap. w1_max/w2_max control scale (live defaults to 1/1
    to minimise real side effects)."""
    _initialize_state()
    if app.state.emitter.current_workflow:
        raise HTTPException(status_code=409, detail="有 workflow 正在运行，请结束后再冒烟")
    body = body or {}
    dry_run = str(body.get("mode", "dry")) != "live"
    if dry_run:
        w1_max = int(body.get("w1_max", 2))
        w2_max = int(body.get("w2_max", 5))
    else:
        # Live smoke really sends greetings -> honour the same daily-cap gate as selfcheck.
        if _is_rate_limited_today():
            raise HTTPException(status_code=409, detail="今日已达 Boss 沟通上限，暂停真跑冒烟")
        # 5, not 1: with a single card the run frequently has nothing to apply to
        # (already applied / filtered out), so the apply path reports "not covered"
        # and the gate never actually closes. A slightly larger batch makes real
        # coverage the normal outcome rather than a lucky one.
        w1_max = int(body.get("w1_max", 5))
        w2_max = int(body.get("w2_max", 5))

    # Workflow knobs mirror the console's so the smoke can reproduce a real run's
    # conditions. score_threshold matters most: at the stock 60 a smoke may apply
    # nothing and therefore cover nothing, leaving the gate permanently open.
    def _opt_int(key):
        v = body.get(key)
        return int(v) if v not in (None, "") else None

    score_threshold = _opt_int("score_threshold")
    no_response_days = _opt_int("no_response_days")
    stale_conv_days = _opt_int("stale_conv_days")

    background_tasks.add_task(_get_orch().run_regression_smoke, dry_run=dry_run,
                              w1_max=w1_max, w2_max=w2_max,
                              score_threshold=score_threshold,
                              no_response_days=no_response_days,
                              stale_conv_days=stale_conv_days)
    return JSONResponse({"status": "started", "mode": "dry" if dry_run else "live",
                         "w1_max": w1_max, "w2_max": w2_max,
                         "score_threshold": score_threshold,
                         "no_response_days": no_response_days,
                         "stale_conv_days": stale_conv_days})


@app.get("/api/runs/{run_id}/diagnose")
async def diagnose_run_endpoint(run_id: str) -> JSONResponse:
    """Deterministic verdict for one run, derived from its JSONL log.

    Works for ANY run (manual / scheduled / smoke), not just the smoke's own --
    the log is the durable record, so a run from weeks ago can still be judged.
    See docs/run-log-guide.md for how to read the report.
    """
    from services import run_diagnostics as rd

    diag = rd.diagnose_run(run_id)
    diag["report"] = rd.render_report(diag, rd.check_params_applied(diag, diag.get("params") or {}))
    return JSONResponse(diag)


@app.get("/api/runs/diagnose/recent")
async def diagnose_recent_runs(limit: int = 20, pipeline: str | None = None,
                               only_problems: bool = False) -> JSONResponse:
    """Batch health sweep over recent runs. only_problems=true filters to runs we
    could judge AND that came back bad -- legacy/unjudgeable logs are excluded so
    they don't read as failures."""
    from services import run_diagnostics as rd

    rows = []
    for run_id in rd.find_runs(pipeline=pipeline, limit=max(1, min(limit, 200))):
        d = rd.diagnose_run(run_id)
        if only_problems and (not d.get("diagnosable") or d.get("ok")):
            continue
        rows.append({
            "run_id": d["run_id"], "pipeline": d.get("pipeline"),
            "trigger": d.get("trigger"), "status": d.get("status"),
            "ok": d.get("ok"), "diagnosable": d.get("diagnosable"),
            "complete": d.get("complete"), "started_at": d.get("started_at"),
            "outbound": d.get("outbound"), "anomalies": d.get("anomalies"),
        })
    return JSONResponse({"runs": rows, "count": len(rows)})


@app.get("/api/regression/smoke/last")
async def get_regression_smoke_last() -> JSONResponse:
    """Most recent smoke report (or null if never run)."""
    if REGRESSION_SMOKE_LOG.exists():
        for line in reversed(REGRESSION_SMOKE_LOG.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if line:
                return JSONResponse({"report": _json.loads(line)})
    return JSONResponse({"report": None})


@app.post("/api/selfcheck/cycle")
async def trigger_selfcheck_cycle(background_tasks: BackgroundTasks, body: dict | None = None) -> JSONResponse:
    """Manually trigger a full self-check cycle (probes -> real W1 -> real W2) in the
    background. Params default to the configured self-check schedule."""
    _initialize_state()
    if app.state.emitter.current_workflow:
        raise HTTPException(status_code=409, detail="有 workflow 正在运行，请结束后再自检")
    body = body or {}
    cfg = _load_schedule_config().get("selfcheck", {})
    w1_max = int(body.get("w1_max", cfg.get("w1_max", 10)))
    w2_max = int(body.get("w2_max", cfg.get("w2_max", 300)))
    with_probes = bool(body.get("with_probes", cfg.get("with_probes", True)))
    background_tasks.add_task(
        _run_selfcheck_cycle, w1_max=w1_max, w2_max=w2_max, with_probes=with_probes, trigger_type="manual",
    )
    return JSONResponse({"status": "started", "w1_max": w1_max, "w2_max": w2_max, "with_probes": with_probes})


@app.get("/api/selfcheck/history")
async def get_selfcheck_history(limit: int = 20) -> JSONResponse:
    _initialize_state()
    limit = max(1, int(limit))
    entries: list[dict] = []
    if SELFCHECK_LOG_PATH.exists():
        for line in reversed(SELFCHECK_LOG_PATH.read_text(encoding="utf-8").splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(_json.loads(line))
            except _json.JSONDecodeError:
                continue
            if len(entries) >= limit:
                break
    return JSONResponse({"history": entries, "total": len(entries)})


@app.get("/api/workflow/status")
async def workflow_status() -> JSONResponse:
    _initialize_state()
    return JSONResponse({"running": app.state.emitter.current_workflow})


# 哪些 workflow 的运行参数支持「设为默认」。**判据是"它有每次都一样的参数"**：
# w3 没有（发的是当前所有已批准回复），m2 也没有（岗位每次都不同）。
_DEFAULTABLE_WORKFLOWS = ("w1", "w2", "m1")


def _resolved_defaults() -> dict:
    from services.settings_resolver import resolve_params
    # m1 = 多站点选岗。它跟 w1/w2 一样有"每次都一样"的参数（站点、入口页 URL），
    # 走同一套「设为默认」机制，不另起炉灶。
    return {
        wf: resolve_params(wf, {}, app.state.config, DATA_DIR)
        for wf in _DEFAULTABLE_WORKFLOWS
    }


@app.get("/api/workflow/defaults")
async def get_workflow_defaults() -> JSONResponse:
    """Layer-3 运行参数的已解析默认值（出厂 config.yaml < user_settings.yaml），供前端 WorkflowPanel 启动回填。"""
    _initialize_state()
    return JSONResponse(_resolved_defaults())


@app.post("/api/workflow/defaults")
async def save_workflow_defaults(body: dict | None = None) -> JSONResponse:
    """前端「设为默认」：把 updates 写入 data/user_settings.yaml[workflow]（部分覆盖），返回回填后的默认。"""
    _initialize_state()
    body = body or {}
    workflow = body.get("workflow")
    if workflow not in _DEFAULTABLE_WORKFLOWS:
        raise HTTPException(status_code=400,
                            detail=f"workflow must be one of {'|'.join(_DEFAULTABLE_WORKFLOWS)}")
    updates = body.get("updates")
    if not isinstance(updates, dict):
        raise HTTPException(status_code=400, detail="updates must be an object")
    # 只接受该 workflow config 节里已知的键，过滤垃圾键与 None 值
    allowed = set((app.state.config.get(workflow) or {}).keys())
    clean = {k: v for k, v in updates.items() if k in allowed and v is not None}
    from services.settings_resolver import save_user_default
    save_user_default(workflow, clean, DATA_DIR)
    return JSONResponse(_resolved_defaults())


def _enqueue_response(workflow: str, params: dict, source: str = "manual") -> JSONResponse:
    """Enqueue one workflow item. status is "started" when nothing was ahead of
    it (queue idle, no browser op running) so it runs immediately, else "queued".
    Decided from the PRE-enqueue state to avoid racing the worker; callers that
    only check response.ok keep working either way."""
    q = app.state.workflow_queue
    pre = q.snapshot()
    idle = (
        pre["current"] is None
        and not pre["pending"]
        and not getattr(app.state.emitter, "current_workflow", None)
    )
    item = q.enqueue(workflow, params, source=source)
    return JSONResponse({
        "status": "started" if idle else "queued",
        "id": item.id,
        "workflow": workflow,
        "running": not idle,
    })


@app.post("/api/workflow/apply")
async def trigger_apply(body: dict | None = None) -> JSONResponse:
    """Enqueue a W1 apply run (runs immediately if the queue is idle, else waits
    its turn — no longer 409s when another workflow is running)."""
    _initialize_state()
    body = body or {}
    # max_cards 兼容旧键 apply_limit；0/缺省 → None（resolve 时回退 w1 默认）。
    _max_cards_in = body.get("max_cards", body.get("apply_limit"))
    params = {
        "dry_run": body.get("dry_run"),
        "score_threshold": body.get("score_threshold"),
        "max_cards": (int(_max_cards_in) if _max_cards_in and int(_max_cards_in) > 0 else None),
        "headless": body.get("headless"),
        "debug": body.get("debug"),
        "search_url": body.get("search_url") or None,
    }
    return _enqueue_response("w1", params)


@app.post("/api/workflow/check")
async def trigger_check(body: dict | None = None) -> JSONResponse:
    _initialize_state()
    body = body or {}
    params = {
        "dry_run": body.get("dry_run"),
        "max_conversations": body.get("max_conversations"),
        # Frontend sends a single `days` field; map it to no_response_days.
        "no_response_days": body.get("no_response_days", body.get("days")),
        "stale_conv_days": body.get("stale_conv_days"),
        "headless": body.get("headless"),
        "debug": body.get("debug"),
    }
    return _enqueue_response("w2", params)


@app.post("/api/workflow/reply")
async def trigger_reply(body: dict | None = None) -> JSONResponse:
    """W3: send user-approved replies (approved/revision) with delivery verification."""
    _initialize_state()
    body = body or {}
    params = {
        "dry_run": body.get("dry_run"),
        "max_replies": body.get("max_replies"),
        "headless": body.get("headless"),
        "debug": body.get("debug"),
    }
    return _enqueue_response("w3", params)


@app.get("/api/workflow/queue")
async def get_workflow_queue() -> JSONResponse:
    _initialize_state()
    return JSONResponse(app.state.workflow_queue.snapshot())


@app.post("/api/workflow/queue")
async def add_workflow_queue(body: dict | None = None) -> JSONResponse:
    """Explicitly add one item to the queue (source=queue)."""
    _initialize_state()
    body = body or {}
    # 白名单直接引用队列的 VALID_WORKFLOWS，不再手抄一份 ("w1","w2","w3")——
    # 手抄的那份在 m1/m2 上线后就漏了，表现为"队列支持但这个端点拒收"。
    from services.workflow_queue import VALID_WORKFLOWS

    wf = body.get("workflow")
    if wf not in VALID_WORKFLOWS:
        raise HTTPException(status_code=400,
                            detail=f"workflow must be one of {'|'.join(VALID_WORKFLOWS)}")
    return _enqueue_response(wf, body.get("params") or {}, source="queue")


@app.post("/api/workflow/queue/batch")
async def add_workflow_queue_batch(body: dict | None = None) -> JSONResponse:
    """Add an ordered chain of items in one call (e.g. W1 -> W2 -> W3)."""
    _initialize_state()
    body = body or {}
    items = body.get("items") or []
    ids = []
    for it in items:
        # 白名单引用队列那一份，不手抄——这是同一个列表在本文件里的第三处，
        # 前两处都因为漏了 m1/m2 出过问题。
        from services.workflow_queue import VALID_WORKFLOWS

        wf = it.get("workflow")
        if wf not in VALID_WORKFLOWS:
            raise HTTPException(status_code=400, detail=f"bad workflow {wf!r}")
        qi = app.state.workflow_queue.enqueue(wf, it.get("params") or {}, source="queue")
        ids.append(qi.id)
    return JSONResponse({"status": "queued", "ids": ids})


@app.delete("/api/workflow/queue/{item_id}")
async def remove_workflow_queue_item(item_id: str) -> JSONResponse:
    _initialize_state()
    return JSONResponse({"ok": app.state.workflow_queue.remove(item_id)})


@app.post("/api/workflow/queue/clear")
async def clear_workflow_queue() -> JSONResponse:
    _initialize_state()
    return JSONResponse({"ok": True, "removed": app.state.workflow_queue.clear()})


@app.post("/api/workflow/queue/move")
async def move_workflow_queue_item(body: dict | None = None) -> JSONResponse:
    """Reorder a pending item: direction < 0 earlier, > 0 later."""
    _initialize_state()
    body = body or {}
    ok = app.state.workflow_queue.move(str(body.get("id", "")), int(body.get("direction", 0)))
    return JSONResponse({"ok": ok})


@app.post("/api/workflow/queue/reorder")
async def reorder_workflow_queue(body: dict | None = None) -> JSONResponse:
    """Set the full pending order (drag-and-drop): body {ids: [...]}."""
    _initialize_state()
    body = body or {}
    ids = body.get("ids") or []
    ok = app.state.workflow_queue.reorder([str(i) for i in ids])
    return JSONResponse({"ok": ok})


@app.post("/api/workflow/queue/pause")
async def pause_workflow_queue() -> JSONResponse:
    """Pause the queue worker: the running item finishes, no new item starts."""
    _initialize_state()
    app.state.workflow_queue.pause()
    return JSONResponse({"ok": True, "paused": True})


@app.post("/api/workflow/queue/resume")
async def resume_workflow_queue() -> JSONResponse:
    _initialize_state()
    app.state.workflow_queue.resume()
    return JSONResponse({"ok": True, "paused": False})


def _build_boss_search_url(profile: dict) -> str:
    return _build_boss_search_url_shared(profile)


def _find_chrome_exe() -> str | None:
    """Find the Chrome executable on common Windows/Mac/Linux paths."""
    import sys as _sys
    candidates: list[Path] = []
    if _sys.platform == "win32":
        for base in ["LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"]:
            root = Path(os.environ.get(base, ""))
            candidates.append(root / "Google/Chrome/Application/chrome.exe")
            candidates.append(root / "Chromium/Application/chrome.exe")
    elif _sys.platform == "darwin":
        candidates = [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")]
    else:
        candidates = [Path("/usr/bin/google-chrome"), Path("/usr/bin/chromium-browser")]
    return next((str(p) for p in candidates if p.exists()), None)


@app.post("/api/preview/search")
async def preview_search() -> JSONResponse:
    """Open Chrome with the saved session profile and navigate to Boss直聘 search.
    Uses subprocess (not DrissionPage) so the browser_profile is never locked by this process."""
    import subprocess as _subprocess
    _initialize_state()

    # Through the singleton: reading profile.yaml inline here meant this preview
    # could be built from a different profile than the one /api/profile just saved.
    profile = get_config_manager(str(CONFIG_PATH), str(PROFILE_PATH)).get_profile()

    search_url = _build_boss_search_url(profile)
    chrome = _find_chrome_exe()
    if not chrome:
        raise HTTPException(status_code=500, detail="Chrome not found. Install Google Chrome.")

    # Kill previous preview process if still running
    prev: Any = getattr(app.state, "preview_proc", None)
    if prev is not None:
        try:
            prev.kill()
        except Exception:
            pass
        app.state.preview_proc = None

    proc = _subprocess.Popen(
        [chrome, f"--user-data-dir={DATA_DIR / 'browser_profile'}", search_url],
        stdout=_subprocess.DEVNULL,
        stderr=_subprocess.DEVNULL,
    )
    app.state.preview_proc = proc
    return JSONResponse({"ok": True, "url": search_url})


@app.post("/api/open-boss-browser")
async def open_boss_browser() -> JSONResponse:
    """Open the automation browser (with saved Boss直聘 session) at Boss直聘 home page."""
    import subprocess as _subprocess
    _initialize_state()
    chrome = _find_chrome_exe()
    if not chrome:
        raise HTTPException(status_code=500, detail="Chrome not found. Install Google Chrome.")

    boss_url = "https://www.zhipin.com/web/geek/chat"
    prev: Any = getattr(app.state, "boss_browser_proc", None)
    if prev is not None:
        try:
            prev.kill()
        except Exception:
            pass
        app.state.boss_browser_proc = None

    proc = _subprocess.Popen(
        [chrome, f"--user-data-dir={DATA_DIR / 'browser_profile'}", boss_url],
        stdout=_subprocess.DEVNULL,
        stderr=_subprocess.DEVNULL,
    )
    app.state.boss_browser_proc = proc
    return JSONResponse({"ok": True, "url": boss_url})


if __name__ == "__main__":
    uvicorn.run("dashboard.server:app", host="0.0.0.0", port=8765)
