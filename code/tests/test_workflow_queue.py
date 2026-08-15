"""Unit tests for services.workflow_queue.WorkflowQueue (in-memory FIFO + worker)."""
import threading
import time

import pytest

from services.workflow_queue import WorkflowQueue


class Gate:
    """Fake runner: records start/finish order, can block on a gate and fail on
    selected workflows — lets tests hold items in the pending list deterministically."""

    def __init__(self):
        self.ev = threading.Event()
        self.ev.set()
        self.started: list[str] = []
        self.ran: list[str] = []
        self.fail: set[str] = set()
        self._lock = threading.Lock()

    def __call__(self, item):
        with self._lock:
            self.started.append(item.workflow)
        if not self.ev.wait(timeout=5):
            raise TimeoutError("gate never opened")
        if item.workflow in self.fail:
            raise RuntimeError(f"boom-{item.workflow}")
        with self._lock:
            self.ran.append(item.workflow)


def _wait(cond, timeout=5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


def _drain(q, timeout=5.0):
    ok = _wait(lambda: q.snapshot()["current"] is None and not q.snapshot()["pending"], timeout)
    assert ok, f"queue did not drain: {q.snapshot()}"


def test_fifo_order():
    g = Gate()
    q = WorkflowQueue(runner=g)
    try:
        for w in ("w1", "w2", "w3"):
            q.enqueue(w)
        _drain(q)
        assert g.ran == ["w1", "w2", "w3"]
    finally:
        q.stop()


def test_enqueue_invalid_workflow():
    q = WorkflowQueue(runner=lambda i: None)
    try:
        with pytest.raises(ValueError):
            q.enqueue("w9")
    finally:
        q.stop()


def test_enqueue_returns_pending_item():
    g = Gate()
    g.ev.clear()  # block so it stays observable
    q = WorkflowQueue(runner=g)
    try:
        it = q.enqueue("w2", params={"max_conversations": 10}, source="queue")
        assert it.workflow == "w2"
        assert it.source == "queue"
        assert it.params == {"max_conversations": 10}
        assert it.status in ("pending", "running")
        g.ev.set()
        _drain(q)
    finally:
        q.stop()


def test_remove_move_clear():
    g = Gate()
    g.ev.clear()  # block the worker on the first (blocker) item
    q = WorkflowQueue(runner=g)
    try:
        q.enqueue("w1")  # blocker: starts and hangs on the gate
        assert _wait(lambda: q.snapshot()["current"] is not None)
        a = q.enqueue("w2")
        c = q.enqueue("w3")
        d = q.enqueue("w1")
        assert [i["id"] for i in q.snapshot()["pending"]] == [a.id, c.id, d.id]

        assert q.move(c.id, -1)
        assert [i["id"] for i in q.snapshot()["pending"]] == [c.id, a.id, d.id]
        assert not q.move(c.id, -1)  # already first
        assert q.move(c.id, 1)
        assert [i["id"] for i in q.snapshot()["pending"]] == [a.id, c.id, d.id]

        assert q.remove(a.id)
        assert not q.remove("nope")
        assert [i["id"] for i in q.snapshot()["pending"]] == [c.id, d.id]

        assert q.clear() == 2
        assert q.snapshot()["pending"] == []

        g.ev.set()
        _drain(q)
        assert g.ran == ["w1"]  # only the blocker ran; the rest were removed/cleared
    finally:
        q.stop()


def test_coalesce_by_workflow_and_source():
    g = Gate()
    g.ev.clear()
    q = WorkflowQueue(runner=g)
    try:
        q.enqueue("w1")  # blocker
        assert _wait(lambda: q.snapshot()["current"] is not None)
        i1 = q.enqueue("w2", source="scheduled", coalesce=True)
        i2 = q.enqueue("w2", source="scheduled", coalesce=True)
        assert i1.id == i2.id  # coalesced into the same pending item
        assert len(q.snapshot()["pending"]) == 1
        i3 = q.enqueue("w2", source="manual", coalesce=True)  # different source
        assert i3.id != i1.id
        assert len(q.snapshot()["pending"]) == 2
        g.ev.set()
        _drain(q)
    finally:
        q.stop()


def test_error_survives_and_continues():
    g = Gate()
    g.fail.add("w1")
    q = WorkflowQueue(runner=g)
    try:
        q.enqueue("w1")  # raises inside the worker
        q.enqueue("w2")  # must still run afterwards
        _drain(q)
        assert g.ran == ["w2"]
        by_wf = {r["workflow"]: r for r in q.snapshot()["recent"]}
        assert by_wf["w1"]["status"] == "error"
        assert "boom" in (by_wf["w1"]["error"] or "")
        assert by_wf["w2"]["status"] == "done"
    finally:
        q.stop()


def test_is_busy_defers_start():
    busy = {"v": True}
    g = Gate()
    q = WorkflowQueue(runner=g, is_busy=lambda: busy["v"])
    try:
        q.enqueue("w1")
        time.sleep(0.3)
        assert q.snapshot()["current"] is None  # deferred while busy
        assert len(q.snapshot()["pending"]) == 1
        busy["v"] = False
        _drain(q)
        assert g.ran == ["w1"]
    finally:
        q.stop()


def test_pause_defers_new_items():
    g = Gate()
    q = WorkflowQueue(runner=g)
    try:
        q.pause()
        q.enqueue("w1")
        q.enqueue("w2")
        time.sleep(0.3)
        assert q.snapshot()["current"] is None
        assert len(q.snapshot()["pending"]) == 2
        assert q.snapshot()["paused"] is True
        q.resume()
        _drain(q)
        assert g.ran == ["w1", "w2"]
        assert q.snapshot()["paused"] is False
    finally:
        q.stop()


def test_pause_lets_running_item_finish():
    g = Gate()
    g.ev.clear()  # block the running item on the gate
    q = WorkflowQueue(runner=g)
    try:
        q.enqueue("w1")  # starts and hangs
        assert _wait(lambda: q.snapshot()["current"] is not None)
        q.pause()
        q.enqueue("w2")
        g.ev.set()  # release w1 -> it finishes, but paused so w2 must NOT start
        assert _wait(lambda: not g.started or g.ran == ["w1"])
        time.sleep(0.3)
        assert q.snapshot()["current"] is None
        assert [i["workflow"] for i in q.snapshot()["pending"]] == ["w2"]
        assert g.ran == ["w1"]
        q.resume()
        _drain(q)
        assert g.ran == ["w1", "w2"]
    finally:
        q.stop()


def test_reorder():
    g = Gate()
    g.ev.clear()
    q = WorkflowQueue(runner=g)
    try:
        q.enqueue("w1")  # blocker
        assert _wait(lambda: q.snapshot()["current"] is not None)
        a = q.enqueue("w2")
        b = q.enqueue("w3")
        c = q.enqueue("w1")
        assert [i["id"] for i in q.snapshot()["pending"]] == [a.id, b.id, c.id]
        # full reorder
        q.reorder([c.id, a.id, b.id])
        assert [i["id"] for i in q.snapshot()["pending"]] == [c.id, a.id, b.id]
        # partial + unknown id: b first, rest keep current relative order (c, a)
        q.reorder([b.id, "nope"])
        assert [i["id"] for i in q.snapshot()["pending"]] == [b.id, c.id, a.id]
        g.ev.set()
        _drain(q)
    finally:
        q.stop()


class TestMultisiteWorkflowKinds:
    """m1/m2 进队列。

    加新 workflow 要同时改三处（VALID_WORKFLOWS / log_wf 映射 / 分派分支），
    漏了 log_wf 那一处最阴：它在 try 外面，活干完了才炸在写日志上。
    """

    def test_m1_and_m2_are_valid(self):
        from services.workflow_queue import VALID_WORKFLOWS
        assert "m1" in VALID_WORKFLOWS and "m2" in VALID_WORKFLOWS

    def test_log_name_mapping_covers_every_valid_workflow(self):
        """这条就是为了拦“加了新 workflow 但忘了加映射”。"""
        import re
        from pathlib import Path
        from services.workflow_queue import VALID_WORKFLOWS

        src = Path(__file__).resolve().parent.parent / "services" / "workflow_orchestration.py"
        text = src.read_text(encoding="utf-8")
        m = re.search(r"log_wf = \{([^}]*)\}", text, re.S)
        assert m, "log_wf 映射不见了？"
        mapped = set(re.findall(r'"(\w+)":', m.group(1)))
        missing = set(VALID_WORKFLOWS) - mapped
        assert not missing, f"这些 workflow 没进 log_wf 映射，跑完会 KeyError: {missing}"

    def test_unknown_workflow_is_rejected_at_enqueue(self):
        from services.workflow_queue import WorkflowQueue
        q = WorkflowQueue(runner=lambda item: None)
        try:
            with pytest.raises(ValueError):
                q.enqueue("nope", {})
        finally:
            q.stop()
