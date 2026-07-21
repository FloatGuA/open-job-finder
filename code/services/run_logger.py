"""
Per-run structured JSONL logger.

File path: logs/runs/{run_id}.jsonl
run_id format: w1_{YYYYMMDD_HHmm} / w2_{YYYYMMDD_HHmm}
"""
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

RUNS_DIR = Path(__file__).resolve().parent.parent.parent / "logs" / "runs"

_log = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class RunLogger:
    """Per-run JSONL writer.  One instance per pipeline run."""

    def __init__(self, run_id: str, pipeline: str) -> None:
        self._run_id = run_id
        self._pipeline = pipeline
        self._f = None

        try:
            RUNS_DIR.mkdir(parents=True, exist_ok=True)
            self._f = (RUNS_DIR / f"{run_id}.jsonl").open("a", encoding="utf-8", newline="\n")
        except OSError as exc:
            _log.warning("RunLogger: cannot open log file for run %s: %s", run_id, exc)

    # ── public API ────────────────────────────────────────────────────────────

    def log_run_start(self, meta: Optional[dict] = None) -> None:
        self._write({
            "event": "run_start",
            "run_id": self._run_id,
            "pipeline": self._pipeline,
            "meta": meta or {},   # {trigger, params}: who launched this run + its knobs
            "ts": _now_iso(),
        })

    def log_run_end(self, status: str, summary: dict) -> None:
        self._write({
            "event": "run_end",
            "run_id": self._run_id,
            "status": status,
            "summary": summary,
            "ts": _now_iso(),
        })
        self._close()

    def log_step(
        self,
        step: str,
        scope: dict,
        status: str,
        duration_ms: int,
        data: dict,
        error: Optional[str] = None,
    ) -> None:
        self._write({
            "event": "step",
            "run_id": self._run_id,
            "pipeline": self._pipeline,
            "step": step,
            "scope": scope,
            "status": status,
            "duration_ms": duration_ms,
            "data": data,
            "error": error,
            "ts": _now_iso(),
        })

    def log_tool(
        self,
        step: str,
        tool: str,
        scope: dict,
        status: str,
        duration_ms: int,
        data: dict,
        error: Optional[str] = None,
    ) -> None:
        self._write({
            "event": "tool",
            "run_id": self._run_id,
            "step": step,
            "tool": tool,
            "scope": scope,
            "status": status,
            "duration_ms": duration_ms,
            "data": data,
            "error": error,
            "ts": _now_iso(),
        })

    def log_business_event(self, event: str, scope: dict, data: dict, visible: bool = True) -> None:
        # `visible` mirrors the SSE gate: file-only traces (visible=False, e.g. the
        # per-conversation filter_decision) are persisted for raw debugging but must
        # be excluded from the replayed live view so it matches what was streamed.
        self._write({
            "event": event,
            "run_id": self._run_id,
            "scope": scope,
            "data": data,
            "visible": visible,
            "ts": _now_iso(),
        })

    # ── internals ─────────────────────────────────────────────────────────────

    def _write(self, record: dict) -> None:
        if self._f is None:
            return
        try:
            self._f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._f.flush()
        except Exception as exc:
            _log.warning("RunLogger: write failed for run %s: %s", self._run_id, exc)

    def _close(self) -> None:
        if self._f is not None:
            try:
                self._f.close()
            except Exception:
                pass
            self._f = None
