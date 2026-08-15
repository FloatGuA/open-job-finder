"""In-memory FIFO workflow queue with a single sequential worker.

Replaces the old "one workflow at a time, reject/skip if busy" model: every
workflow start (manual trigger, scheduled job, explicit queue add, a composed
W1->W2->W3 chain) goes through `enqueue`; a single daemon worker pops items
FIFO and runs them one after another. This serialises the single Boss browser
without dropping runs on the floor.

Decoupled from the dashboard: the caller injects `runner(item)` (executes ONE
item synchronously, blocking until the workflow finishes) and `is_busy()`
(True when some non-queue path — interactive browse / onboarding — currently
owns the browser, so the worker defers). The queue itself holds no FastAPI,
browser, or DB knowledge, which keeps it unit-testable with a fake runner.
"""
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# w1/w2/w3 = Boss 直聘那条线（投递 / 检查回应 / 发送回复）。
# m1/m2 = 多站点 Layer 1（选岗 / 填表），见 docs/multi-site-expansion-design.md。
#
# **加新 workflow 必须同时改三处**，漏一处就是静默失败：
#   1. 这里（不加的话 enqueue 直接拒绝，报错还算明显）
#   2. workflow_orchestration.run_item 的 log_wf 映射（**在 try 外面，跑完了才
#      炸在写日志上**——活干完了、结果丢了，最难查的那种）
#   3. run_item 的分派 if/elif
_BOSS_WORKFLOWS = ("w1", "w2", "w3")
_MULTISITE_WORKFLOWS = ("m1", "m2")
VALID_WORKFLOWS = _BOSS_WORKFLOWS + _MULTISITE_WORKFLOWS


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class QueueItem:
    id: str
    workflow: str                 # w1 | w2 | w3 | m1 | m2
    params: dict = field(default_factory=dict)
    source: str = "manual"        # manual | queue | scheduled | selfcheck
    enqueued_at: str = field(default_factory=_now)
    status: str = "pending"       # pending | running | done | error
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None


class WorkflowQueue:
    def __init__(self, runner: Callable[[QueueItem], None], is_busy: Optional[Callable[[], bool]] = None):
        self._runner = runner
        self._is_busy = is_busy or (lambda: False)
        self._cv = threading.Condition(threading.Lock())
        self._pending: list[QueueItem] = []
        self._current: Optional[QueueItem] = None
        self._recent: list[QueueItem] = []   # most-recent-first, capped
        self._recent_max = 20
        self._stop = False
        self._paused = False
        self._worker = threading.Thread(target=self._loop, name="wf-queue-worker", daemon=True)
        self._worker.start()

    # -- producer side -------------------------------------------------------

    def enqueue(self, workflow: str, params: Optional[dict] = None,
                source: str = "manual", coalesce: bool = False) -> QueueItem:
        """Append an item and wake the worker. Returns the item (or, when
        coalesce=True and a pending item with the same workflow+source already
        waits, that existing item — used by the scheduler to avoid pile-up)."""
        if workflow not in VALID_WORKFLOWS:
            raise ValueError(f"unknown workflow {workflow!r}")
        with self._cv:
            if coalesce:
                for it in self._pending:
                    if it.workflow == workflow and it.source == source:
                        return it
            item = QueueItem(id=uuid.uuid4().hex[:8], workflow=workflow,
                             params=dict(params or {}), source=source)
            self._pending.append(item)
            self._cv.notify()
            return item

    # -- queue management ----------------------------------------------------

    def remove(self, item_id: str) -> bool:
        with self._cv:
            before = len(self._pending)
            self._pending = [i for i in self._pending if i.id != item_id]
            return len(self._pending) < before

    def clear(self) -> int:
        with self._cv:
            n = len(self._pending)
            self._pending = []
            return n

    def move(self, item_id: str, direction: int) -> bool:
        """Reorder a pending item: direction -1 = earlier, +1 = later."""
        step = -1 if direction < 0 else 1
        with self._cv:
            idx = next((k for k, i in enumerate(self._pending) if i.id == item_id), None)
            if idx is None:
                return False
            j = idx + step
            if j < 0 or j >= len(self._pending):
                return False
            self._pending[idx], self._pending[j] = self._pending[j], self._pending[idx]
            return True

    def reorder(self, ordered_ids: list) -> bool:
        """Reorder pending to match the given id order (drag-and-drop). Ids not
        listed keep their relative order at the end; unknown ids are ignored."""
        with self._cv:
            by_id = {i.id: i for i in self._pending}
            new = [by_id[i] for i in ordered_ids if i in by_id]
            seen = {i.id for i in new}
            new.extend(i for i in self._pending if i.id not in seen)
            self._pending = new
            return True

    def pause(self) -> None:
        """Stop starting NEW items; a currently-running item is unaffected."""
        with self._cv:
            self._paused = True

    def resume(self) -> None:
        with self._cv:
            self._paused = False
            self._cv.notify()

    def snapshot(self) -> dict:
        with self._cv:
            return {
                "current": asdict(self._current) if self._current else None,
                "pending": [asdict(i) for i in self._pending],
                "recent": [asdict(i) for i in self._recent],
                "paused": self._paused,
            }

    # -- lifecycle -----------------------------------------------------------

    def stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()

    def _loop(self) -> None:
        while True:
            with self._cv:
                # Wait until there is work, the queue isn't paused, and no
                # non-queue browser op is running.
                while not self._stop and (not self._pending or self._is_busy() or self._paused):
                    self._cv.wait(timeout=1.0)
                if self._stop:
                    return
                item = self._pending.pop(0)
                item.status = "running"
                item.started_at = _now()
                self._current = item

            # Run OUTSIDE the lock — this blocks until the workflow finishes.
            try:
                self._runner(item)
                item.status = "done"
            except Exception as exc:  # noqa: BLE001 — worker must survive any item failure
                item.status = "error"
                item.error = str(exc)
                logger.exception("queue item %s (%s) failed", item.id, item.workflow)
            finally:
                item.finished_at = _now()
                with self._cv:
                    self._current = None
                    self._recent.insert(0, item)
                    del self._recent[self._recent_max:]
