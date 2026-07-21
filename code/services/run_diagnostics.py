"""Run-log diagnostics: turn a run's JSONL into a machine-checkable verdict.

Why this exists: a run log is the only artifact that survives a crash (RunLogger
flushes every line), while the in-memory smoke report is written once at the end
and is therefore missing exactly when something went wrong. A live smoke on
2026-07-21 really sent a resume to an HR, died mid-run, and left no report at all
-- the dashboard showed "never run". The log had all 585 events.

So the verdict is derived from the log, not from what the runner claims. Every
judgement here is deterministic (did run_end appear? does the applied count match
the DB delta? did the passed-in threshold show up in run_start.meta?) -- that is
code's job, not a model's. Nothing in this module calls an LLM.

Public API:
    diagnose_run(run_id)  -> dict   structured verdict
    render_report(diag)   -> str    the human/model-readable template
"""
import json
from pathlib import Path
from typing import Optional

RUNS_DIR = Path(__file__).resolve().parent.parent.parent / "logs" / "runs"

# Irreversible actions toward a real person. These are audited explicitly: if a run
# performed one and then died before persisting, that is the worst case we can hit
# (the HR got the message; our DB does not know) and it must be shouted about.
OUTBOUND_EVENTS = {
    "job_applied": "投递",
    "resume_sent": "发简历",
    "reply_sent": "发回复",
}

# Events that are themselves evidence of a failure, independent of step status.
FAILURE_EVENTS = {
    "job_apply_failed": "投递失败",
    "db_write_failed": "落库失败",
    "conv_pipeline_error": "会话流水线异常",
    "send_reply_error": "发送回复异常",
    "hr_conversation_stub_failed": "会话建行失败",
}

# Degraded-but-not-failed signals worth surfacing without failing the run.
WARNING_EVENTS = {
    "llm_degraded": "LLM 全provider降级",
    "page_drift_detected": "页面漂移",
    "run_time_budget_exceeded": "超时预算",
    "reply_locate_gave_up": "回复定位放弃",
}

# Structural records, not business events.
_STRUCTURAL = {"run_start", "run_end", "step", "tool", "filter_decision"}

# run_end statuses that mean "finished normally". NOTE two different vocabularies
# live in these logs: steps use successful/failed/degraded (StepStatus), while
# run_end uses done/failed (pipeline.close). Conflating them marks every healthy
# run as anomalous.
_OK_END_STATUSES = {"done", "successful", "completed"}


def _safe_text(value) -> str:
    """Strip lone surrogates from log-derived text.

    Scraped DOM text occasionally lands in the log with unpaired surrogates
    (\\udcXX). They parse back fine but blow up on encode, so any report built
    from them becomes unserialisable -- the diagnosis would fail on exactly the
    dirty runs it exists to examine. External data boundary: sanitise, don't
    fail fast.
    """
    if value is None:
        return ""
    return str(value).encode("utf-8", "replace").decode("utf-8", "replace")


