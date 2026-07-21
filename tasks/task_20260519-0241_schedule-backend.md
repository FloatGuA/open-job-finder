# Task: Schedule Backend — APScheduler + API + Log

## 目标

在 `dashboard/server.py` 中嵌入 APScheduler BackgroundScheduler，实现 W1（apply）和 W2（check）的定时/间隔自动触发，配置持久化到 `data/schedule.yaml`，运行记录写入 `data/schedule_log.jsonl`，暴露 `GET/PUT /api/schedule` 和 `GET /api/schedule/log` 两个 API 端点。

## 背景

- Dashboard 已有手动触发：`POST /api/workflow/apply` 和 `POST /api/workflow/check`，内部调用 `_build_orchestrator()` + `orch.run_once()` / `orch.check_responses()`
- 并发保护已有：`emitter.current_workflow` 非空时抛 409
- SSE 流已常驻：前端 `useWorkflowStream` 始终监听，只要后端 emit 事件前端就会更新
- 目标：让调度器复用同一套 `_run()` 逻辑，冲突时静默跳过并记录日志

## 实现要求

### 1. `code/requirements.txt`

新增依赖行（如果不存在）：
```
apscheduler>=3.10.0
```

### 2. `code/dashboard/server.py`

#### 2a. 导入

在现有 import 区块末尾添加（不拆现有 import 块）：
```python
import json as _json
import threading
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
```

#### 2b. 常量

在现有 `DATA_DIR` / `CONTROL_PATH` 等常量区块中添加：
```python
SCHEDULE_CONFIG_PATH = DATA_DIR / "schedule.yaml"
SCHEDULE_LOG_PATH    = DATA_DIR / "schedule_log.jsonl"
```

#### 2c. schedule_log 写入函数

```python
def _write_schedule_log(entry: dict) -> None:
    """Append one JSON line to schedule_log.jsonl. Thread-safe via GIL + append mode."""
    SCHEDULE_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SCHEDULE_LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(_json.dumps(entry, ensure_ascii=False) + "\n")
```

#### 2d. schedule 配置读写函数

```python
_SCHEDULE_DEFAULTS = {
    "apply": {
        "enabled": False,
        "times": [],           # list of "HH:MM" strings
        "interval_hours": 0,   # 0 = disabled
        "params": {
            "limit": 30,
            "score_threshold": 60,
            "apply_limit": 0,  # 0 = no limit
            "dry_run": False,
            "headless": True,
            "generate_resume": False,
        },
    },
    "check": {
        "enabled": False,
        "times": [],
        "interval_hours": 0,
        "params": {
            "max_conversations": 200,
            "days": 7,
            "headless": True,
        },
    },
}

def _load_schedule_config() -> dict:
    import copy, yaml as _yaml
    defaults = copy.deepcopy(_SCHEDULE_DEFAULTS)
    if not SCHEDULE_CONFIG_PATH.exists():
        return defaults
    try:
        with SCHEDULE_CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = _yaml.safe_load(f) or {}
        for wf in ("apply", "check"):
            if wf in data:
                wf_data = data[wf]
                defaults[wf]["enabled"] = bool(wf_data.get("enabled", False))
                defaults[wf]["times"]   = list(wf_data.get("times", []))
                defaults[wf]["interval_hours"] = int(wf_data.get("interval_hours", 0))
                if "params" in wf_data:
                    defaults[wf]["params"].update(wf_data["params"])
        return defaults
    except Exception:
        return defaults

def _save_schedule_config(cfg: dict) -> None:
    import yaml as _yaml
    SCHEDULE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with SCHEDULE_CONFIG_PATH.open("w", encoding="utf-8") as f:
        _yaml.safe_dump(cfg, f, allow_unicode=True)
```

#### 2e. scheduler job 函数（核心逻辑）

