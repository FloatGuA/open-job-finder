"""Run-log diagnostics: the verdict must come from the log, deterministically.

These tests encode the rules that make the diagnosis trustworthy -- notably that
run_end uses done/failed while steps use successful/failed (two vocabularies;
conflating them marked all 143 healthy runs as anomalous), and that a run which
sent something real and then died is the loudest case we have.
"""
import json

import pytest

from services import run_diagnostics as rd


def _write_run(tmp_path, run_id, events):
    p = tmp_path / f"{run_id}.jsonl"
    p.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in events),
                 encoding="utf-8")
    return tmp_path


def _start(pipeline="w2", trigger="manual", params=None):
    return {"event": "run_start", "run_id": "r", "pipeline": pipeline,
            "meta": {"trigger": trigger, "params": params or {}}, "ts": "2026-07-21T08:00:00Z"}


def _end(status="done", summary=None):
    return {"event": "run_end", "run_id": "r", "status": status,
            "summary": summary or {}, "ts": "2026-07-21T08:05:00Z"}


def test_healthy_run_is_ok(tmp_path):
    d = tmp_path
    _write_run(d, "w2_ok", [
        _start(),
        {"event": "step", "step": "read", "status": "successful", "scope": {}},
        _end(summary={"convs_processed": 3}),
    ])
    diag = rd.diagnose_run("w2_ok", runs_dir=d)
    assert diag["ok"] is True
    assert diag["complete"] is True
    assert diag["status"] == "done"
    assert diag["anomalies"] == []
    assert diag["summary"] == {"convs_processed": 3}


def test_done_is_not_confused_with_step_vocabulary(tmp_path):
    """run_end says 'done'; steps say 'successful'. Treating 'done' as abnormal
    flagged every healthy run in the archive (143 of them)."""
    d = tmp_path
    _write_run(d, "w1_done", [_start(pipeline="w1"), _end(status="done")])
    assert rd.diagnose_run("w1_done", runs_dir=d)["ok"] is True


def test_missing_run_end_is_interrupted(tmp_path):
    d = tmp_path
    _write_run(d, "w2_cut", [
        _start(),
        {"event": "step", "step": "read", "status": "successful", "scope": {}},
    ])
    diag = rd.diagnose_run("w2_cut", runs_dir=d)
    assert diag["complete"] is False
    assert diag["status"] == "interrupted"
    assert diag["ok"] is False
    assert any("无 run_end" in a for a in diag["anomalies"])


def test_interrupted_after_real_outbound_is_shouted_about(tmp_path):
    """The worst case: the HR already received it, our DB may not know. Eight such
    runs exist in the real archive."""
    d = tmp_path
    _write_run(d, "w2_sent_then_died", [
        _start(),
        {"event": "resume_sent", "scope": {"conv_id": "abc"}, "data": {}},
        {"event": "resume_sent", "scope": {"conv_id": "def"}, "data": {}},
    ])
    diag = rd.diagnose_run("w2_sent_then_died", runs_dir=d)
    assert diag["ok"] is False
    assert diag["outbound"] == {"resume_sent": 2}
    assert diag["outbound_total"] == 2
    assert any("对方已收到" in a for a in diag["anomalies"])


def test_failed_run_end_is_flagged(tmp_path):
    d = tmp_path
    _write_run(d, "w1_failed", [_start(pipeline="w1"), _end(status="failed")])
    diag = rd.diagnose_run("w1_failed", runs_dir=d)
    assert diag["ok"] is False
    assert any("failed" in a for a in diag["anomalies"])


def test_failure_events_and_step_errors_are_collected(tmp_path):
    d = tmp_path
    _write_run(d, "w1_bad", [
        _start(pipeline="w1"),
        {"event": "db_write_failed", "scope": {}, "data": {}},
        {"event": "step", "step": "apply", "status": "failed", "scope": {"job_id": "j1"},
         "error": "dialog blocked"},
        _end(),
    ])
    diag = rd.diagnose_run("w1_bad", runs_dir=d)
    assert diag["ok"] is False
    assert diag["failures"] == {"db_write_failed": 1}
    assert diag["errors"][0]["step"] == "apply"
    assert any("落库失败" in a for a in diag["anomalies"])


