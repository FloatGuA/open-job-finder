"""RunLogger.should_stop() — the poll the W1/W2/W3 loops use to honor the 中止 button."""
from pipeline.run_logger import RunLogger
from services.progress_emitter import ProgressEmitter


def test_should_stop_reflects_emitter_stop_requested(tmp_path, monkeypatch):
    import pipeline.run_logger as rl
    monkeypatch.setattr(rl, "RUNS_DIR", tmp_path, raising=False)
    emitter = ProgressEmitter()
    logger = RunLogger(pipeline="w2", emitter=emitter)

    assert logger.should_stop() is False           # nothing requested
    emitter.request_stop()                          # user hits 中止
    assert logger.should_stop() is True             # loops will break next iteration
    emitter.finish_workflow("w2", "done")           # finish clears stop_requested
    assert logger.should_stop() is False


def test_should_stop_false_without_emitter(tmp_path, monkeypatch):
    import pipeline.run_logger as rl
    monkeypatch.setattr(rl, "RUNS_DIR", tmp_path, raising=False)
    logger = RunLogger(pipeline="w1", emitter=None)
    assert logger.should_stop() is False
