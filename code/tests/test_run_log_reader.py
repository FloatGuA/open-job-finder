"""run_log_reader: read-only parsing of run JSONL, tested directly.

While inline in server.py these were reachable only through the HTTP layer. As
pure functions taking runs_dir they can be tested against files on disk, including
the edge cases the endpoints never exercised: a run with no run_end (still
'running'), a torn line, a file-only trace filtered out of the replay.
"""
import json

import pytest

from services import run_log_reader as rlr


def _write(runs_dir, name, events):
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / name).write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in events) + "\n",
        encoding="utf-8",
    )
    return runs_dir / name


def _start(pipeline="w1", run_id="r1", ts="2026-07-22T08:00:00Z", meta=None):
    d = {"event": "run_start", "run_id": run_id, "pipeline": pipeline, "ts": ts}
    if meta is not None:
        d["meta"] = meta
    return d


def _end(status="done", ts="2026-07-22T08:05:00Z", summary=None, duration_ms=300000):
    return {"event": "run_end", "run_id": "r1", "status": status, "ts": ts,
            "duration_ms": duration_ms, "summary": summary or {}}


# ---- iter / find --------------------------------------------------------------


def test_iter_filters_by_pipeline(tmp_path):
    _write(tmp_path, "w1_a.jsonl", [_start("w1")])
    _write(tmp_path, "w2_b.jsonl", [_start("w2")])
    assert len(rlr.iter_run_files(tmp_path)) == 2
    assert [p.name for p in rlr.iter_run_files(tmp_path, "w1")] == ["w1_a.jsonl"]


def test_iter_missing_dir_is_empty(tmp_path):
    assert rlr.iter_run_files(tmp_path / "nope") == []


def test_find_matches_run_id_not_filename(tmp_path):
    _write(tmp_path, "w1_20260722.jsonl", [_start(run_id="abc123"), _end()])
    assert rlr.find_run_file(tmp_path, "abc123").name == "w1_20260722.jsonl"
    assert rlr.find_run_file(tmp_path, "nope") is None


# ---- summarize ----------------------------------------------------------------


def test_summary_of_finished_run(tmp_path):
    p = _write(tmp_path, "w1_x.jsonl", [_start(), _end(summary={"applied": 2})])
    s = rlr.summarize_run_file(p)
    assert s["status"] == "done"
    assert s["summary"] == {"applied": 2}
    assert s["duration_ms"] == 300000


def test_summary_of_running_run_has_no_end(tmp_path):
    """A run whose process is still going (or died) has no run_end."""
    p = _write(tmp_path, "w1_x.jsonl", [_start(), {"event": "step", "step": "navigate", "ts": "x"}])
    s = rlr.summarize_run_file(p)
    assert s["status"] == "running"
    assert s["duration_ms"] is None
    assert s["summary"] is None


def test_summary_of_empty_or_non_run_is_none(tmp_path):
    assert rlr.summarize_run_file(_write(tmp_path, "e.jsonl", [])) is None
    # First line is not a run_start -> not a run we recognise.
    stray = _write(tmp_path, "s.jsonl", [{"event": "step", "step": "x", "ts": "t"}])
    assert rlr.summarize_run_file(stray) is None


# ---- detail (grouped steps + tools) -------------------------------------------


def test_detail_attaches_tools_to_their_step(tmp_path):
    p = _write(tmp_path, "w2_d.jsonl", [
        _start("w2"),
        {"event": "step", "step": "navigate", "status": "successful", "ts": "2026-07-22T08:01:00Z"},
        {"event": "tool", "step": "navigate", "tool": "goto", "status": "successful", "ts": "2026-07-22T08:01:05Z"},
        {"event": "step", "step": "read", "status": "successful", "ts": "2026-07-22T08:02:00Z"},
        {"event": "tool", "step": "read", "tool": "extract", "status": "successful", "ts": "2026-07-22T08:02:05Z"},
        _end(),
    ])
    d = rlr.parse_run_detail(p)
    assert [s["step"] for s in d["steps"]] == ["navigate", "read"]
    assert d["steps"][0]["tools"][0]["tool"] == "goto"
    assert d["steps"][1]["tools"][0]["tool"] == "extract"


def test_detail_separates_business_events(tmp_path):
    p = _write(tmp_path, "w1_d.jsonl", [
        _start(),
        {"event": "job_scored", "scope": {"job_id": "j1"}, "data": {"score": 80}, "ts": "2026-07-22T08:01:00Z"},
        _end(),
    ])
    d = rlr.parse_run_detail(p)
    assert d["steps"] == []
    assert d["business_events"][0]["event"] == "job_scored"


# ---- replay events ------------------------------------------------------------


def test_replay_maps_domain_status_to_ui(tmp_path):
    p = _write(tmp_path, "w1_r.jsonl", [
        _start(meta={"trigger": "manual"}),
        {"event": "step", "step": "apply", "status": "failed", "ts": "2026-07-22T08:01:00Z"},
        _end(status="done"),
    ])
    ev = rlr.parse_run_events(p)
    kinds = {(e["step"], e["status"]) for e in ev}
    assert ("start", "running") in kinds
    assert ("apply", "error") in kinds       # domain 'failed' -> ui 'error'
    assert ("done", "done") in kinds


def test_replay_skips_file_only_traces(tmp_path):
    """filter_decision and visible=False events never appeared on the SSE stream, so
    a replay must not surface them or it wouldn't match the live view."""
    p = _write(tmp_path, "w2_r.jsonl", [
        _start("w2"),
        {"event": "filter_decision", "scope": {}, "ts": "2026-07-22T08:01:00Z"},
        {"event": "some_trace", "visible": False, "ts": "2026-07-22T08:01:30Z"},
        {"event": "intent_analyzed", "data": {"intent": "general"}, "ts": "2026-07-22T08:02:00Z"},
        _end(),
    ])
    ev = rlr.parse_run_events(p)
    steps = {e["step"] for e in ev}
    assert "filter_decision" not in steps
    assert "some_trace" not in steps
    assert "intent_analyzed" in steps        # a visible business event survives


def test_replay_events_are_time_sorted(tmp_path):
    p = _write(tmp_path, "w1_r.jsonl", [
        _start(ts="2026-07-22T08:00:00Z"),
        {"event": "step", "step": "b", "status": "successful", "ts": "2026-07-22T08:03:00Z"},
        {"event": "step", "step": "a", "status": "successful", "ts": "2026-07-22T08:01:00Z"},
        _end(ts="2026-07-22T08:05:00Z"),
    ])
    ev = rlr.parse_run_events(p)
    assert [e["ts"] for e in ev] == sorted(e["ts"] for e in ev)


def test_iso_to_epoch_handles_z_and_bad_input():
    assert rlr.iso_to_epoch("2026-07-22T08:00:00Z") > 0
    assert rlr.iso_to_epoch("") == 0.0
    assert rlr.iso_to_epoch("not-a-date") == 0.0
