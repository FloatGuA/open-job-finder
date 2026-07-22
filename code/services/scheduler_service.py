"""APScheduler ownership, extracted from dashboard/server.py.

server.py had grown a full scheduler inside the "wiring" layer: building cron /
interval jobs, the scheduled entrypoints, and the _scheduler global + its lock.
That is orchestration, not HTTP wiring, so it lives here.

The scheduler is a CONSUMER of orchestration it does not own -- it enqueues work,
checks the Boss daily-cap gate, runs the self-check cycle, and writes the schedule
log. Those cross-cutting pieces are INJECTED as callables rather than imported, so
this module has no dependency on app.state or on server.py's globals and can be
constructed (and tested) with fakes.

Schedule config load/save stays in server.py: seven endpoints read it, so it is
shared infrastructure rather than scheduler-private. It is passed in as load_config.
"""
import logging
import threading
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)


class SchedulerService:
    """Owns the BackgroundScheduler lifecycle and the scheduled entrypoints.

    Injected dependencies (all cross-cutting, none owned by the scheduler):
      load_config()            -> dict   current schedule config
      get_last_run_time(wf)    -> datetime|None   for interval restore across restarts
      enqueue(wf, params, source, coalesce)   put a run on the queue
      rate_limited_today()     -> bool   Boss daily-cap gate (apply only)
      run_selfcheck(w1_max, w2_max, with_probes, trigger_type)   the self-check cycle
      write_schedule_log(entry)          append a schedule-log line
    """

    def __init__(
        self,
        *,
        load_config: Callable[[], dict],
        get_last_run_time: Callable[[str], object],
        enqueue: Callable[..., object],
        rate_limited_today: Callable[[], bool],
        run_selfcheck: Callable[..., object],
        write_schedule_log: Callable[[dict], None],
    ) -> None:
        self._load_config = load_config
        self._get_last_run_time = get_last_run_time
        self._enqueue = enqueue
        self._rate_limited_today = rate_limited_today
        self._run_selfcheck = run_selfcheck
        self._write_schedule_log = write_schedule_log
        self._scheduler: Optional[BackgroundScheduler] = None
        self._lock = threading.Lock()

    # -- scheduled entrypoints (called by APScheduler on a background thread) ----

    def _scheduled_run(self, workflow: str) -> None:
        """Enqueue a scheduled workflow run (coalescing duplicates).

        The single queue worker serialises this with manual / other scheduled runs,
        so a tick that lands while something else runs waits its turn rather than
        being dropped.
        """
        from datetime import datetime, timezone

        triggered_at = datetime.now(timezone.utc).isoformat()

        # Boss daily-cap gate: once W1 hit the cap today, pause scheduled apply until
        # the China date rolls over. W2 'check' is unaffected -- it sends no greetings.
        if workflow == "apply" and self._rate_limited_today():
            self._write_schedule_log({
                "workflow": workflow,
                "trigger_type": "scheduler",
                "triggered_at": triggered_at,
                "result": "skipped",
                "skipped_reason": "今日已达 Boss 沟通上限，暂停定时投递",
                "summary": None,
                "duration_seconds": 0,
            })
            logger.info("Scheduled apply skipped: Boss daily cap reached today")
            return

        wf = {"apply": "w1", "check": "w2"}[workflow]
        cfg = self._load_config()
        params = {**cfg.get(workflow, {}).get("params", {})}
        self._enqueue(wf, params, source="scheduled", coalesce=True)
        logger.info("Scheduled %s enqueued", workflow)

    def _scheduled_selfcheck(self) -> None:
        """APScheduler entry for the recurring full self-check cycle (live config)."""
        sc = self._load_config().get("selfcheck", {})
        self._run_selfcheck(
            w1_max=int(sc.get("w1_max", 10)),
            w2_max=int(sc.get("w2_max", 300)),
            with_probes=bool(sc.get("with_probes", True)),
            trigger_type="scheduler",
        )

    # -- lifecycle --------------------------------------------------------------

    def _build(self, cfg: dict, restore_interval_times: bool) -> BackgroundScheduler:
        import pytz

        tz = pytz.timezone("Asia/Shanghai")
        sched = BackgroundScheduler(timezone=tz)

        for workflow in ("apply", "check"):
            workflow_cfg = cfg.get(workflow, {})
            cron_enabled = bool(workflow_cfg.get("enabled", False))
            interval_enabled = bool(workflow_cfg.get("interval_enabled", False))
            interval_minutes = int(workflow_cfg.get("interval_minutes", 0))

            if cron_enabled:
                for time_str in workflow_cfg.get("times", []):
                    try:
                        hour, minute = map(int, time_str.split(":"))
                        sched.add_job(
                            self._scheduled_run,
                            CronTrigger(hour=hour, minute=minute, timezone=tz),
                            args=[workflow],
                            id=f"{workflow}_cron_{time_str.replace(':', '')}",
                            replace_existing=True,
                        )
                    except (ValueError, TypeError):
                        logger.warning("Invalid schedule time %r for %s", time_str, workflow)

            if interval_enabled and interval_minutes > 0:
                start_date = self._get_last_run_time(workflow) if restore_interval_times else None
                sched.add_job(
                    self._scheduled_run,
                    IntervalTrigger(minutes=interval_minutes, timezone=tz, start_date=start_date),
                    args=[workflow],
                    id=f"{workflow}_interval",
                    replace_existing=True,
                )

        sc = cfg.get("selfcheck", {})
        if bool(sc.get("enabled", False)) and int(sc.get("interval_minutes", 0)) > 0:
            sched.add_job(
                self._scheduled_selfcheck,
                IntervalTrigger(minutes=int(sc["interval_minutes"]), timezone=tz),
                id="selfcheck_interval",
                replace_existing=True,
            )

        return sched

    def rebuild(self, cfg: dict, restore_interval_times: bool = False) -> None:
        """Stop the existing scheduler (if any), build and start a fresh one.

        restore_interval_times: continue interval timers from the last run log across
        restarts (startup); False starts them from now (a user save).
        """
        with self._lock:
            if self._scheduler is not None and self._scheduler.running:
                self._scheduler.shutdown(wait=False)
            self._scheduler = self._build(cfg, restore_interval_times)
            self._scheduler.start()
            logger.info("Scheduler started with %d jobs", len(self._scheduler.get_jobs()))

    def shutdown(self) -> None:
        with self._lock:
            if self._scheduler is not None and self._scheduler.running:
                self._scheduler.shutdown(wait=False)

    def next_run_times(self) -> dict:
        """Next fire time per workflow, split by cron vs interval, for /api/schedule.

        Returns {running, cron: {apply, check}, interval: {apply, check}} with ISO
        strings or None. Reading the live job list is the scheduler's business, so
        the endpoint asks the service instead of reaching into its internals.
        """
        cron: dict = {"apply": None, "check": None}
        interval: dict = {"apply": None, "check": None}
        with self._lock:
            sched = self._scheduler
        running = bool(sched and sched.running)
        if running:
            for job in sched.get_jobs():
                workflow = job.id.split("_")[0]
                nrt = job.next_run_time
                nrs = nrt.isoformat() if nrt else None
                if not nrs:
                    continue
                if "_interval" in job.id:
                    interval[workflow] = nrs
                else:
                    existing = cron.get(workflow)
                    if existing is None or nrs < existing:
                        cron[workflow] = nrs
        return {"running": running, "cron": cron, "interval": interval}
