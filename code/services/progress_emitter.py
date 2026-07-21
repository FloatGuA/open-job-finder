import queue
import threading
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProgressEvent:
    workflow: str
    step: str
    status: str
    message: str
    # tool: set on tool-level events (registry.call traces); None on step-level
    # events. scope: which loop instance this event belongs to (job_id for W1,
    # conv_id/company for W2; {} for run-level steps). Both feed the frontend
    # scope x step x tool hierarchy tree.
    tool: Optional[str] = None
    scope: Optional[dict] = field(default_factory=dict)
    detail: Optional[dict] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


class ProgressEmitter:
    """Thread-safe progress event bus."""

    def __init__(self):
        self._queues: list[queue.Queue] = []
        self._lock = threading.Lock()
        self.current_workflow: Optional[str] = None
        self.stop_requested: bool = False
        # Per-workflow replay buffers (keyed by workflow: "w1"/"w2"/"w3"). Fan-out is
        # otherwise live-only, so a page refresh (EventSource reconnects with a fresh
        # queue) used to lose the whole LIVE view. On subscribe we seed the new queue
        # with every workflow's buffer so the client rebuilds all last-run views.
        # Keyed per workflow so running W2 doesn't wipe W1's last-run view;
        # start_workflow clears only its own workflow's buffer. Full persisted
        # history still lives in the run JSONL (Logs page).
        self._buffers: dict[str, list[ProgressEvent]] = {}
        self._buffer_max: int = 200   # per workflow

    def request_stop(self) -> None:
        self.stop_requested = True
        if self.current_workflow:
            self.emit(
                ProgressEvent(
                    workflow=self.current_workflow,
                    step="stop",
                    status="stopping",
                    message="停止请求已接收，等待当前步骤完成...",
                )
            )

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=600)
        with self._lock:
            # Seed with every workflow's recent buffered events (time-ordered) so a
            # fresh / reconnected client reconstructs all last-run views, not a blank.
            seeded = sorted(
                (ev for buf in self._buffers.values() for ev in buf),
                key=lambda e: e.ts,
            )
            for ev in seeded[-400:]:
                try:
                    q.put_nowait(ev)
                except queue.Full:
                    break
            self._queues.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._queues = [x for x in self._queues if x is not q]

    def emit(self, event: ProgressEvent) -> None:
        with self._lock:
            buf = self._buffers.setdefault(event.workflow, [])
            buf.append(event)
            if len(buf) > self._buffer_max:
                del buf[: len(buf) - self._buffer_max]
            for q in self._queues:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass

    def start_workflow(self, workflow: str, meta: Optional[dict] = None) -> None:
        self.current_workflow = workflow
        with self._lock:
            self._buffers[workflow] = []   # new run → clear only THIS workflow's buffer
        self.emit(
            ProgressEvent(
                workflow=workflow,
                step="start",
                status="running",
                message=f"开始 {workflow} workflow",
                detail=meta or {},   # {trigger, params} — surfaced in the live-panel title
            )
        )

    def finish_workflow(self, workflow: str, summary: str, status: str = "done") -> None:
        self.current_workflow = None
        self.stop_requested = False
        self.emit(
            ProgressEvent(
                workflow=workflow,
                step="done",
                status=status,
                message=summary,
            )
        )
