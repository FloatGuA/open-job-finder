"""Read-only parsing of run JSONL logs for the dashboard, extracted from server.py.

These are the shapes the Logs page consumes: a list summary, a grouped
step/tool/business-event detail, and a flattened ProgressEvent[] replay. All pure
file reads with no app.state -- so they take runs_dir as an argument rather than a
module global, and are unit-testable without a server.

Sibling to run_diagnostics.py, which also reads run JSONL but for a different
purpose (a deterministic health verdict, not display shapes); the two are kept
separate on purpose.

HTTP-facing validation (pipeline whitelist -> 400) stays in server.py -- that is a
request concern, not a reading concern.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pipeline.run_logger import _ui_status, agent_event


def iter_run_files(runs_dir: Path, pipeline: str | None = None) -> list[Path]:
    if not runs_dir.exists():
        return []
    pattern = f"{pipeline}_*.jsonl" if pipeline else "*.jsonl"
    return list(runs_dir.glob(pattern))


def summarize_run_file(path: Path) -> dict[str, Any] | None:
    """One-line summary for the run list, or None if the file is empty / not a run
    (no run_start). A run with no run_end is reported as still 'running'."""
    lines: list[str] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                lines.append(line)
    if not lines:
        return None
    first = json.loads(lines[0])
    last = json.loads(lines[-1])
    if first.get("event") != "run_start":
        return None
    ended = last.get("event") == "run_end"
    return {
        "run_id": first.get("run_id", path.stem),
        "pipeline": first.get("pipeline", ""),
        "filename": path.name,
        "started_at": first.get("ts"),
        "status": last.get("status") if ended else "running",
        "duration_ms": last.get("duration_ms") if ended else None,
        "summary": last.get("summary") if ended else None,
    }


def find_run_file(runs_dir: Path, run_id: str) -> Path | None:
    """Locate a run's JSONL by matching the run_start event's run_id field."""
    for path in iter_run_files(runs_dir):
        try:
            with path.open("r", encoding="utf-8") as file:
                first_line = file.readline().strip()
            if not first_line:
                continue
            if json.loads(first_line).get("run_id") == run_id:
                return path
        except (OSError, json.JSONDecodeError):
            continue
    return None


def parse_run_detail(path: Path) -> dict[str, Any]:
    """Group a run's events into steps (each with its tools) + business_events, the
    shape the Logs detail/Flow tabs render."""
    lines: list[str] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                lines.append(line)
    if not lines:
        return {}

    first = json.loads(lines[0])
    last = json.loads(lines[-1])
    ended = last.get("event") == "run_end"

    step_events: list[dict[str, Any]] = []
    tool_events: list[dict[str, Any]] = []
    business_events: list[dict[str, Any]] = []
    for raw_line in lines:
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        event = entry.get("event", "")
        if event in ("run_start", "run_end"):
            continue
        if event == "step":
            step_events.append(entry)
        elif event == "tool":
            tool_events.append(entry)
        else:
            business_events.append(entry)

    step_events.sort(key=lambda e: e.get("ts", ""))
    tool_events.sort(key=lambda e: e.get("ts", ""))
    business_events.sort(key=lambda e: e.get("ts", ""))

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

    # Attach each tool to the most recent step whose ts <= the tool's ts.
    for te in tool_events:
        tool_ts = te.get("ts", "")
        best_idx = -1
        for idx, step in enumerate(steps):
            if step["ts"] <= tool_ts:
                best_idx = idx
        target_idx = best_idx if best_idx >= 0 else (len(steps) - 1 if steps else -1)
        if target_idx >= 0:
            steps[target_idx]["tools"].append({
                "tool": te.get("tool", ""),
                "scope": te.get("scope") or {},
                "status": te.get("status", ""),
                "duration_ms": te.get("duration_ms"),
                "data": te.get("data") or {},
                "error": te.get("error"),
                "ts": te.get("ts", ""),
            })

    be_list = [
        {
            "event": be.get("event", ""),
            "scope": be.get("scope") or {},
            "data": be.get("data") or {},
            "ts": be.get("ts", ""),
        }
        for be in business_events
    ]

    return {
        "run_id": first.get("run_id", path.stem),
        "pipeline": first.get("pipeline", ""),
        "status": last.get("status") if ended else "running",
        "started_at": first.get("ts"),
        "duration_ms": last.get("duration_ms") if ended else None,
        "summary": last.get("summary") if ended else None,
        "steps": steps,
        "business_events": be_list,
    }


def iso_to_epoch(ts: str) -> float:
    if not ts:
        return 0.0
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def parse_run_events(path: Path) -> list[dict[str, Any]]:
    """Flatten a run JSONL into frontend ProgressEvent[] (the live-stream shape), so
    a finished run can be replayed into WorkflowTrack via the same buildTree the SSE
    stream feeds. The in-memory SSE buffer is capped (200, shared) and lost on
    restart, so it cannot show a *complete* past run -- the JSONL can.

    Domain status -> UI status (single source: _ui_status); ISO ts -> epoch seconds;
    workflow taken once from run_start; message synthesized to match the SSE path."""
    lines = [ln.strip() for ln in path.open("r", encoding="utf-8") if ln.strip()]
    if not lines:
        return []
    first = json.loads(lines[0])
    pipeline = first.get("pipeline", "") or path.stem.split("_")[0]

    out: list[dict[str, Any]] = []

    def emit(**fields: Any) -> None:
        # seq / duration_ms 只在部分分支上有值；这里给统一默认，免得每加一个分支
        # 就要记得补一次（补五处等于给将来第六个分支留同样的坑）。
        out.append({"seq": None, "duration_ms": None, **fields})

    for raw in lines:
        try:
            e = json.loads(raw)
        except json.JSONDecodeError:
            continue
        event = e.get("event", "")
        scope = e.get("scope") or {}
        data = e.get("data") or {}
        status = e.get("status", "")
        ts = iso_to_epoch(e.get("ts", ""))
        if event == "run_start":
            emit(workflow=pipeline, step="start", tool=None, status="running",
                 message=f"开始 {pipeline} workflow", scope={},
                 detail=e.get("meta") or {}, ts=ts)
        elif event == "run_end":
            emit(workflow=pipeline, step="done", tool=None, status=_ui_status(status),
                 message=str(e.get("summary") or {}), scope={}, detail=e.get("summary") or {}, ts=ts,
                 duration_ms=e.get("duration_ms"))
        elif event == "step":
            step = e.get("step", "")
            emit(workflow=pipeline, step=step, tool=None, status=_ui_status(status),
                 message=f"Step {step}: {status}", scope=scope, detail=data, ts=ts,
                 duration_ms=e.get("duration_ms"))
        elif event == "tool":
            tool = e.get("tool", "")
            emit(workflow=pipeline, step=e.get("step", ""), tool=tool, status=_ui_status(status),
                 message=f"[tool] {tool}: {status}", scope=scope, detail=data, ts=ts,
                 duration_ms=e.get("duration_ms"))
        elif event == "agent_step":
            # agent 内层循环。格式化跟实时 SSE 共用 agent_event()——两边各写一套的
            # 表现是"实时看着好好的、翻历史就少一半"，而那不会报错。agent_event() 自带
            # seq，经 emit() 时会覆盖 "seq": None 的默认值。
            emit(**agent_event(pipeline, e.get("step", ""), e.get("record") or {}, ts))
        else:
            # business event. Skip file-only per-conversation traces the live SSE never
            # showed (visible=False), so replay mirrors the live view. Older logs
            # predate `visible`, so also skip the known file-only event by name.
            if e.get("visible") is False or event == "filter_decision":
                continue
            # job_scored / job_skipped / intent_analyzed / ...: no status in file; SSE
            # emits these as "info"; detail carries the human-readable payload.
            emit(workflow=pipeline, step=event, tool=None, status="info",
                 message=f"[event] {event}", scope=scope, detail={**scope, **data}, ts=ts)
    out.sort(key=lambda x: x["ts"])
    return out
