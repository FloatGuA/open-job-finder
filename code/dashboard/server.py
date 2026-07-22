import json
import logging
import os
import re
import asyncio
import queue
import threading
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
from services.llm_client import build_model_router, load_config
from services.onboarding import OnboardingChecker
from services.progress_emitter import ProgressEmitter, ProgressEvent
from services.resume_manager import ResumeManager
from services.resume_parser import parse_resume_file
from services.tracker import ApplicationTracker
from tools.biz_logic.wechat_id import wechat_id_from
from pipeline.run_logger import _ui_status
from services.scheduler_service import SchedulerService
from services.workflow_orchestration import OrchestrationService


BASE_DIR = Path(__file__).resolve().parent.parent
RUNS_DIR = BASE_DIR.parent / "logs" / "runs"
DASHBOARD_DIR = BASE_DIR / "dashboard"
STATIC_DIR = DASHBOARD_DIR / "static"
DATA_DIR = BASE_DIR / "data"
ATTACHMENT_RESUME_PATH = DATA_DIR / "resume_attachment.pdf"
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
        resume_yaml_path=str(DATA_DIR / "resume_base.yaml"),
        session_path=str(DATA_DIR / "session.json"),
        config=config,
    )
    app.state.resume_manager = ResumeManager(
        base_yaml_path=str(DATA_DIR / "resume_base.yaml"),
        template_path=str(BASE_DIR / "templates" / "resume.html"),
        output_dir=str(BASE_DIR / "output" / "resumes"),
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


def _serialize_conversation(conv, messages: list[dict], job_url: str) -> dict[str, Any]:
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
        "status": conv.stage,
        "stage": conv.stage,
        "intent": conv.intent,
        "suggested_reply": reply_text,
        "needs_reply": conv.reply_status in ("pending", "approved", "revision"),
        "reply_status": conv.reply_status,
        "reply_draft": reply_text,
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
    if pipeline is not None and pipeline not in {"w1", "w2", "w3"}:
        raise HTTPException(status_code=400, detail="pipeline must be w1, w2 or w3")
    return pipeline


def _iter_run_files(pipeline: str | None = None) -> list[Path]:
    if not RUNS_DIR.exists():
        return []
    pattern = f"{pipeline}_*.jsonl" if pipeline else "*.jsonl"
    return list(RUNS_DIR.glob(pattern))


def _summarize_run_file(path: Path) -> dict[str, Any] | None:
    lines: list[str] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                lines.append(line)
    if not lines:
        return None
    first = _json.loads(lines[0])
    last = _json.loads(lines[-1])
    if first.get("event") != "run_start":
        return None
    run_id = first.get("run_id", path.stem)
    pipeline = first.get("pipeline", "")
    ended = last.get("event") == "run_end"
    return {
        "run_id": run_id,
        "pipeline": pipeline,
        "filename": path.name,
        "started_at": first.get("ts"),
        "status": last.get("status") if ended else "running",
        "duration_ms": last.get("duration_ms") if ended else None,
        "summary": last.get("summary") if ended else None,
    }


def _find_run_file(run_id: str) -> Path | None:
    """Find the JSONL file for the given run_id by matching the run_start event's run_id field."""
    for path in _iter_run_files():
        try:
            with path.open("r", encoding="utf-8") as file:
                first_line = file.readline().strip()
            if not first_line:
                continue
            first = _json.loads(first_line)
            if first.get("run_id") == run_id:
                return path
        except (OSError, _json.JSONDecodeError):
            continue
    return None


def _parse_run_detail(path: Path) -> dict[str, Any]:
    """Parse a JSONL run file into grouped steps + tools + business_events structure."""
    lines: list[str] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                lines.append(line)

    if not lines:
        return {}

    first = _json.loads(lines[0])
    last = _json.loads(lines[-1])
    ended = last.get("event") == "run_end"

    run_id = first.get("run_id", path.stem)
    pipeline = first.get("pipeline", "")

    # Collect step and tool events; everything else that is not run_start/run_end is a business event
    step_events: list[dict[str, Any]] = []
    tool_events: list[dict[str, Any]] = []
    business_events: list[dict[str, Any]] = []

    known_meta_events = {"run_start", "run_end"}
    known_trace_events = {"step", "tool"}

    for raw_line in lines:
        try:
            entry = _json.loads(raw_line)
        except _json.JSONDecodeError:
            continue
        event = entry.get("event", "")
        if event in known_meta_events:
            continue
        if event == "step":
            step_events.append(entry)
        elif event == "tool":
            tool_events.append(entry)
        else:
            business_events.append(entry)

    # Sort by timestamp
    step_events.sort(key=lambda e: e.get("ts", ""))
    tool_events.sort(key=lambda e: e.get("ts", ""))
    business_events.sort(key=lambda e: e.get("ts", ""))

    # Build steps list; attach tools to the most recent preceding step
    steps: list[dict[str, Any]] = []
    for se in step_events:
        steps.append({
            "step": se.get("step", ""),
            "scope": se.get("scope") or {},
            "status": se.get("status", ""),
            "duration_ms": se.get("duration_ms"),
            "data": se.get("data") or {},
            "error": se.get("error"),
            "ts": se.get("ts", ""),
            "tools": [],
        })

    for te in tool_events:
        tool_ts = te.get("ts", "")
        # Find the most recent step whose ts <= tool_ts
        best_idx = -1
        for idx, step in enumerate(steps):
            if step["ts"] <= tool_ts:
                best_idx = idx
        target_idx = best_idx if best_idx >= 0 else (len(steps) - 1 if steps else -1)
        tool_entry: dict[str, Any] = {
            "tool": te.get("tool", ""),
            "scope": te.get("scope") or {},
            "status": te.get("status", ""),
            "duration_ms": te.get("duration_ms"),
            "data": te.get("data") or {},
            "error": te.get("error"),
            "ts": te.get("ts", ""),
        }
        if target_idx >= 0:
            steps[target_idx]["tools"].append(tool_entry)

    be_list: list[dict[str, Any]] = [
        {
            "event": be.get("event", ""),
            "scope": be.get("scope") or {},
            "data": be.get("data") or {},
            "ts": be.get("ts", ""),
        }
        for be in business_events
    ]

    return {
        "run_id": run_id,
        "pipeline": pipeline,
        "status": last.get("status") if ended else "running",
        "started_at": first.get("ts"),
        "duration_ms": last.get("duration_ms") if ended else None,
        "summary": last.get("summary") if ended else None,
        "steps": steps,
        "business_events": be_list,
    }


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
        for path in _iter_run_files(pipeline)
        if (summary := _summarize_run_file(path)) is not None
    ]
    runs.sort(key=lambda item: item.get("started_at") or item["filename"], reverse=True)
    return JSONResponse({"runs": runs, "total": len(runs)})