def test_legacy_format_is_not_diagnosable_rather_than_failed(tmp_path):
    """387 archived runs predate run_start. "Cannot judge" must not be reported as
    "went wrong" -- otherwise the archive looks like a catastrophe."""
    d = tmp_path
    _write_run(d, "old", [{"event": "step", "step": "x", "status": "successful"}])
    diag = rd.diagnose_run("old", runs_dir=d)
    assert diag["diagnosable"] is False
    assert diag["status"] == "unrecognised"


def test_missing_file_is_reported(tmp_path):
    diag = rd.diagnose_run("nope", runs_dir=tmp_path)
    assert diag["found"] is False
    assert diag["diagnosable"] is False


def test_torn_last_line_does_not_abort_diagnosis(tmp_path):
    """A process killed mid-write leaves a partial line; the rest still counts."""
    p = tmp_path / "w2_torn.jsonl"
    p.write_text(
        json.dumps(_start(), ensure_ascii=False) + "\n"
        + json.dumps(_end(), ensure_ascii=False) + "\n"
        + '{"event": "step", "sta',
        encoding="utf-8",
    )
    diag = rd.diagnose_run("w2_torn", runs_dir=tmp_path)
    assert diag["complete"] is True
    assert diag["ok"] is True


def test_dirty_log_with_lone_surrogates_still_diagnoses(tmp_path):
    """Scraped DOM text sometimes carries unpaired surrogates. They parse but fail
    to encode, so an unsanitised verdict is unserialisable -- breaking diagnosis on
    exactly the messy runs it is meant to inspect. 553 archived runs hit this."""
    p = tmp_path / "w2_dirty.jsonl"
    lines = [
        json.dumps(_start(), ensure_ascii=False),
        json.dumps({"event": "step", "step": "read", "status": "failed", "scope": {},
                    "error": "boom \udca0 bad"}, ensure_ascii=False),
        json.dumps(_end(), ensure_ascii=False),
    ]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8", errors="surrogatepass")

    diag = rd.diagnose_run("w2_dirty", runs_dir=tmp_path)
    # must be encodable -- this is what the API layer needs
    json.dumps(diag).encode("utf-8")
    rd.render_report(diag).encode("utf-8")
    assert diag["errors"][0]["step"] == "read"


def test_param_check_catches_knob_that_never_reached_the_runner(tmp_path):
    """The silent class of bug: an endpoint accepts score_threshold but nothing
    forwards it, so the run quietly uses the default."""
    d = tmp_path
    _write_run(d, "w1_p", [
        _start(pipeline="w1", params={"score_threshold": 60, "max_cards": 1}),
        _end(),
    ])
    diag = rd.diagnose_run("w1_p", runs_dir=d)
    rows = rd.check_params_applied(diag, {"score_threshold": 40, "max_cards": 1})
    by = {r["name"]: r for r in rows}
    assert by["score_threshold"]["ok"] is False   # asked 40, log says 60
    assert by["score_threshold"]["actual"] == 60
    assert by["max_cards"]["ok"] is True


def test_render_report_contains_the_key_sections(tmp_path):
    d = tmp_path
    _write_run(d, "w2_r", [
        _start(params={"max_conversations": 5}),
        {"event": "resume_sent", "scope": {}, "data": {}},
        {"event": "step", "step": "read", "status": "successful", "scope": {}},
        _end(summary={"resumes_sent": 1}),
    ])
    diag = rd.diagnose_run("w2_r", runs_dir=d)
    text = rd.render_report(diag, rd.check_params_applied(diag, {"max_conversations": 5}))
    assert "RUN 诊断" in text
    assert "完整性" in text
    assert "参数生效核对" in text
    assert "外发动作" in text
    assert "发简历 1" in text