```python
def _scheduled_run(workflow: str) -> None:
    """
    Called by APScheduler in a background thread.
    workflow: "apply" | "check"
    """
    import time as _time
    from datetime import datetime, timezone

    triggered_at = datetime.now(timezone.utc).isoformat()
    emitter: ProgressEmitter = getattr(app.state, "emitter", None)

    # Conflict check
    if emitter and emitter.current_workflow:
        log_entry = {
            "workflow": workflow,
            "trigger_type": "scheduler",
            "triggered_at": triggered_at,
            "result": "skipped",
            "skipped_reason": f"{emitter.current_workflow} 正在运行",
            "summary": None,
            "duration_seconds": 0,
        }
        _write_schedule_log(log_entry)
        logger.info("Scheduled %s skipped: %s is running", workflow, emitter.current_workflow)
        return

    cfg = _load_schedule_config()
    params = cfg.get(workflow, {}).get("params", {})
    start_time = _time.monotonic()

    try:
        if workflow == "apply":
            headless = bool(params.get("headless", True))
            orch = _build_orchestrator(headless=headless)
            apply_limit_raw = params.get("apply_limit", 0)
            apply_limit = int(apply_limit_raw) if apply_limit_raw and int(apply_limit_raw) > 0 else None
            orch.run_once(
                dry_run=bool(params.get("dry_run", False)),
                limit=int(params.get("limit", 30)),
                score_threshold=int(params.get("score_threshold", 60)),
                generate_resume=params.get("generate_resume", None),
                apply_limit=apply_limit,
            )
            summary = "apply 工作流完成"
        else:
            headless = bool(params.get("headless", True))
            orch = _build_orchestrator(headless=headless)
            orch.check_responses(
                max_conversations=int(params.get("max_conversations", 200)),
                days=int(params.get("days", 7)),
            )
            summary = "check 工作流完成"

        duration = round(_time.monotonic() - start_time)
        _write_schedule_log({
            "workflow": workflow,
            "trigger_type": "scheduler",
            "triggered_at": triggered_at,
            "result": "success",
            "skipped_reason": None,
            "summary": summary,
            "duration_seconds": duration,
        })
    except Exception as exc:
        duration = round(_time.monotonic() - start_time)
        logger.exception("Scheduled %s failed: %s", workflow, exc)
        _write_schedule_log({
            "workflow": workflow,
            "trigger_type": "scheduler",
            "triggered_at": triggered_at,
            "result": "error",
            "skipped_reason": None,
            "summary": str(exc),
            "duration_seconds": duration,
        })
```

#### 2f. scheduler 构建函数

```python
_scheduler: BackgroundScheduler | None = None
_scheduler_lock = threading.Lock()

def _build_scheduler(cfg: dict) -> BackgroundScheduler:
    """Build a fresh BackgroundScheduler from config. Caller must start() it."""
    import pytz
    tz = pytz.timezone("Asia/Shanghai")
    sched = BackgroundScheduler(timezone=tz)

    for workflow in ("apply", "check"):
        wf_cfg = cfg.get(workflow, {})
        if not wf_cfg.get("enabled", False):
            continue

        # Time-based triggers
        for time_str in wf_cfg.get("times", []):
            try:
                hour, minute = map(int, time_str.split(":"))
                sched.add_job(
                    _scheduled_run,
                    CronTrigger(hour=hour, minute=minute, timezone=tz),
                    args=[workflow],
                    id=f"{workflow}_cron_{time_str.replace(':', '')}",
                    replace_existing=True,
                )
            except (ValueError, TypeError):
                logger.warning("Invalid schedule time %r for %s", time_str, workflow)

        # Interval trigger
        interval_h = int(wf_cfg.get("interval_hours", 0))
        if interval_h > 0:
            sched.add_job(
                _scheduled_run,
                IntervalTrigger(hours=interval_h, timezone=tz),
                args=[workflow],
                id=f"{workflow}_interval",
                replace_existing=True,
            )

    return sched


def _rebuild_scheduler(cfg: dict) -> None:
    """Stop existing scheduler (if any), build and start a new one."""
    global _scheduler
    with _scheduler_lock:
        if _scheduler is not None and _scheduler.running:
            _scheduler.shutdown(wait=False)
        _scheduler = _build_scheduler(cfg)
        _scheduler.start()
        logger.info("Scheduler started with %d jobs", len(_scheduler.get_jobs()))
```