@app.get("/api/runs/{run_id}")
async def get_run_detail(run_id: str) -> JSONResponse:
    path = _find_run_file(run_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    detail = _parse_run_detail(path)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Run {run_id} is empty")
    return JSONResponse(detail)


def _iso_to_epoch(ts: str) -> float:
    if not ts:
        return 0.0
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def _parse_run_events(path: Path) -> list[dict[str, Any]]:
    """Flatten a run JSONL into frontend ProgressEvent[] (the live-stream shape), so
    a finished run can be replayed into WorkflowTrack via the same buildTree the SSE
    stream feeds. The in-memory SSE buffer is capped (200, shared across workflows)
    and lost on restart, so it cannot show a *complete* past run -- the JSONL can.

    Domain status -> UI status here (single source: _ui_status); ISO ts -> epoch
    seconds; workflow field added (only run_start/step carry `pipeline` in the file,
    so it is taken once from run_start); message synthesized to match what the SSE
    path emits (run_logger.log_step / log_tool / log)."""
    lines = [ln.strip() for ln in path.open("r", encoding="utf-8") if ln.strip()]
    if not lines:
        return []
    first = _json.loads(lines[0])
    pipeline = first.get("pipeline", "") or path.stem.split("_")[0]

    out: list[dict[str, Any]] = []
    for raw in lines:
        try:
            e = _json.loads(raw)
        except _json.JSONDecodeError:
            continue
        event = e.get("event", "")
        scope = e.get("scope") or {}
        data = e.get("data") or {}
        status = e.get("status", "")
        ts = _iso_to_epoch(e.get("ts", ""))
        if event == "run_start":
            out.append({"workflow": pipeline, "step": "start", "tool": None, "status": "running",
                        "message": f"开始 {pipeline} workflow", "scope": {},
                        "detail": e.get("meta") or {}, "ts": ts})
        elif event == "run_end":
            out.append({"workflow": pipeline, "step": "done", "tool": None, "status": _ui_status(status),
                        "message": str(e.get("summary") or {}), "scope": {}, "detail": e.get("summary") or {}, "ts": ts})
        elif event == "step":
            step = e.get("step", "")
            out.append({"workflow": pipeline, "step": step, "tool": None, "status": _ui_status(status),
                        "message": f"Step {step}: {status}", "scope": scope, "detail": data, "ts": ts})
        elif event == "tool":
            tool = e.get("tool", "")
            out.append({"workflow": pipeline, "step": e.get("step", ""), "tool": tool, "status": _ui_status(status),
                        "message": f"[tool] {tool}: {status}", "scope": scope, "detail": data, "ts": ts})
        else:
            # business event. Skip file-only per-conversation traces the live SSE never
            # showed (logged visible=False), so replay mirrors the live view instead of
            # surfacing one phantom instance per filtered-out conversation. Newer logs
            # persist `visible`; older logs predate it, so also skip the known file-only
            # event (filter_decision) by name.
            if e.get("visible") is False or event == "filter_decision":
                continue
            # job_scored / job_skipped / intent_analyzed / ...: no status in file; SSE
            # emits these with status "info"; detail carries the human-readable payload
            # (score / reason / intent) the interpret layer uses.
            out.append({"workflow": pipeline, "step": event, "tool": None, "status": "info",
                        "message": f"[event] {event}", "scope": scope, "detail": {**scope, **data}, "ts": ts})
    out.sort(key=lambda x: x["ts"])
    return out


@app.get("/api/runs/{run_id}/events")
async def get_run_events(run_id: str) -> JSONResponse:
    """Full persisted event stream for one run, in frontend ProgressEvent shape, so
    WorkflowTrack can replay a finished run's complete view (not the capped buffer)."""
    path = _find_run_file(run_id)
    if path is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return JSONResponse({"events": _parse_run_events(path)})


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
        if suffix == ".pdf":
            ATTACHMENT_RESUME_PATH.write_bytes(content)
        parsed = parse_resume_file(str(saved_path))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    sections_found = [key for key, value in parsed.items() if value]
    return JSONResponse(
        {
            "success": True,
            "message": "Resume parsed and saved.",
            "sections_found": sections_found,
            "attachment_saved": suffix == ".pdf",
        }
    )


@app.get("/api/resume/blocks")
async def get_resume_blocks() -> JSONResponse:
    """简历积木库（功能一）：读取 resume_blocks.yaml（不存在返回空结构）。"""
    from services import resume_blocks
    return JSONResponse(resume_blocks.load_blocks(str(DATA_DIR / "resume_blocks.yaml")))


@app.put("/api/resume/blocks")
async def put_resume_blocks(body: dict[str, Any] = Body(...)) -> JSONResponse:
    """整存编辑后的块库；只接受已知结构的键，避免存入垃圾字段。"""
    from services import resume_blocks
    clean = resume_blocks.empty_blocks()
    bi = body.get("basic_info") or {}
    for k in clean["basic_info"]:
        if k in bi:
            clean["basic_info"][k] = str(bi[k] or "")
    clean["self_description"] = str(body.get("self_description") or "")
    for cat in resume_blocks.BLOCK_CATEGORIES:
        items = body.get(cat)
        if isinstance(items, list):
            clean[cat] = [
                {
                    "title": str(it.get("title", "")),
                    "time": str(it.get("time", "")),
                    "bullets": [str(b) for b in (it.get("bullets") or []) if str(b).strip()],
                    "summary": str(it.get("summary", "")),
                }
                for it in items if isinstance(it, dict)
            ]
    resume_blocks.save_blocks(clean, str(DATA_DIR / "resume_blocks.yaml"))
    return JSONResponse({"ok": True})


@app.post("/api/resume/blocks/build")
async def build_resume_blocks_endpoint(body: dict[str, Any] | None = None) -> JSONResponse:
    """用 LLM 把已解析简历(resume_base.yaml) + 自我描述整理成结构化块库，存盘并返回（解析预填）。"""
    _initialize_state()
    body = body or {}
    import yaml as _yaml
    from services import resume_blocks
    base_path = DATA_DIR / "resume_base.yaml"
    resume_base: dict = {}
    if base_path.exists():
        with base_path.open("r", encoding="utf-8") as f:
            resume_base = _yaml.safe_load(f) or {}
    self_desc = str(body.get("self_description") or "")
    blocks = resume_blocks.build_blocks(resume_base, self_desc, app.state.model_router)
    resume_blocks.save_blocks(blocks, str(DATA_DIR / "resume_blocks.yaml"))
    return JSONResponse(blocks)


# ── 功能二：岗位特化生成（预制模板 / 简历方案 / 招呼语 / 渲染 PDF）────────────
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
    blocks = resume_blocks.load_blocks(str(DATA_DIR / "resume_blocks.yaml"))
    templates = resume_tailor.load_templates(str(DATA_DIR / "resume_templates.yaml"))
    tmpl = resume_tailor.match_template(templates, job["title"], job["jd_text"])
    sections = resume_tailor.generate_resume_sections(blocks, job, tmpl, app.state.model_router)
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
    blocks = resume_blocks.load_blocks(str(DATA_DIR / "resume_blocks.yaml"))
    templates = resume_tailor.load_templates(str(DATA_DIR / "resume_templates.yaml"))
    tmpl = resume_tailor.match_template(templates, job["title"], job["jd_text"])
    greeting = resume_tailor.generate_greeting(blocks, job, tmpl, app.state.model_router)
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
    from services import resume_blocks, resume_tailor
    plan = resume_tailor.get_plan(job_id, str(DATA_DIR / "resume_plans.yaml"))
    sections = (plan.get("resume") or {}).get("sections") or []
    if not sections:
        raise HTTPException(status_code=404, detail="该岗位还没有生成简历方案")
    blocks = resume_blocks.load_blocks(str(DATA_DIR / "resume_blocks.yaml"))
    html = resume_tailor.render_resume_html(blocks.get("basic_info") or {}, sections)
    out = DATA_DIR / "resume_pdfs" / f"{job_id}.pdf"
    resume_tailor.render_html_to_pdf(html, str(out))
    return FileResponse(str(out), media_type="application/pdf", filename=f"resume_{job_id}.pdf")


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
        "name": profile.get("name") or "",
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
        "extra_notes": profile.get("extra_notes") or "",
    })


