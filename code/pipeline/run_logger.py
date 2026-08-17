"""
Pipeline-facing RunLogger adapter.

Wraps services.run_logger.RunLogger with:
- Auto-generated run_id: {pipeline}_{YYYYMMDD_HHmm}
- log(event, scope, data)       -- business events
- log_step(...)                 -- step trace
- log_tool(...)                 -- tool trace
- close(status, summary=None)   -- run_end + file close
"""
import time
from datetime import datetime, timezone
from typing import Optional

from services.run_logger import RunLogger as _RunLogger


def _make_run_id(pipeline: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    return f"{pipeline}_{stamp}"


# Domain status vocabulary (StepStatus.value) -> frontend StepStatus vocabulary.
# Applied ONLY when constructing SSE ProgressEvents; file logs keep the domain
# words (successful/failed/degraded) for analysis precision. The frontend type
# only understands pending|running|done|skipped|error|blocked, so unmapped
# domain words would silently fall through to a "pending/等待" rendering.
_UI_STATUS = {
    "successful": "done",
    "failed": "error",
    "degraded": "skipped",
}


def _ui_status(status: str) -> str:
    return _UI_STATUS.get(status, status)


def agent_event(pipeline: str, step: str, record: dict, ts: float) -> dict:
    """一条 agent 记录 → 前端 ProgressEvent 形状。

    **实时 SSE 和事后回放共用这一份**。两边各写一套的表现是"实时看着好好的、
    翻历史就少一半"，而那种不一致没有任何东西会报错。
    `services/run_log_reader.py` 也导入它（方向与 `_ui_status` 一致，反过来是循环导入）。
    """
    if record.get("kind") == "think":
        names = ", ".join(c.get("name", "") for c in (record.get("calls") or []))
        text = (record.get("text") or "")[:120]
        message = " ".join(x for x in (f"说: {text}" if text else "",
                                       f"-> {names}" if names else "") if x)
        tool = None
    else:
        message = f"{record.get('tool', '')}: {record.get('chars', 0)} 字符"
        tool = record.get("tool") or None
    return {"workflow": pipeline, "step": step, "tool": tool, "status": "info",
            "message": message, "scope": {}, "detail": record,
            "seq": record.get("seq"), "ts": ts}


class RunLogger:
    def __init__(
        self,
        pipeline: str,
        run_id: Optional[str] = None,
        emitter=None,
        debug: bool = False,
        meta: Optional[dict] = None,
    ) -> None:
        self._pipeline = pipeline
        self._emitter = emitter
        self._debug = debug
        rid = run_id or _make_run_id(pipeline)
        self._inner = _RunLogger(run_id=rid, pipeline=pipeline)
        self._inner.log_run_start(meta)

    @property
    def run_id(self) -> str:
        return self._inner._run_id

    def should_stop(self) -> bool:
        """True when the user requested a stop (中止 button → emitter.request_stop()).
        Long pipeline loops poll this between iterations to break gracefully — the
        run still runs its finalize/summary step, unlike a hard kill."""
        return bool(self._emitter is not None and getattr(self._emitter, "stop_requested", False))

    def log(self, event: str, scope: dict, data: dict, *, visible: bool = True) -> None:
        self._inner.log_business_event(event=event, scope=scope, data=data, visible=visible)
        if self._emitter is not None and visible and self._debug:
            try:
                from services.progress_emitter import ProgressEvent
                self._emitter.emit(ProgressEvent(
                    workflow=self._pipeline,
                    step=event,
                    status="info",
                    message=f"[event] {event}",
                    scope=scope or {},
                    detail={**scope, **data},
                ))  # business events carry their own status ("info"); no mapping needed
            except Exception:
                pass

    def log_step(
        self,
        step: str,
        scope: dict,
        status: str,
        duration_ms: int,
        data: Optional[dict] = None,
        error: Optional[str] = None,
        message: Optional[str] = None,
    ) -> None:
        self._inner.log_step(
            step=step,
            scope=scope,
            status=status,
            duration_ms=duration_ms,
            data=data or {},
            error=error,
        )
        if self._emitter is not None:
            try:
                from services.progress_emitter import ProgressEvent
                # `message` lets a caller surface a human-readable summary on the
                # SSE stream (the frontend LiveLog renders message, not detail);
                # the file log above is unaffected and keeps the structured data.
                self._emitter.emit(ProgressEvent(
                    workflow=self._pipeline,
                    step=step,
                    status=_ui_status(status),
                    message=message or f"Step {step}: {status}",
                    scope=scope or {},
                    detail=data or {},
                    duration_ms=duration_ms,
                ))
            except Exception:
                pass

    def emit_step_running(self, step: str, scope: dict) -> None:
        """Emit a step-entry 'running' SSE event WITHOUT writing the file log.

        Steps only call log_step() on completion (terminal status), so the
        hierarchy tree would never see an in-progress node. registry.set_context
        calls this on every step entry to surface the 'running' middle state.
        File logs stay clean (terminal steps only); this is SSE-only.
        """
        if self._emitter is None:
            return
        try:
            from services.progress_emitter import ProgressEvent
            self._emitter.emit(ProgressEvent(
                workflow=self._pipeline,
                step=step,
                status="running",
                message=f"Step {step}: running",
                scope=scope or {},
            ))
        except Exception:
            pass

    def log_tool(
        self,
        step: str,
        tool: str,
        scope: dict,
        status: str,
        duration_ms: int,
        data: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> None:
        self._inner.log_tool(
            step=step,
            tool=tool,
            scope=scope,
            status=status,
            duration_ms=duration_ms,
            data=data or {},
            error=error,
        )
        if self._emitter is not None and self._debug:
            try:
                from services.progress_emitter import ProgressEvent
                # tool name goes in its own field (not spliced into step) so the
                # frontend can place it under the right step node in the tree.
                self._emitter.emit(ProgressEvent(
                    workflow=self._pipeline,
                    step=step,
                    tool=tool,
                    status=_ui_status(status),
                    message=f"[tool] {tool}: {status}",
                    scope=scope or {},
                    detail=data or {},
                ))
            except Exception:
                pass

    def log_agent_step(self, step: str, record: dict) -> None:
        """JSONL 无条件写；SSE 只在 debug 时推（与 log_tool 一致）。"""
        self._inner.log_agent_step(step=step, record=record)
        if self._emitter is not None and self._debug:
            try:
                from services.progress_emitter import ProgressEvent
                payload = agent_event(self._pipeline, step, record, time.time())
                self._emitter.emit(ProgressEvent(**payload))
            except Exception:
                pass

    def close(self, status: str, summary: Optional[dict] = None) -> None:
        self._inner.log_run_end(status=status, summary=summary or {})
