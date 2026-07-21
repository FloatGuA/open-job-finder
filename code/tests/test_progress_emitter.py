"""ProgressEmitter per-workflow replay-buffer tests.

Fan-out is live-only; a page refresh reconnects the SSE stream with a fresh
queue, which used to lose the LIVE view. Per-workflow replay buffers seed a new
subscriber with EACH workflow's last-run events, so refreshing rebuilds both
W1's and W2's last-run views, and running one workflow never wipes the other's.
"""
import time

from services.progress_emitter import ProgressEmitter, ProgressEvent


def _ev(step: str, workflow: str = "w2", status: str = "running") -> ProgressEvent:
    return ProgressEvent(workflow=workflow, step=step, status=status, message=step)


def _drain(q) -> list:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_subscribe_replays_buffer():
    em = ProgressEmitter()
    em.emit(_ev("scan"))
    em.emit(_ev("analyze"))
    q = em.subscribe()  # connects AFTER events emitted (e.g. page refresh)
    assert [e.step for e in _drain(q)] == ["scan", "analyze"]


def test_live_fanout_after_subscribe():
    em = ProgressEmitter()
    q = em.subscribe()
    em.emit(_ev("read"))
    assert [e.step for e in _drain(q)] == ["read"]


def test_start_workflow_clears_only_its_own_buffer():
    em = ProgressEmitter()
    em.emit(_ev("w1card", workflow="w1")); time.sleep(0.001)
    em.emit(_ev("old", workflow="w2")); time.sleep(0.001)
    em.start_workflow("w2")  # clears w2 only, then emits w2 'start'
    steps = [(e.workflow, e.step) for e in _drain(em.subscribe())]
    assert ("w1", "w1card") in steps      # W1's last-run view preserved
    assert ("w2", "old") not in steps      # W2 buffer reset
    assert ("w2", "start") in steps


def test_subscribe_seeds_all_workflows_time_ordered():
    em = ProgressEmitter()
    em.emit(_ev("a", workflow="w1")); time.sleep(0.001)
    em.emit(_ev("b", workflow="w2")); time.sleep(0.001)
    em.emit(_ev("c", workflow="w1"))
    assert [e.step for e in _drain(em.subscribe())] == ["a", "b", "c"]


def test_buffer_trims_per_workflow():
    em = ProgressEmitter()
    em._buffer_max = 10
    for i in range(25):
        em.emit(_ev(f"s{i}", workflow="w2"))
    assert len(em._buffers["w2"]) == 10
    steps = [e.step for e in _drain(em.subscribe())]
    assert steps[0] == "s15" and steps[-1] == "s24"