@app.post("/api/profile")
async def save_profile(request: Request) -> JSONResponse:
    _initialize_state()
    data = await request.json()
    # Read-modify-write through the singleton. save_profile() merges into the cached
    # dict and writes, so fields managed outside the dashboard (greeting_template,
    # boss_online, ...) survive AND the cache stays in step with the file. Writing
    # inline used to leave the singleton serving a pre-edit copy.
    cm = get_config_manager(str(CONFIG_PATH), str(PROFILE_PATH))
    existing = cm.get_profile()
    updates = {
        "name": data.get("name") or existing.get("name") or "",
        "keywords": data.get("keywords") or [],
        "cities": data.get("cities") or [],
        "experience": data.get("experience") or [],
        "degree": data.get("degree") or [],
        "salary": data.get("salary") or "",
        "scale": data.get("scale") or [],
        "job_types": data.get("job_types") or [],
        "financing": data.get("financing") or [],
        "districts": data.get("districts") or [],
        "position_types": data.get("position_types") or [],
        "industries": data.get("industries") or [],
        # extra_notes (LLM scoring free-text) — preserve when not provided so a
        # save from a form that omits it does not wipe it. Single source of truth
        # for all profile.yaml fields now lives on /api/profile (Settings merge).
        "extra_notes": data.get("extra_notes", existing.get("extra_notes", "")),
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cm.save_profile(updates)
    return JSONResponse({"ok": True})


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

    available: list[str] = []
    try:
        for chain in app.state.model_router._chains.values():
            for p in chain.providers:
                if p.name not in available:
                    available.append(p.name)
    except Exception:
        pass

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


@app.get("/api/check/attachment-resume")
async def check_attachment_resume_status() -> JSONResponse:
    """Check local attachment resume file existence.
    Boss直聘 online status requires browser automation — not checked here."""
    local_exists = ATTACHMENT_RESUME_PATH.exists()
    local_size = ATTACHMENT_RESUME_PATH.stat().st_size if local_exists else 0
    return JSONResponse({
        "local_file": {
            "exists": local_exists,
            "path": str(ATTACHMENT_RESUME_PATH),
            "size_kb": round(local_size / 1024, 1) if local_exists else 0,
        },
        "boss_online": {
            "checked": False,
            "note": "需要浏览器 session 才能检测在线状态，当前未自动检测",
        },
        "boss_profile_url": "https://www.zhipin.com/web/geek/resume",
    })


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
    job_urls: dict[str, str] = {}
    for c in convs:
        if c.job_id and c.job_id not in job_urls:
            rec = tracker.get(c.job_id)
            job_urls[c.job_id] = (rec.url or "") if rec else ""
    return JSONResponse({
        "conversations": [
            _serialize_conversation(
                c, tracker.get_hr_messages(c.conv_id), job_urls.get(c.job_id or "", "")
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
                        "data": json.dumps(
                            {
                                "workflow": event.workflow,
                                "step": event.step,
                                "tool": event.tool,
                                "status": event.status,
                                "message": event.message,
                                "scope": event.scope,
                                "detail": event.detail,
                                "ts": event.ts,
                            },
                            ensure_ascii=False,
                        ),
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


def _resolved_defaults() -> dict:
    from services.settings_resolver import resolve_params
    return {
        "w1": resolve_params("w1", {}, app.state.config, DATA_DIR),
        "w2": resolve_params("w2", {}, app.state.config, DATA_DIR),
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
    if workflow not in {"w1", "w2"}:
        raise HTTPException(status_code=400, detail="workflow must be w1 or w2")
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
    wf = body.get("workflow")
    if wf not in ("w1", "w2", "w3"):
        raise HTTPException(status_code=400, detail="workflow must be w1|w2|w3")
    return _enqueue_response(wf, body.get("params") or {}, source="queue")


@app.post("/api/workflow/queue/batch")
async def add_workflow_queue_batch(body: dict | None = None) -> JSONResponse:
    """Add an ordered chain of items in one call (e.g. W1 -> W2 -> W3)."""
    _initialize_state()
    body = body or {}
    items = body.get("items") or []
    ids = []
    for it in items:
        wf = it.get("workflow")
        if wf not in ("w1", "w2", "w3"):
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
