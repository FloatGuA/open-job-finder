"""System self-check probes.

Lightweight liveness checks for each subsystem the workflows depend on
(browser+session / DB / LLM). Each probe reuses the real component instead of
reimplementing it, so a failure points straight at the broken layer. No side
effects: browser is opened headless and closed, DB is read-only, LLM gets one
tiny prompt.
"""
import time
from pathlib import Path


def _run(name: str, label: str, fn) -> dict:
    start = time.time()
    try:
        ok, detail = fn()
    except Exception as exc:
        ok, detail = False, f"{type(exc).__name__}: {exc}"
    return {
        "name": name,
        "label": label,
        "ok": bool(ok),
        "duration_ms": int((time.time() - start) * 1000),
        "detail": str(detail),
    }


def _probe_browser_session(data_dir: Path):
    from services.browser_context import open_browser, close_browser
    from pipeline.common.verify_session import VerifySessionStep
    from pipeline.base import StepStatus

    page = None
    try:
        page = open_browser(data_dir, headless=True)
        out = VerifySessionStep(page).run()
        if out.status == StepStatus.SUCCESSFUL:
            return True, f"已登录：{out.username}"
        return False, out.reason or out.error or "session invalid"
    finally:
        if page is not None:
            try:
                close_browser(page)
            except Exception:
                pass


def _probe_db(tracker):
    apps = tracker.get_all()
    convs = tracker.get_hr_conversations()
    return True, f"应聘 {len(apps)} 条 · 会话 {len(convs)} 条"


def _probe_llm(model_router):
    text, provider = model_router.complete(
        prompt="Reply with the single word: OK", capability="balanced",
    )
    text = (text or "").strip()
    return bool(text), f"provider={provider} · reply={text[:40]}"


def run_probes(*, data_dir: Path, tracker, model_router) -> dict:
    """Run the lightweight infra probes sequentially and return a report dict."""
    probes = [
        _run("browser_session", "浏览器 + 登录态", lambda: _probe_browser_session(data_dir)),
        _run("db", "数据库", lambda: _probe_db(tracker)),
        _run("llm", "LLM 探活", lambda: _probe_llm(model_router)),
    ]
    return {
        "ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "ok": all(p["ok"] for p in probes),
        "probes": probes,
    }