def _sanitize(obj):
    """Recursively apply _safe_text to every string in a result structure, so the
    whole verdict is guaranteed JSON-serialisable regardless of log cleanliness."""
    if isinstance(obj, str):
        return _safe_text(obj)
    if isinstance(obj, dict):
        return {_safe_text(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _read_events(path: Path) -> list:
    events = []
    # errors="replace": a log written by a killed process can contain raw invalid
    # bytes, and refusing to read it would mean we cannot diagnose precisely the
    # runs that died badly. Undecodable bytes become U+FFFD; the surrounding
    # structure still parses.
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                # A torn last line is itself a signal (process killed mid-write);
                # keep parsing the rest rather than failing the whole diagnosis.
                continue
    return events


def diagnose_run(run_id: str, runs_dir: Optional[Path] = None) -> dict:
    """Parse one run's JSONL into a structured verdict.

    Returns a dict with ok/complete/anomalies plus the evidence behind them. A
    missing file or an unrecognised (pre-run_start) format is reported as such
    rather than silently producing an empty green report.
    """
    base = Path(runs_dir) if runs_dir else RUNS_DIR
    path = base / f"{run_id}.jsonl"
    if not path.exists():
        return {
            "run_id": run_id, "found": False, "diagnosable": False, "ok": False,
            "complete": False,
            "status": "missing", "anomalies": [f"run 日志不存在: {path.name}"],
            "events_total": 0, "steps": {}, "outbound": {}, "failures": {},
            "warnings": {}, "errors": [], "trigger": None, "params": {}, "summary": {},
        }

    events = _read_events(path)
    start = next((e for e in events if e.get("event") == "run_start"), None)
    end = next((e for e in events if e.get("event") == "run_end"), None)

    if start is None:
        # Legacy format (pre-run_start) -- say so instead of inventing a verdict.
        # diagnosable=False keeps these out of the failure bucket: "we cannot judge
        # this run" is a different statement from "this run went wrong".
        return {
            "run_id": run_id, "found": True, "diagnosable": False, "ok": False,
            "complete": False, "status": "unrecognised",
            "anomalies": ["无 run_start：日志为旧格式或已损坏，无法诊断"],
            "events_total": len(events), "steps": {}, "outbound": {}, "failures": {},
            "warnings": {}, "errors": [], "trigger": None, "params": {}, "summary": {},
        }

    meta = start.get("meta") or {}
    pipeline = start.get("pipeline") or run_id.split("_")[0]

    # -- step outcomes, grouped by step name -----------------------------------
    steps: dict = {}
    errors: list = []
    for e in events:
        if e.get("event") != "step":
            continue
        name = e.get("step") or "?"
        bucket = steps.setdefault(name, {})
        status = e.get("status") or "?"
        bucket[status] = bucket.get(status, 0) + 1
        if status == "failed":
            errors.append({
                "step": _safe_text(name),
                "scope": e.get("scope") or {},
                "error": _safe_text(e.get("error"))[:200],
            })

    # -- business events --------------------------------------------------------
    outbound: dict = {}
    failures: dict = {}
    warnings: dict = {}
    for e in events:
        name = e.get("event")
        if not name or name in _STRUCTURAL:
            continue
        if name in OUTBOUND_EVENTS:
            outbound[name] = outbound.get(name, 0) + 1
        elif name in FAILURE_EVENTS:
            failures[name] = failures.get(name, 0) + 1
        elif name in WARNING_EVENTS:
            warnings[name] = warnings.get(name, 0) + 1

    complete = end is not None
    end_status = (end or {}).get("status")
    outbound_total = sum(outbound.values())

    # -- deterministic anomaly rules -------------------------------------------
    anomalies: list = []
    if not complete:
        anomalies.append("无 run_end：进程中断或崩溃，本次运行未收尾")
        if outbound_total:
            # The dangerous case: real messages went out, persistence unknown.
            acts = "、".join(f"{OUTBOUND_EVENTS[k]}{v}" for k, v in outbound.items())
            anomalies.append(f"中断前已发生真实外发（{acts}）——对方已收到，落库状态未知")
    elif end_status and end_status not in _OK_END_STATUSES:
        anomalies.append(f"run_end 状态为 {end_status}")

    for k, v in failures.items():
        anomalies.append(f"{FAILURE_EVENTS[k]} × {v}")
    if errors:
        anomalies.append(f"step 失败 × {len(errors)}")

    status = "interrupted" if not complete else (end_status or "unknown")
    return _sanitize({
        "run_id": run_id,
        "found": True,
        "diagnosable": True,
        "pipeline": pipeline,
        "trigger": meta.get("trigger"),
        "params": meta.get("params") or {},
        "started_at": start.get("ts"),
        "ended_at": (end or {}).get("ts"),
        "status": status,
        "complete": complete,
        # ok = nothing structurally wrong. Coverage ("did it actually do anything")
        # is a separate axis, decided by the caller against what it expected.
        "ok": complete and not anomalies,
        "events_total": len(events),
        "steps": steps,
        "outbound": outbound,
        "outbound_total": outbound_total,
        "failures": failures,
        "warnings": warnings,
        "errors": errors[:10],
        "summary": (end or {}).get("summary") or {},
        "anomalies": anomalies,
    })


def find_runs(pipeline: Optional[str] = None, trigger: Optional[str] = None,
              since_epoch: Optional[float] = None, limit: int = 20,
              runs_dir: Optional[Path] = None) -> list:
    """List run_ids newest-first, optionally filtered by pipeline / trigger / mtime.

    trigger filtering needs run_start, so legacy logs are skipped when it is set.
    since_epoch uses file mtime, which is what lets a caller say "the runs MY smoke
    just produced" without threading run_ids back through the runners.
    """
    base = Path(runs_dir) if runs_dir else RUNS_DIR
    if not base.exists():
        return []
    files = []
    for p in base.glob("*.jsonl"):
        if pipeline and not p.name.startswith(f"{pipeline}_"):
            continue
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        if since_epoch is not None and mtime < since_epoch:
            continue
        files.append((mtime, p))
    files.sort(reverse=True)

    out = []
    for _, p in files:
        run_id = p.stem
        if trigger is not None:
            diag = diagnose_run(run_id, runs_dir=base)
            if diag.get("trigger") != trigger:
                continue
        out.append(run_id)
        if len(out) >= limit:
            break
    return out


def check_params_applied(diag: dict, expected: dict) -> list:
    """Compare the params we asked for against what run_start actually recorded.

    Catches the silent class of bug where a knob is accepted by the endpoint but
    never reaches the runner (the smoke passing score_threshold that nothing
    forwards). Returns a list of {name, expected, actual, ok}.
    """
    actual = diag.get("params") or {}
    rows = []
    for key, want in expected.items():
        if want is None:
            continue
        got = actual.get(key)
        rows.append({
            "name": key,
            "expected": want,
            "actual": got,
            "ok": got == want,
        })
    return rows


def _fmt_steps(steps: dict) -> list:
    lines = []
    for name, outcomes in steps.items():
        parts = []
        for status in ("successful", "skipped", "degraded", "failed"):
            if outcomes.get(status):
                mark = {"successful": "✓", "skipped": "skip",
                        "degraded": "degr", "failed": "✗"}[status]
                parts.append(f"{outcomes[status]}{mark}")
        lines.append(f"    {name:16s} {' '.join(parts)}")
    return lines


def render_report(diag: dict, param_checks: Optional[list] = None) -> str:
    """Render the verdict as the fixed-format text template (see
    docs/run-log-guide.md for how to read it)."""
    L = []
    verdict = "PASS" if diag.get("ok") else "FAIL"
    L.append(f"=== RUN 诊断 · {diag.get('run_id')} ===")
    head = f"结论: {verdict}"
    if diag.get("anomalies"):
        head += f" — {diag['anomalies'][0]}"
    L.append(head)

    if not diag.get("found") or diag.get("status") in ("missing", "unrecognised"):
        for a in diag.get("anomalies", []):
            L.append(f"  ! {a}")
        return "\n".join(L)

    L.append("")
    L.append("[完整性]")
    L.append(f"  run_start ✓   run_end {'✓' if diag['complete'] else '✗'}"
             f"   状态={diag.get('status')}")
    L.append(f"  事件 {diag['events_total']}   trigger={diag.get('trigger')}"
             f"   {diag.get('started_at')} → {diag.get('ended_at') or '(无)'}")

    if param_checks:
        L.append("")
        L.append("[参数生效核对]   传入 → log 回显")
        for r in param_checks:
            L.append(f"  {r['name']:22s} {r['expected']} → {r['actual']}"
                     f" {'✓' if r['ok'] else '✗ 未生效'}")

    if diag.get("steps"):
        L.append("")
        L.append("[Step 统计]")
        L.extend(_fmt_steps(diag["steps"]))

    L.append("")
    L.append("[外发动作 · 真实副作用]")
    if diag.get("outbound"):
        for k, v in diag["outbound"].items():
            L.append(f"  {OUTBOUND_EVENTS[k]} {v}")
    else:
        L.append("  （无外发）")

    if diag.get("summary"):
        L.append("")
        L.append("[run_end summary]")
        L.append(f"  {json.dumps(diag['summary'], ensure_ascii=False)[:300]}")

    if diag.get("warnings"):
        L.append("")
        L.append("[告警]")
        for k, v in diag["warnings"].items():
            L.append(f"  ~ {WARNING_EVENTS[k]} × {v}")

    if diag.get("anomalies"):
        L.append("")
        L.append("[异常]")
        for a in diag["anomalies"]:
            L.append(f"  ! {a}")
    for e in diag.get("errors", [])[:5]:
        L.append(f"    - {e['step']}: {e['error'][:110]}")

    return "\n".join(L)
