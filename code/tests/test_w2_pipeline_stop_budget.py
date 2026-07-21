"""W2Pipeline honors 中止 (stop_requested) and the time budget, both breaking the
conversation loop gracefully (FinalizeStep still runs, summary records stopped)."""
import pipeline.w2.pipeline as w2p
from pipeline.base import StepStatus
from pipeline.w2.pipeline import W2Config, W2Pipeline
from pipeline.w2.scan_step import ScanStepOutput


class _FakeConv:
    def __init__(self, cid):
        self.conv_id = cid
        self.company = "C"


class _FakeConvOut:
    reply_sent = False
    resume_sent = False
    stage_changed = False
    llm_degraded = False


class _FakeLogger:
    def __init__(self, stop_after=None):
        self._stop_after = stop_after
        self.calls = 0
        self.events = []

    def should_stop(self):
        if self._stop_after is None:
            return False
        return self.calls >= self._stop_after

    def log(self, event, scope, data, **kw):
        self.events.append((event, data))

    def close(self, *a, **k):
        pass


def _patch(monkeypatch, n_convs, logger):
    monkeypatch.setattr(w2p.ScanStep, "run",
                        lambda self, active_window_days=0: ScanStepOutput(status=StepStatus.SUCCESSFUL,
                                                    conversations_to_process=[_FakeConv(f"c{i}") for i in range(n_convs)],
                                                    approved_replies={}))
    finalize_called = {"v": False}
    monkeypatch.setattr(w2p, "FinalizeStep",
                        lambda reg, log: type("F", (), {"run": lambda self, **k: finalize_called.__setitem__("v", True)})())

    def _conv_run(self, conv, approved):
        logger.calls += 1
        return _FakeConvOut()
    monkeypatch.setattr(w2p.ConversationPipeline, "run", _conv_run)
    return finalize_called


def test_stop_breaks_loop_and_finalizes(monkeypatch):
    logger = _FakeLogger(stop_after=2)  # stop after 2 conversations processed
    finalize = _patch(monkeypatch, 5, logger)
    pipe = W2Pipeline(registry=object(), profile=object(), logger=logger)
    summary = pipe.run(W2Config(dry_run=True, max_run_minutes=0))
    assert summary["stopped"] is True
    assert summary["convs_processed"] == 2       # broke early, not all 5
    assert finalize["v"] is True                 # FinalizeStep still ran


def test_time_budget_breaks_loop(monkeypatch):
    logger = _FakeLogger(stop_after=None)
    finalize = _patch(monkeypatch, 5, logger)
    # fake clock: jumps past the 1-minute budget after the 2nd conversation
    ticks = iter([0, 0, 1, 61, 61, 61, 61])  # loop_start=0, then checks
    monkeypatch.setattr(w2p.time, "time", lambda: next(ticks))
    pipe = W2Pipeline(registry=object(), profile=object(), logger=logger)
    summary = pipe.run(W2Config(dry_run=True, max_run_minutes=1))
    assert summary["stopped"] is True
    assert summary["convs_processed"] < 5
    assert finalize["v"] is True
    assert any(e[0] == "run_time_budget_exceeded" for e in logger.events)
