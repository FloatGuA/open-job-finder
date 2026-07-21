import pytest
import services.run_logger as _run_logger


@pytest.fixture(autouse=True)
def _redirect_runs_dir(tmp_path, monkeypatch):
    """Prevent tests from writing RunLogger files to the real logs/runs/ directory."""
    monkeypatch.setattr(_run_logger, "RUNS_DIR", tmp_path / "runs")
