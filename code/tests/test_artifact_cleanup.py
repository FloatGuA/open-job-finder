"""services/artifact_cleanup.py: listing + deletion of failed-run JSONL logs and
W1 apply-failure screenshots. Both are file-based (no DB), tested directly against
tmp_path -- same convention as test_run_log_reader.py.
"""
import json

import pytest

from services import artifact_cleanup as ac


def _write_run(runs_dir, name, run_id, status, ts="2026-08-01T00:00:00Z"):
    runs_dir.mkdir(parents=True, exist_ok=True)
    events = [{"event": "run_start", "run_id": run_id, "pipeline": "w1", "ts": ts}]
    if status is not None:
        events.append({"event": "run_end", "run_id": run_id, "status": status, "ts": ts, "summary": {}})
    (runs_dir / name).write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n", encoding="utf-8",
    )


# ── list_failed_run_logs ────────────────────────────────────────────────────────

def test_list_failed_run_logs_includes_failure_statuses(tmp_path):
    _write_run(tmp_path, "w1_a.jsonl", "a", "failed")
    _write_run(tmp_path, "w1_b.jsonl", "b", "aborted")
    items = ac.list_failed_run_logs(tmp_path)
    assert {i["run_id"] for i in items} == {"a", "b"}


def test_list_failed_run_logs_excludes_successful_and_still_running(tmp_path):
    _write_run(tmp_path, "w1_ok.jsonl", "ok", "successful")
    _write_run(tmp_path, "w1_live.jsonl", "live", None)  # no run_end -> "running"
    assert ac.list_failed_run_logs(tmp_path) == []


def test_list_failed_run_logs_reports_size(tmp_path):
    _write_run(tmp_path, "w1_a.jsonl", "a", "failed")
    items = ac.list_failed_run_logs(tmp_path)
    assert items[0]["size_bytes"] > 0


def test_list_failed_run_logs_missing_dir(tmp_path):
    assert ac.list_failed_run_logs(tmp_path / "nope") == []


# ── list_apply_failure_screenshots ──────────────────────────────────────────────

def test_list_screenshots_parses_trailing_timestamp(tmp_path):
    (tmp_path / "w1_20260801_0900_job123_20260801_090512.png").write_bytes(b"fake")
    items = ac.list_apply_failure_screenshots(tmp_path)
    assert len(items) == 1
    assert items[0]["filename"] == "w1_20260801_0900_job123_20260801_090512.png"
    assert items[0]["label"] == "w1_20260801_0900_job123"


def test_list_screenshots_falls_back_to_stem_without_timestamp_suffix(tmp_path):
    (tmp_path / "weird_name.png").write_bytes(b"fake")
    items = ac.list_apply_failure_screenshots(tmp_path)
    assert items[0]["label"] == "weird_name"


def test_list_screenshots_missing_dir(tmp_path):
    assert ac.list_apply_failure_screenshots(tmp_path / "nope") == []


def test_list_screenshots_ignores_non_png(tmp_path):
    (tmp_path / "notes.txt").write_text("x")
    assert ac.list_apply_failure_screenshots(tmp_path) == []


# ── delete_run_log / delete_screenshot ──────────────────────────────────────────

def test_delete_run_log_removes_file(tmp_path):
    _write_run(tmp_path, "w1_a.jsonl", "a", "failed")
    assert ac.delete_run_log(tmp_path, "w1_a.jsonl") is True
    assert not (tmp_path / "w1_a.jsonl").exists()


def test_delete_run_log_rejects_path_traversal(tmp_path):
    _write_run(tmp_path, "w1_a.jsonl", "a", "failed")
    assert ac.delete_run_log(tmp_path, "../w1_a.jsonl") is False
    assert ac.delete_run_log(tmp_path, "sub/w1_a.jsonl") is False
    assert (tmp_path / "w1_a.jsonl").exists()


def test_delete_run_log_rejects_wrong_extension(tmp_path):
    (tmp_path / "w1_a.png").write_bytes(b"x")
    assert ac.delete_run_log(tmp_path, "w1_a.png") is False


def test_delete_run_log_missing_file_returns_false(tmp_path):
    assert ac.delete_run_log(tmp_path, "nope.jsonl") is False


def test_delete_screenshot_removes_file(tmp_path):
    (tmp_path / "a.png").write_bytes(b"x")
    assert ac.delete_screenshot(tmp_path, "a.png") is True
    assert not (tmp_path / "a.png").exists()


def test_delete_screenshot_rejects_path_traversal(tmp_path):
    (tmp_path / "a.png").write_bytes(b"x")
    assert ac.delete_screenshot(tmp_path, "..\\a.png") is False
    assert (tmp_path / "a.png").exists()
