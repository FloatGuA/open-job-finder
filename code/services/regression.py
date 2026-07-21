"""Regression test runner (layer 1 of the regression tab: logic regression).

Runs the pytest suite in a subprocess and parses the JUnit XML into a structured
report for the dashboard. Reuses the real suite (455 tests) rather than
reimplementing anything. Layer 0 (env probes) lives in services/selfcheck.py.
"""
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional


def run_pytest(code_dir: Path, timeout: int = 600) -> dict:
    """Run pytest in code_dir, return a parsed report.

    Report shape:
        { ok, total, passed, failed, skipped, duration_s, ran_at, exit_code,
          files: [ { name, passed, failed, skipped, failures: [ {name, message} ] } ] }
    """
    xml_fd, xml_path = tempfile.mkstemp(suffix=".xml", prefix="ojf_pytest_")
    os.close(xml_fd)
    start = time.time()
    exit_code = None
    parse_error = None
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider",
             f"--junitxml={xml_path}"],
            cwd=str(code_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        exit_code = proc.returncode
        try:
            report = _parse_junit(xml_path)
        except (ET.ParseError, FileNotFoundError) as exc:
            # pytest crashed before writing XML (import/collection error): surface it
            # rather than pretend zero tests. stderr tail is the useful signal.
            parse_error = f"{type(exc).__name__}: {exc}"
            report = {"ok": False, "total": 0, "passed": 0, "failed": 0,
                      "skipped": 0, "files": []}
            report["collect_error"] = (proc.stderr or proc.stdout or "")[-800:]
    finally:
        try:
            os.unlink(xml_path)
        except OSError:
            pass

    report["duration_s"] = round(time.time() - start, 1)
    report["ran_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    report["exit_code"] = exit_code
    if parse_error:
        report["parse_error"] = parse_error
    return report


def _parse_junit(xml_path: str) -> dict:
    root = ET.parse(xml_path).getroot()
    # Root is <testsuites> (wrapping one or more <testsuite>) or a bare <testsuite>.
    suites = root.findall("testsuite") if root.tag == "testsuites" else [root]

    files: dict = {}  # test-file name -> aggregate
    for suite in suites:
        for tc in suite.iter("testcase"):
            # classname is dotted: "tests.test_foo" (module-level) or
            # "tests.test_foo.TestBar" (class-based). Group by the test FILE, i.e.
            # the "test_*" segment, not the trailing class name.
            parts = [p for p in (tc.get("classname") or "").split(".") if p]
            cls = next((p for p in parts if p.startswith("test_")),
                       parts[-1] if parts else "unknown")
            f = files.setdefault(
                cls, {"name": cls, "passed": 0, "failed": 0, "skipped": 0, "failures": []}
            )
            # ElementTree elements are falsy when empty, so test with `is not None`.
            failure = tc.find("failure")
            if failure is None:
                failure = tc.find("error")
            skipped = tc.find("skipped")
            if failure is not None:
                f["failed"] += 1
                f["failures"].append({
                    "name": tc.get("name", ""),
                    "message": (failure.get("message") or "").strip()[:300],
                })
            elif skipped is not None:
                f["skipped"] += 1
            else:
                f["passed"] += 1

    # Failing files first, then alphabetical, so problems surface at the top.
    file_list = sorted(files.values(), key=lambda x: (x["failed"] == 0, x["name"]))
    passed = sum(f["passed"] for f in file_list)
    failed = sum(f["failed"] for f in file_list)
    skipped = sum(f["skipped"] for f in file_list)
    return {
        "ok": failed == 0,
        "total": passed + failed + skipped,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "files": file_list,
    }


# ---- Layer 2: data invariants (read-only checks over the tracker) -------------

_VALID_APP_STATUS = {"APPLIED", "INTERVIEWING", "OFFER", "REJECTED"}
_DEAD_APP_STATUS = {"FOUND", "SCORED", "CHATTING"}
_VALID_STAGE = {"new", "active", "resume_sent", "interview", "offer", "closed"}
_VALID_REPLY_STATUS = {"pending", "approved", "revision", "sent", "dismissed"}
# Only replies still waiting to be sent must carry text. 'sent' is excluded on
# purpose: reply_text is a working draft "cleared after send" (schemas.py), so a
# sent conversation legitimately has an empty reply_text.
_REPLY_NEEDS_TEXT = {"approved", "revision"}


def run_invariants(tracker) -> dict:
    """Assert data-layer invariants the DB constraints can't enforce (status/stage
    enums, reply consistency). Read-only via tracker getters -- no raw SQL here."""
    apps = tracker.get_all()
    convs = tracker.get_hr_conversations()
    checks = []

    def add(name, offenders, detail):
        checks.append({
            "name": name,
            "ok": len(offenders) == 0,
            "count": len(offenders),
            "detail": detail if offenders else "OK",
        })

    dead = [a for a in apps if a.status in _DEAD_APP_STATUS]
    add("应聘状态无死态(FOUND/SCORED/CHATTING)", dead,
        f"{len(dead)} 条: " + ",".join(sorted({a.status for a in dead})))

    bad_status = [a for a in apps if a.status not in _VALID_APP_STATUS]
    add("应聘状态全部合法", bad_status,
        ",".join(sorted({a.status for a in bad_status}))[:120])

    bad_stage = [c for c in convs if c.stage not in _VALID_STAGE]
    add("会话 stage 全部合法", bad_stage,
        ",".join(sorted({c.stage for c in bad_stage}))[:120])

    bad_rs = [c for c in convs if c.reply_status and c.reply_status not in _VALID_REPLY_STATUS]
    add("回复状态全部合法", bad_rs,
        ",".join(sorted({c.reply_status for c in bad_rs}))[:120])

    empty_reply = [c for c in convs
                   if c.reply_status in _REPLY_NEEDS_TEXT and not (c.reply_text or "").strip()]
    add("待发送回复必有正文", empty_reply,
        f"{len(empty_reply)} 条会话 reply_status 为待发送(approved/revision)但 reply_text 为空")

    # ---- Watermark / analysis invariants -------------------------------------
    # These encode the read-vs-analyze decoupling contract (#53). last_analyzed_ts
    # is "the last message we SUCCESSFULLY analyzed up to"; last_msg_ts is "the last
    # message we saw". Violations mean the dirty check will mis-fire: too high and a
    # conversation stops being re-analyzed (goes invisible), inconsistent with intent
    # and we claimed success without storing a verdict.
    overshoot = [c for c in convs
                 if (c.last_analyzed_ts or 0) > (c.last_msg_ts or 0)]
    add("分析水位线不超过消息水位线", overshoot,
        f"{len(overshoot)} 条会话 last_analyzed_ts > last_msg_ts(水位线越界→会话将不再被重新分析)")

    analyzed_no_intent = [c for c in convs
                          if (c.last_analyzed_ts or 0) > 0 and not (c.intent or "").strip()]
    add("已分析的会话必有结论", analyzed_no_intent,
        f"{len(analyzed_no_intent)} 条会话 last_analyzed_ts>0 但 intent 为空(声称分析成功却无结论)")

    # Mirror of _REPLY_NEEDS_TEXT: reply_text is a working draft cleared after send,
    # so 'sent' MUST have an empty one. This is the invariant that guards the
    # mark-sent semantic convergence (three implementations, one wrote NULL).
    sent_with_text = [c for c in convs
                      if c.reply_status == "sent" and (c.reply_text or "").strip()]
    add("已发送回复不留草稿", sent_with_text,
        f"{len(sent_with_text)} 条会话 reply_status='sent' 但 reply_text 非空(发送后未清草稿)")

    # DB-side aggregates (EXISTS / anti-join) -- see tracker.get_data_health.
    health = tracker.get_data_health()
    hr_no_intent = health["convs_hr_no_intent"]
    checks.append({
        "name": "有 HR 消息的会话必已分析",
        "ok": hr_no_intent == 0,
        "count": hr_no_intent,
        "detail": "OK" if hr_no_intent == 0 else
                  f"{hr_no_intent} 条会话有 HR 消息但 intent 为空"
                  f"(读成功/分析失败→控制台隐形，#52/#53 的 bug 特征)",
    })
    orphans = health["orphan_messages"]
    checks.append({
        "name": "消息无孤儿(会话行存在)",
        "ok": orphans == 0,
        "count": orphans,
        "detail": "OK" if orphans == 0 else
                  f"{orphans} 条 hr_messages 找不到对应会话行(历史不可达)",
    })

    return {
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ok": all(c["ok"] for c in checks),
        "total_apps": len(apps),
        "total_convs": len(convs),
        "checks": checks,
    }


# ---- Layer 3: real-machine end-to-end smoke (dry-run, tiny scale) -------------


def _diagnose_smoke_runs(started_at: float, trigger: str,
                         w1_expected: dict, w2_expected: dict) -> list:
    """Diagnose the w1/w2 runs this smoke just produced, from their run logs.

    Located by (pipeline, trigger, mtime >= start) rather than by threading a
    run_id back out of the runners. Failure to diagnose is reported, never
    silently dropped -- an absent diagnosis would otherwise read as "all clear".
    """
    from services import run_diagnostics as rd

    out = []
    for pipeline, expected in (("w1", w1_expected), ("w2", w2_expected)):
        try:
            ids = rd.find_runs(pipeline=pipeline, trigger=trigger,
                               since_epoch=started_at - 5, limit=1)
            if not ids:
                # No log to judge (e.g. a patched runner in tests, or the run never
                # started). "Cannot judge" is not "went wrong" -- keep it out of the
                # failure bucket, same rule as legacy logs in run_diagnostics.
                out.append({"pipeline": pipeline, "run_id": None, "diagnosable": False,
                            "ok": False,
                            "anomalies": [f"未找到本次 {pipeline} 的 run 日志(trigger={trigger})"],
                            "report": ""})
                continue
            diag = rd.diagnose_run(ids[0])
            param_checks = rd.check_params_applied(diag, expected)
            diag["param_checks"] = param_checks
            diag["params_ok"] = all(r["ok"] for r in param_checks)
            diag["report"] = rd.render_report(diag, param_checks)
            out.append(diag)
        except Exception as exc:  # diagnosis must never break the smoke itself
            out.append({"pipeline": pipeline, "run_id": None, "diagnosable": False,
                        "ok": False,
                        "anomalies": [f"诊断失败: {type(exc).__name__}: {exc}"],
                        "report": ""})
    return out


def _diagnostics_verdict(diagnostics: list) -> dict:
    """Roll the per-run diagnoses into one verdict.

    Only runs we could actually judge count. params_applied is called out
    separately because a knob that never reached the runner means the smoke did
    not test what you asked it to -- the run looks healthy and still proves
    nothing about the setting you were trying to exercise.
    """
    judged = [d for d in diagnostics if d.get("diagnosable")]
    anomalies = []
    for d in diagnostics:
        for a in d.get("anomalies", []):
            anomalies.append(f"[{d.get('pipeline') or d.get('run_id') or '?'}] {a}")
    return {
        "judged": len(judged),
        "total": len(diagnostics),
        "ok": all(d.get("ok") for d in judged) if judged else None,
        "params_applied": (all(d.get("params_ok", True) for d in judged)
                           if judged else None),
        "anomalies": anomalies,
    }

def run_smoke(*, submit, tracker,
              dry_run: bool = True, w1_max: int = 2, w2_max: int = 5,
              score_threshold: Optional[int] = None,
              no_response_days: Optional[int] = None,
              stale_conv_days: Optional[int] = None) -> dict:
    """Real-browser smoke over W1/W2. Two modes:

    `submit(workflow, params) -> summary` executes ONE workflow and blocks until it
    finishes. It is injected rather than calling run_w1/run_w2 directly so that the
    smoke runs through the SAME path as every other workflow start -- the queue.
    Owning a second execution path was the real hazard: the queue runner also writes
    the schedule log, maps the trigger and clears the mutex on error, and anything
    added there later would silently not apply to the smoke (the "two implementations,
    harden one and miss the other" failure this codebase has hit before).
    Tests inject a fake submit; no browser, no queue.

    dry-run (default): dry_run=True, tiny scale -- asserts only that the READ path
    did not break (session / selectors / DOM / APIs). Nothing is applied or sent;
    harmless, run it as often as you like.

    live: dry_run=False -- actually applies (W1) and sends resume/agrees WeChat (W2),
    then asserts the outbound action PERSISTED, not just "did not crash". The core
    assertion is symmetric on both workflows: an outbound action MUST show up in the
    DB (W1 apply -> count_today grows; W2 resume send -> hr_messages grows). If the
    action reports success but the DB did not move, that is a persistence failure
    (the exact "applied but never stored" class of bug we have hit before) and the
    check goes red. When there is simply nothing to act on this run (no new card /
    no HR asking for a resume), we say so honestly ("未覆盖") rather than fake a pass.

    W3 (sending approved replies to real HRs) is never included -- most destructive,
    excluded by design. Slow: opens a real browser and needs a live Boss login.

    The workflow knobs (score_threshold / no_response_days / stale_conv_days) are
    passed through rather than left at their defaults, because the defaults can make
    the smoke structurally unable to cover anything: with the stock threshold of 60,
    a run whose cards all score below it applies nothing, so the apply path reports
    "not covered" forever and the gate never closes. Lower the threshold to force
    coverage -- reusing the real knob instead of inventing a "force apply" flag.
    """
    t0 = time.time()
    checks = []
    mode = "dry" if dry_run else "live"
    # Only forward what the caller actually set; None means "use the runner default".
    w1_extra = {} if score_threshold is None else {"score_threshold": int(score_threshold)}
    w2_extra = {}
    if no_response_days is not None:
        w2_extra["no_response_days"] = int(no_response_days)
    if stale_conv_days is not None:
        w2_extra["stale_conv_days"] = int(stale_conv_days)
    # trigger identifies who launched the run inside run_start.meta -- the smoke's
    # own runs must be findable in the log archive afterwards (see run_diagnostics).
    trigger = "smoke" if dry_run else "smoke_live"
    w1_params = {"dry_run": dry_run, "max_cards": w1_max, "headless": True,
                 "trigger": trigger, **w1_extra}
    w2_params = {"dry_run": dry_run, "max_conversations": w2_max, "headless": True,
                 "trigger": trigger, **w2_extra}

    def step(name, fn, ok_fn, detail_fn, covered_fn):
        """covered_fn answers "did this run actually exercise the path?" -- separate
        from ok_fn ("did anything fail?"). A run where there was nothing to apply and
        nothing to send passes every assertion while verifying nothing; reporting that
        as a plain green is how a smoke test silently stops being a gate. So coverage
        is tracked as its own axis and surfaced as report["fully_covered"]."""
        s0 = time.time()
        try:
            summary = fn()
            ok = ok_fn(summary)
            detail = detail_fn(summary)
            covered = covered_fn(summary)
        except Exception as exc:
            summary, ok, detail, covered = {}, False, f"{type(exc).__name__}: {exc}", False
        checks.append({
            "name": name, "ok": bool(ok), "covered": bool(covered), "detail": detail,
            "duration_s": round(time.time() - s0, 1), "summary": summary,
        })

    if dry_run:
        step(
            "W1 dry-run: 搜索→抓卡→抓JD→评分(不投递)",
            lambda: submit("w1", w1_params),
            lambda s: isinstance(s, dict) and not s.get("error") and int(s.get("cards_viewed", 0) or 0) >= 1,
            lambda s: f"cards_viewed={s.get('cards_viewed')} scored={s.get('scored')} "
                      f"applied={s.get('applied')}(dry) errors={s.get('errors')}"
                      + (f" · {s['error']}" if s.get("error") else ""),
            # Dry-run exercises the READ path, so coverage = we actually reached and
            # scored a card. Zero cards means the search/DOM path told us nothing.
            lambda s: int(s.get("cards_viewed", 0) or 0) >= 1 and int(s.get("scored", 0) or 0) >= 1,
        )
        step(
            "W2 dry-run: 会话列表→导航→读消息→意图分析(不发送)",
            lambda: submit("w2", w2_params),
            lambda s: isinstance(s, dict) and not s.get("error"),
            lambda s: f"convs_processed={s.get('convs_processed')} "
                      f"stage_changes={s.get('stage_changes')} resumes_sent={s.get('resumes_sent')}(dry)"
                      + (f" · {s['error']}" if s.get("error") else ""),
            # Coverage = at least one conversation was navigated + read + analyzed.
            # Zero processed means the chat-list/API path produced nothing to work on.
            lambda s: int(s.get("convs_processed", 0) or 0) >= 1,
        )
    else:
        def _w1_live():
            before = tracker.count_today()
            s = submit("w1", w1_params)
            if isinstance(s, dict):
                s["_applied_delta"] = tracker.count_today() - before
            return s

        def _w1_live_ok(s):
            if not isinstance(s, dict) or s.get("error"):
                return False
            applied = int(s.get("applied", 0) or 0)
            # Applied a greeting -> it MUST land in applications (count_today grows).
            # Nothing applied (no card / all skipped) -> honestly not covered, still ok.
            return int(s.get("_applied_delta", 0) or 0) >= 1 if applied > 0 else True

        def _w1_live_detail(s):
            if s.get("error"):
                return f"errors={s.get('errors')} · {s['error']}"
            applied = int(s.get("applied", 0) or 0)
            delta = int(s.get("_applied_delta", 0) or 0)
            if applied == 0:
                return (f"本轮无投递(cards_viewed={s.get('cards_viewed')} scored={s.get('scored')})"
                        f"—未覆盖投递落库验证")
            if delta < 1:
                return f"真投{applied}但今日投递数未增(Δ={delta})—落库失败!"
            return f"真投{applied} · 今日投递 Δ+{delta}(已落库)"

        def _w2_live():
            tb = tracker.get_lifecycle_counts()["tables"]
            s = submit("w2", w2_params)
            if isinstance(s, dict):
                tb2 = tracker.get_lifecycle_counts()["tables"]
                s["_msgs_delta"] = tb2["hr_messages"] - tb["hr_messages"]
                s["_convs_delta"] = tb2["hr_conversations"] - tb["hr_conversations"]
            return s

        def _w2_live_ok(s):
            if not isinstance(s, dict) or s.get("error"):
                return False
            # Sent a resume -> a new outbound message MUST persist (hr_messages grows),
            # mirror of the W1 apply->count_today assertion. Wechat-agree + upsert of an
            # already-seen conversation are UPDATEs (no row delta), so absent an outbound
            # send we only require the pipeline not to crash.
            resumes = int(s.get("resumes_sent", 0) or 0)
            return int(s.get("_msgs_delta", 0) or 0) >= 1 if resumes > 0 else True

        def _w2_live_detail(s):
            if s.get("error"):
                return f"convs_processed={s.get('convs_processed')} · {s['error']}"
            resumes = int(s.get("resumes_sent", 0) or 0)
            md = int(s.get("_msgs_delta", 0) or 0)
            cd = int(s.get("_convs_delta", 0) or 0)
            base = (f"convs_processed={s.get('convs_processed')} stage_changes={s.get('stage_changes')} "
                    f"落库Δ(消息+{md}/会话+{cd})")
            if resumes > 0:
                return (f"{base} · 真发简历{resumes}"
                        + (f"—但消息未落库(Δ={md})落库失败!" if md < 1 else "(已落库)"))
            return f"{base} · 本轮无简历外发—未覆盖发送落库验证(微信同意/落库仍真跑)"

        # Coverage for live = an outbound action actually happened, which is the only
        # case where the "did it persist?" assertion means anything. Nothing applied /
        # nothing sent -> ok stays True (nothing broke) but covered is False, so the
        # report cannot read as a full pass. This is the difference between "the gate
        # let it through" and "the gate was never closed".
        step("W1 真跑: 搜索→抓卡→抓JD→评分→真投递→断言落库",
             _w1_live, _w1_live_ok, _w1_live_detail,
             lambda s: int(s.get("applied", 0) or 0) >= 1)
        step("W2 真跑: 会话→读消息→意图→真发简历/同意微信→断言落库",
             _w2_live, _w2_live_ok, _w2_live_detail,
             lambda s: int(s.get("resumes_sent", 0) or 0) >= 1)

    uncovered = [c["name"] for c in checks if not c["covered"]]
    # Diagnose the runs this smoke just produced, straight from their logs. The log
    # is the durable record (flushed per line) and it is what a human or a model
    # should read afterwards -- see docs/run-log-guide.md.
    diagnostics = _diagnose_smoke_runs(t0, trigger,
                                       {**w1_extra, "max_cards": w1_max, "dry_run": dry_run},
                                       {**w2_extra, "max_conversations": w2_max, "dry_run": dry_run})
    return {
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "mode": mode,
        "params": {"dry_run": dry_run, "w1_max": w1_max, "w2_max": w2_max,
                   "score_threshold": score_threshold,
                   "no_response_days": no_response_days,
                   "stale_conv_days": stale_conv_days},
        "diagnostics": diagnostics,
        "diagnostics_verdict": _diagnostics_verdict(diagnostics),
        "ok": all(c["ok"] for c in checks),
        # fully_covered is the real gate: ok only says nothing failed, which a run
        # that did nothing also satisfies. Use this, not ok, to decide "verified".
        "fully_covered": all(c["covered"] for c in checks),
        "uncovered": uncovered,
        # Paths this smoke deliberately never exercises. Stated in the report so the
        # gap is visible at the point of use rather than buried in a docstring --
        # W3 sends approved replies to real HRs (most destructive), so it is guarded
        # by unit tests + the layer-2 invariants ('已发送回复不留草稿') instead.
        "not_covered_paths": ["W3 发送已批准回复(靠单测+数据不变量守)"],
        "duration_s": round(time.time() - t0, 1),
        "checks": checks,
    }