#### 2g. startup / shutdown 更新

修改现有 `startup()` 和 `shutdown()` 事件处理器，在初始化之后启动调度器、关闭时停止：

```python
@app.on_event("startup")
async def startup() -> None:
    _initialize_state()
    app.state.emitter = getattr(app.state, "emitter", None) or ProgressEmitter()
    # Start scheduler
    cfg = _load_schedule_config()
    _rebuild_scheduler(cfg)


@app.on_event("shutdown")
async def shutdown() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    tracker = getattr(app.state, "tracker", None)
    if tracker is not None:
        tracker.close()
```

#### 2h. API 端点

在现有 `/api/workflow/stop` 附近（workflow 端点区域）新增：

```python
@app.get("/api/schedule")
async def get_schedule() -> JSONResponse:
    cfg = _load_schedule_config()
    # Enrich with next_run_times from scheduler
    next_runs: dict[str, str | None] = {}
    with _scheduler_lock:
        sched = _scheduler
    if sched and sched.running:
        for job in sched.get_jobs():
            # job.id format: "apply_cron_0900" / "apply_interval" / "check_cron_0800" / "check_interval"
            wf = job.id.split("_")[0]
            nrt = job.next_run_time
            nrt_str = nrt.isoformat() if nrt else None
            # Keep earliest next run per workflow
            existing = next_runs.get(wf)
            if nrt_str and (existing is None or nrt_str < existing):
                next_runs[wf] = nrt_str
    cfg["_next_runs"] = next_runs
    cfg["_scheduler_running"] = bool(sched and sched.running)
    return JSONResponse(cfg)


@app.put("/api/schedule")
async def update_schedule(body: dict) -> JSONResponse:
    # Validate and sanitize
    cfg = _load_schedule_config()
    for wf in ("apply", "check"):
        if wf not in body:
            continue
        wf_body = body[wf]
        if "enabled" in wf_body:
            cfg[wf]["enabled"] = bool(wf_body["enabled"])
        if "times" in wf_body:
            cfg[wf]["times"] = [str(t) for t in wf_body["times"] if isinstance(t, str)]
        if "interval_hours" in wf_body:
            cfg[wf]["interval_hours"] = max(0, int(wf_body["interval_hours"]))
        if "params" in wf_body:
            cfg[wf]["params"].update(wf_body["params"])
    _save_schedule_config(cfg)
    _rebuild_scheduler(cfg)
    return JSONResponse({"ok": True, "config": cfg})


@app.get("/api/schedule/log")
async def get_schedule_log(limit: int = 50) -> JSONResponse:
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
```

### 3. Unicode 注意事项

所有写入 `.py` 文件的中文字符串（logger 消息除外）必须用 `\uXXXX` 转义，因为 Windows GBK 工具链可能损坏中文源码。已在上方代码示例中对中文字符串使用了 `\uXXXX`（如 `"正在运行"`）。

## 验收标准

- [ ] `GET /api/schedule` 返回 `apply` 和 `check` 两个 workflow 的配置结构，包含 `_next_runs` 字段
- [ ] `PUT /api/schedule` 可以更新配置（enabled/times/interval_hours/params），持久化到 `data/schedule.yaml`，并立即重建 scheduler
- [ ] `GET /api/schedule/log` 返回 `data/schedule_log.jsonl` 中的记录（倒序，最新在前）
- [ ] `PUT /api/schedule` 中将 apply 的 enabled 设为 true + times=["09:00"] 后，scheduler 中存在 `apply_cron_0900` job
- [ ] 当 emitter.current_workflow 非空时，`_scheduled_run` 写入 result="skipped" 的日志并返回，不运行 workflow
- [ ] server.py 启动时（startup 事件）自动加载 schedule.yaml 并启动 scheduler
- [ ] server.py 关闭时（shutdown 事件）调用 scheduler.shutdown(wait=False)
- [ ] apscheduler>=3.10.0 已写入 requirements.txt
