"""Workflow orchestration, extracted from dashboard/server.py.

This is the layer the audit flagged: server.py's "wiring" had grown the actual
execution of workflows -- the queue runner, the three W1/W2/W3 runners, the Boss
daily-cap state, the self-check cycle, and the regression-smoke driver. That is
orchestration, not HTTP wiring, and it is the path the live smoke exercises.

Coupling to app.state is unavoidable (these need tracker / config / model_router /
emitter / the workflow queue), so the service takes a `get_state` accessor rather
than importing app: it reads app.state at CALL time, after _initialize_state has
populated it. The FastAPI-facing helpers (_enqueue_response, endpoint bodies) stay
in server.py -- only the execution moves here.
"""
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)


class OrchestrationService:
    """Owns workflow execution: the queue runner, the W1/W2/W3 runners, the daily-cap
    state, the self-check cycle, and the regression smoke.

    Injected dependencies:
      get_state()          -> app.state (read at call time, not construction)
      ensure_state()       -> None   (= server._initialize_state; idempotent)
      data_dir             Path
      write_schedule_log(entry)      append a schedule-log line
      write_selfcheck_log(entry)     append a self-check-log line
      smoke_log_path       Path      where regression smoke reports are appended
      submit_timeout       seconds a smoke item may take before we give up
    """

    def __init__(
        self,
        *,
        get_state: Callable[[], Any],
        ensure_state: Callable[[], None],
        data_dir: Path,
        write_schedule_log: Callable[[dict], None],
        write_selfcheck_log: Callable[[dict], None],
        smoke_log_path: Path,
        submit_timeout: int = 3600,
    ) -> None:
        self._get_state = get_state
        self._ensure = ensure_state
        self._data_dir = data_dir
        self._write_schedule_log = write_schedule_log
        self._write_selfcheck_log = write_selfcheck_log
        self._smoke_log_path = smoke_log_path
        self._submit_timeout = submit_timeout

    @property
    def _st(self):
        return self._get_state()

    # -- Boss daily-cap state ---------------------------------------------------

    @staticmethod
    def china_today():
        """Boss's daily greeting cap resets at China-local midnight, so 'today' for
        the cap is the China (UTC+8) date, not the UTC date."""
        from datetime import timedelta
        return (datetime.now(timezone.utc) + timedelta(hours=8)).date()

    def mark_rate_limited_today(self) -> None:
        """Record that W1 hit Boss's daily cap today so scheduled apply + selfcheck
        pause until the China date rolls over (in-memory; a restart clears it, which
        only means one extra attempt that re-trips the cap and re-marks)."""
        self._st.rate_limited_date = self.china_today()
        logger.info("W1 hit Boss daily cap; pausing scheduled apply + selfcheck for %s",
                    self._st.rate_limited_date)

    def is_rate_limited_today(self) -> bool:
        return getattr(self._st, "rate_limited_date", None) == self.china_today()

    # -- the three workflow runners (called only by run_item) -------------------

    def _run_apply_workflow(self, overrides: dict[str, Any]) -> tuple[str, dict]:
        from pipeline.w1_runner import run_w1
        from services.settings_resolver import resolve_params
        self._ensure()
        st = self._st
        p = resolve_params("w1", overrides, st.config, self._data_dir)
        # 兼容旧调度 params：apply_limit 旧名 → max_cards
        max_cards_raw = p.get("max_cards") or overrides.get("apply_limit") or 0
        max_cards = int(max_cards_raw) if max_cards_raw and int(max_cards_raw) > 0 else None
        summary = run_w1(
            config=st.config, tracker=st.tracker, model_router=st.model_router,
            emitter=getattr(st, "emitter", None),
            dry_run=bool(p.get("dry_run", False)),
            score_threshold=int(p.get("score_threshold", 60)),
            max_cards=max_cards,
            search_url=overrides.get("search_url") or None,
            headless=bool(p.get("headless", True)),
            debug=bool(overrides.get("debug", True)),
            data_dir=self._data_dir,
            trigger=overrides.get("_trigger", "manual"),
        )
        # A Boss daily-cap hit pauses today's scheduled apply + selfcheck.
        if isinstance(summary, dict) and summary.get("rate_limited"):
            self.mark_rate_limited_today()
        # (log line, raw summary): the schedule log wants prose, the smoke needs the
        # actual counters to assert on. Returning both keeps one execution path.
        return "apply 工作流完成", (summary if isinstance(summary, dict) else {})

    def _run_check_workflow(self, overrides: dict[str, Any]) -> tuple[str, dict]:
        from pipeline.w2_runner import run_w2
        from services.settings_resolver import resolve_params
        self._ensure()
        st = self._st
        p = resolve_params("w2", overrides, st.config, self._data_dir)
        summary = run_w2(
            config=st.config, tracker=st.tracker, model_router=st.model_router,
            emitter=getattr(st, "emitter", None),
            dry_run=bool(p.get("dry_run", False)),
            max_conversations=int(p.get("max_conversations", 200)),
            no_response_days=int(p.get("no_response_days", 14)),
            stale_conv_days=int(p.get("stale_conv_days", 30)),
            auto_send_adapted_resume=bool(p.get("auto_send_adapted_resume", False)),
            headless=bool(p.get("headless", True)),
            debug=bool(overrides.get("debug", True)),
            data_dir=self._data_dir,
            trigger=overrides.get("_trigger", "manual"),
        )
        return "check 工作流完成", (summary if isinstance(summary, dict) else {})

    def _run_reply_workflow(self, overrides: dict[str, Any]) -> tuple[str, dict]:
        from pipeline.w3_runner import run_w3
        self._ensure()
        st = self._st
        hl = overrides.get("headless")
        summary = run_w3(
            config=st.config, tracker=st.tracker, model_router=st.model_router,
            emitter=getattr(st, "emitter", None),
            dry_run=bool(overrides.get("dry_run") or False),
            max_replies=int(overrides.get("max_replies") or 50),
            headless=bool(hl) if hl is not None else False,
            debug=bool(overrides.get("debug", True)),
            data_dir=self._data_dir,
        )
        return "reply 工作流完成", (summary if isinstance(summary, dict) else {})

    # -- multi-site Layer 1 (m1 = 选岗, m2 = 填表) -------------------------------
    #
    # 这两条走的是**完全不同的浏览器栈**：chrome-devtools-mcp + 各站独立的
    # data/browser_profile_multisite/<site>/，跟 W1/W2/W3 的 DrissionPage +
    # data/browser_profile/ 是两个 Chrome 实例，互不干扰。
    #
    # 但**仍然进同一个队列串行跑**：并行要多一套 SSE 通道和 running 状态，而且
    # 两个 Chrome + 两路 LLM 同时跑，机器和人的注意力都吃不消（用户 2026-08-14
    # 确认"浏览器互斥还是共享"）。共享队列还顺带拿到 schedule_log / trigger 归类
    # ——"某功能有自己的执行路径"在这个项目里已经是记过案的坏味道。
    #
    # run_layer1 是 async 的，这里用 asyncio.run 桥接：队列 runner 是同步的
    # （线程模型），而整个项目刻意不引入 async（DrissionPage 不支持）。

    def _run_multisite_select(self, overrides: dict[str, Any]) -> tuple[str, dict]:
        """m1：按求职偏好自主选岗，产出 pending_jobs 待审批记录。对外零副作用。"""
        import asyncio

        from multisite.layer1_agent import run_layer1

        self._ensure()
        site = str(overrides.get("site") or "")
        search_url = str(overrides.get("search_url") or "")
        if not site or not search_url:
            raise ValueError("m1 需要 site 和 search_url 两个参数")

        # 名额与翻页预算跟着 item 走：CLI 的 --category / --max-pages 现在会放进
        # params，队列侧不读的话它们就静默失效（默认路径正是走队列的）。
        # 不给 = 用 profile 的站点解析结果 / 默认 8 页，跟直接跑一致。
        categories = overrides.get("categories") or None
        if categories is not None and not isinstance(categories, dict):
            raise ValueError("m1 的 categories 必须是 {类别: 名额} 字典")

        state = asyncio.run(run_layer1(
            resume_pdf_path="",          # 选岗阶段用不到简历
            site_name=site,
            search_url=search_url,
            headless=bool(overrides.get("headless") or False),
            tracker=self._st.tracker,
            quotas=categories,
            max_pages=int(overrides.get("max_pages") or 8),
            select_only=True,
            emitter=getattr(self._st, "emitter", None),
            workflow="m1",
        ))
        found = state.get("found_jobs") or []
        new_ids = state.get("pending_job_ids") or []
        return (f"选岗完成：找到 {len(found)} 个，新入库 {len(new_ids)} 条待审批",
                {"found": len(found), "new": len(new_ids)})

    def _run_multisite_fill(self, overrides: dict[str, Any]) -> tuple[str, dict]:
        """m2：对**一个已批准的岗位**打开申请表、上传简历、扫描空字段。

        一个岗位一次 run（用户 2026-08-14 定："用队列，每个投递一个 run"）：批准
        5 个就排 5 个 item，中途哪个挂了一目了然，也不用处理"第 3 个挂了后面还跑
        不跑"。

        **不提交**——提交是 Layer 3 的事，而且提交类点击在 safe_tools 里被代码
        拦着，不是靠这里小心。
        """
        import asyncio

        from multisite.layer1_agent import run_layer1

        self._ensure()
        job_id = overrides.get("pending_job_id")
        if not isinstance(job_id, int):
            raise ValueError("m2 需要 pending_job_id")
        job = self._st.tracker.get_pending_job(job_id)
        if job is None:
            raise ValueError(f"pending_job {job_id} 不存在")
        if job.status != "approved":
            # 没批准就填表 = 绕过 Checkpoint 1。这一层是队列的守门，不是 UI 的。
            raise ValueError(f"pending_job {job_id} 状态是 {job.status}，只有 approved 才能填表")

        from services.resume_store import ResumeStore

        resume = str(overrides.get("resume_pdf_path") or "") or \
            ResumeStore(str(self._data_dir)).latest_export_path()
        if not resume:
            raise ValueError("没有可用的简历 PDF：先在 Dashboard「简历」页导出一份，"
                             "或在参数里给 resume_pdf_path")
        state = asyncio.run(run_layer1(
            resume_pdf_path=resume,
            site_name=job.site_name,
            job_url=job.url,
            headless=bool(overrides.get("headless") or False),
            tracker=self._st.tracker,
            emitter=getattr(self._st, "emitter", None),
            workflow="m2",
        ))
        outcome = state.get("open_result")
        app_id = state.get("pending_application_id")
        n_fields = len(state.get("classified_fields") or [])
        return (
            f"填表完成：表单已打开={getattr(outcome, 'form_opened', None)} "
            f"简历已上传={getattr(outcome, 'resume_uploaded', None)} "
            f"待审批字段 {n_fields} 个" + (f"（记录 id={app_id}）" if app_id else "（未写记录）"),
            {"pending_application_id": app_id, "fields": n_fields,
             "note": getattr(outcome, "note", "")},
        )

    # -- the queue runner (WorkflowQueue's runner callback) ---------------------

    def run_item(self, item) -> None:
        """Execute ONE queued workflow item (blocks until it finishes).

        Sets the emitter mutex up front (closes the race with interactive browser
        ops that only READ current_workflow), dispatches to the matching runner,
        writes a schedule-log entry, and -- because the runners clear the mutex only
        on success -- clears it here on error and re-raises so the queue records the
        failure. trigger_type is derived from where the item came from.
        """
        st = self._st
        emitter = st.emitter
        emitter.current_workflow = item.workflow

        # 'smoke'/'smoke_live' come from the regression smoke, which enqueues like any
        # other caller. Keeping the trigger distinct is what lets run_diagnostics find
        # the smoke's own runs in the log archive afterwards.
        trig_param = {"manual": "manual", "queue": "manual",
                      "scheduled": "scheduled", "selfcheck": "selfcheck",
                      "smoke": "smoke", "smoke_live": "smoke_live"}.get(item.source, "manual")
        log_trigger = {"manual": "manual", "queue": "manual",
                       "scheduled": "scheduler", "selfcheck": "selfcheck",
                       "smoke": "smoke", "smoke_live": "smoke_live"}.get(item.source, "manual")
        # 加新 workflow 时**必须**同时加这一条。它在 try 外面，漏了会在活儿干完
        # 之后炸在写日志上——结果已经产生却没落进 schedule_log，是最难查的那种。
        log_wf = {"w1": "apply", "w2": "check", "w3": "reply",
                  "m1": "ms_select", "m2": "ms_fill"}[item.workflow]
        params = {**item.params, "_trigger": trig_param}
        triggered_at = datetime.now(timezone.utc).isoformat()
        start_time = time.monotonic()
        try:
            if item.workflow == "w1":
                summary, raw = self._run_apply_workflow(params)
            elif item.workflow == "w2":
                summary, raw = self._run_check_workflow(params)
            elif item.workflow == "w3":
                summary, raw = self._run_reply_workflow(params)
            elif item.workflow == "m1":
                summary, raw = self._run_multisite_select(params)
            elif item.workflow == "m2":
                summary, raw = self._run_multisite_fill(params)
            else:
                # 以前这里是 else→w3，加了 m1/m2 之后那个兜底会把任何未知类型
                # 悄悄当成"发回复"跑掉。宁可炸。
                raise ValueError(f"unknown workflow kind: {item.workflow!r}")
            # Hand the raw counters to whoever is waiting on this item (the smoke).
            # Bounded so a long-lived server doesn't accumulate them.
            if item.source.startswith("smoke"):
                st.smoke_summaries[item.id] = raw
                if len(st.smoke_summaries) > 50:
                    st.smoke_summaries.pop(next(iter(st.smoke_summaries)))
            self._write_schedule_log({
                "workflow": log_wf, "trigger_type": log_trigger,
                "triggered_at": triggered_at, "result": "success",
                "skipped_reason": None, "summary": summary,
                "duration_seconds": round(time.monotonic() - start_time),
            })
        except Exception as exc:
            logger.exception("queue run %s failed: %s", item.workflow, exc)
            self._write_schedule_log({
                "workflow": log_wf, "trigger_type": log_trigger,
                "triggered_at": triggered_at, "result": "error",
                "skipped_reason": None, "summary": str(exc),
                "duration_seconds": round(time.monotonic() - start_time),
            })
            emitter.finish_workflow(item.workflow, f"执行失败: {exc}", status="error")
            raise
        finally:
            # Backstop the browser mutex: run_item OWNS current_workflow for this item,
            # so it must guarantee release no matter how we leave. The success path
            # (runner's finish_workflow) and the except path both already clear it;
            # this makes a future runner that returns without finishing the workflow
            # unable to wedge the queue (is_busy stuck true) the way it once did.
            emitter.current_workflow = None

    # -- self-check cycle -------------------------------------------------------

    def run_selfcheck_cycle(self, *, w1_max: int, w2_max: int,
                            with_probes: bool, trigger_type: str) -> dict:
        """One full self-check cycle: optional infra probes, then (if green) a REAL
        W1 + W2 ENQUEUED on the shared queue (source=selfcheck) so they never bypass
        it. Skipped only if the probes fail or the Boss daily cap was hit today."""
        self._ensure()
        st = self._st
        entry: dict[str, Any] = {
            "trigger_type": trigger_type,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "params": {"w1_max": w1_max, "w2_max": w2_max, "with_probes": with_probes},
            "stages": [],
        }

        # Boss daily-cap gate: skip the whole cycle once W1 hit the cap today -- its
        # point is W1 apply liveness, moot at the cap; scheduled W2 runs independently.
        if self.is_rate_limited_today():
            entry["ok"] = True
            entry["skipped_reason"] = "今日已达 Boss 沟通上限，暂停自检"
            entry["finished_at"] = datetime.now(timezone.utc).isoformat()
            self._write_selfcheck_log(entry)
            return entry

        emitter = st.emitter
        if with_probes:
            if emitter.current_workflow:
                # Something is using the single Boss browser; the probes open it too,
                # so skip them this cycle. W1/W2 are still enqueued below.
                entry["stages"].append({
                    "stage": "probes", "label": "探针", "ok": True, "duration_ms": 0,
                    "detail": "浏览器忙，本轮跳过探针（W1/W2 仍入队）",
                })
            else:
                from services import selfcheck
                # Hold the browser mutex so the queue worker doesn't start a run while
                # the probe has the browser open.
                emitter.current_workflow = "selfcheck"
                try:
                    rep = selfcheck.run_probes(
                        data_dir=self._data_dir, tracker=st.tracker,
                        model_router=st.model_router,
                    )
                finally:
                    emitter.current_workflow = None
                for pr in rep.get("probes", []):
                    entry["stages"].append({
                        "stage": pr["name"], "label": pr["label"], "ok": pr["ok"],
                        "duration_ms": pr["duration_ms"], "detail": pr["detail"],
                    })
                if not rep.get("ok"):
                    entry["ok"] = False
                    entry["skipped_reason"] = "探针未通过，跳过真跑"
                    entry["finished_at"] = datetime.now(timezone.utc).isoformat()
                    self._write_selfcheck_log(entry)
                    return entry

        # Unified scheduling: enqueue the real W1/W2 on the shared queue rather than
        # running inline. A self-check that fires while something else runs queues
        # behind it; each run's outcome lands in the schedule log / queue history.
        q = st.workflow_queue
        it1 = q.enqueue("w1", {"max_cards": w1_max, "dry_run": False}, source="selfcheck", coalesce=True)
        it2 = q.enqueue("w2", {"max_conversations": w2_max, "dry_run": False}, source="selfcheck", coalesce=True)
        entry["stages"].append({
            "stage": "enqueue", "label": "W1/W2 入队", "ok": True, "duration_ms": 0,
            "detail": f"已排入队列顺序执行（w1={it1.id} · w2={it2.id}）",
        })
        entry["ok"] = True
        entry["finished_at"] = datetime.now(timezone.utc).isoformat()
        self._write_selfcheck_log(entry)
        logger.info("selfcheck cycle done: ok=%s stages=%s", entry["ok"],
                    [f"{s['stage']}={'ok' if s['ok'] else 'FAIL'}" for s in entry["stages"]])
        return entry

    # -- regression smoke -------------------------------------------------------

    def submit_and_wait(self, workflow: str, params: dict) -> dict:
        """Enqueue ONE workflow with source='smoke' and block until it finishes.

        This is the `submit` the smoke injects, so its runs go through the same queue
        path as manual/scheduled ones. Returns the runner's summary dict, or a dict
        with an "error" key -- run_smoke treats `error` as a failed check.
        """
        st = self._st
        q = st.workflow_queue
        # `trigger` is not a runner kwarg here: the queue derives it from `source`.
        params = dict(params)
        source = params.pop("trigger", "smoke")
        item = q.enqueue(workflow, params, source=source)

        deadline = time.monotonic() + self._submit_timeout
        while time.monotonic() < deadline:
            snap = q.snapshot()
            done = next((i for i in snap["recent"] if i["id"] == item.id), None)
            if done is not None:
                if done.get("status") == "error":
                    return {"error": done.get("error") or "queue item failed"}
                return st.smoke_summaries.get(item.id) or {}
            pending = any(i["id"] == item.id for i in snap["pending"])
            running = (snap.get("current") or {}).get("id") == item.id
            if not pending and not running:
                return {"error": "queue item disappeared"}
            time.sleep(1.0)
        return {"error": f"queue item timed out after {self._submit_timeout}s"}

    def run_regression_smoke(self, dry_run: bool = True, w1_max: int = 2, w2_max: int = 5,
                             score_threshold: int | None = None,
                             no_response_days: int | None = None,
                             stale_conv_days: int | None = None) -> None:
        """Background: real-machine smoke (W1+W2 tiny scale), run THROUGH THE QUEUE
        (source='smoke') so it shares the single execution path. Must NOT set
        emitter.current_workflow itself -- that flag is the queue's is_busy signal,
        so holding it would deadlock the worker it waits on. Appends the report to
        the smoke log for the dashboard to poll."""
        import json as _json
        self._ensure()
        from services import regression
        try:
            report = regression.run_smoke(
                submit=self.submit_and_wait, tracker=self._st.tracker,
                dry_run=dry_run, w1_max=w1_max, w2_max=w2_max,
                score_threshold=score_threshold, no_response_days=no_response_days,
                stale_conv_days=stale_conv_days,
            )
        except Exception as exc:
            report = {"ran_at": datetime.now(timezone.utc).isoformat(), "ok": False,
                      "mode": "dry" if dry_run else "live",
                      "duration_s": 0, "checks": [], "error": f"{type(exc).__name__}: {exc}"}
        try:
            with open(self._smoke_log_path, "a", encoding="utf-8") as f:
                f.write(_json.dumps(report, ensure_ascii=False) + "\n")
        except OSError:
            pass
        logger.info("regression smoke: ok=%s %ss", report.get("ok"), report.get("duration_s"))
