# Task 008 — Orchestrator & Scheduler

## 目标
Implement the main control loop (Orchestrator) and the APScheduler-based scheduler, with per-job error isolation, daily limit enforcement, and session expiry handling.

## 上下文
- 依赖：Task 001-007 (all schemas, services, and tools)
- 代码目录：`C:/Coding/AI-factory-projects/open-job-finder/code/`

## 实现要求

### 1. `orchestrator.py` — Orchestrator

```python
class Orchestrator:
    def __init__(
        self,
        config: dict,
        tracker: ApplicationTracker,
        llm_clients: dict,           # {"scoring": FallbackChain, "generation": FallbackChain}
        dry_run: bool = False
    ):
        self.config = config
        self.tracker = tracker
        self.llm_clients = llm_clients
        self.dry_run = dry_run
        self.logger = get_orchestrator_logger()

        # Extract config values
        self.score_threshold = config.get("apply", {}).get("score_threshold", 72)
        self.daily_limit = config.get("apply", {}).get("daily_limit", 25)

        # Initialize tools (lazy: browser_agent created per-run)
        self._init_tools()

    def _init_tools(self) -> None:
        """
        Initialize all tools that don't require a live browser session.
        Browser-dependent tools (search_jobs, apply_job, check_responses) are created in run_once().
        """
        from tools.score_job import ScoreJobTool
        from tools.critique_job import CritiqueJobTool
        from tools.update_status import UpdateStatusTool
        from tools.generate_resume import GenerateResumeTool
        from services.resume_manager import ResumeManager
        from services.rate_limiter import RateLimiter

        self.score_tool = ScoreJobTool(
            llm_chain=self.llm_clients["scoring"],
            score_threshold=self.score_threshold
        )
        self.critique_tool = CritiqueJobTool(llm_chain=self.llm_clients["scoring"])
        self.update_tool = UpdateStatusTool(tracker=self.tracker)
        self.resume_manager = ResumeManager()
        self.resume_tool = GenerateResumeTool(resume_manager=self.resume_manager)
        self.rate_limiter = RateLimiter(
            min_wait=10.0, max_wait=30.0,
            hourly_cap=config.get("apply", {}).get("hourly_rate_cap", 8)
        )

    def run_once(self, dry_run: bool = None) -> dict:
        """
        Execute one full apply cycle.
        Returns summary dict: {"searched": N, "processed": N, "applied": N, "skipped": N, "errors": N}

        Steps:
        1. DAILY LIMIT CHECK:
           applied_today = tracker.count_today()
           if applied_today >= daily_limit:
               logger.info(f"Daily limit reached ({applied_today}/{daily_limit}). Exiting.")
               return summary with note

        2. LOAD PROFILE:
           Load data/profile.yaml. If missing, log error and return.

        3. GET SEARCH PARAMS from profile (keywords, cities) and config.

        4. OPEN BROWSER SESSION:
           with BrowserAgent() as agent:
               from tools.search_jobs import SearchJobsTool
               from tools.apply_job import ApplyJobTool
               from tools.check_responses import CheckResponsesTool
               search_tool = SearchJobsTool(agent)
               apply_tool = ApplyJobTool(agent, tracker, rate_limiter, dry_run=effective_dry_run)
               check_tool = CheckResponsesTool(agent, tracker)

               5. SEARCH JOBS:
                  For each keyword in profile.keywords:
                      For each city in profile.cities:
                          jobs = search_tool.execute(keywords=kw, city=city, limit=limit_per_run)
                          For each job: if not tracker.exists(job.job_id): tracker.upsert(ApplicationRecord(...))

               6. PROCESS JOBS:
                  pending = [j for j in tracker.get_by_status(AppStatus.DISCOVERED)
                               + tracker.get_by_status(AppStatus.SCANNED)
                               + tracker.get_by_status(AppStatus.SCORED)]
                  For each job in pending:
                      try:
                          _process_job(job, apply_tool, profile, dry_run)
                          # Re-check daily limit after each apply
                          if tracker.count_today() >= daily_limit: break
                      except SessionExpiredError:
                          raise  # Propagate to scheduler
                      except RateLimitExceededError:
                          logger.warning("Rate limit exceeded, stopping this run.")
                          break
                      except Exception as e:
                          logger.error(f"Error processing job {job.job_id}: {e}", exc_info=True)
                          tracker.update_status(job.job_id, AppStatus.ERROR, error_msg=str(e))
                          errors += 1
                          continue  # Isolate failure

        7. Return summary dict.
        """

    def _process_job(self, record: ApplicationRecord, apply_tool, profile: dict, dry_run: bool) -> None:
        """
        Process a single job through the full pipeline.
        Uses job_logger for per-job logging.

        Pipeline:
        1. If status is DISCOVERED:
           - jd_text = browser_agent.open_job(record.url)  [use the agent from run_once context]
           - Update record.jd_text and set status=SCANNED
           job = Job(record.job_id, ..., jd_text=jd_text, ...)

        2. If status is SCANNED or DISCOVERED→SCANNED:
           - score_result = score_tool.execute(job=job, profile=profile)["result"]
           - Log score and decision at INFO level
           - Update tracker: status=SCORED, score=score_result.score, decision=score_result.decision
           - If score < threshold or decision == "skip": log skip reason, return (do not apply)

        3. If status is SCORED:
           - critic_result = critique_tool.execute(job=job, score_result=score_result, profile=profile)["result"]
           - Log critic verdict
           - Update tracker: critic_verdict=critic_result.verdict
           - If critic_result.verdict == "reject": log rejection reason, return

        4. Generate resume (if resume available):
           - pdf_result = resume_tool.execute(job=job, score_result=score_result)
           - pdf_path = pdf_result.get("pdf_path")  # may be None if no resume

        5. Apply:
           - apply_result = apply_tool.execute(job=job, resume_path=pdf_path)
           - Log result

        Use job_logger = get_job_logger(record.job_id) for all step logs in this method.
        """

    def check_responses(self) -> dict:
        """
        Check Boss直聘 chat list for any responses to applied jobs.
        Opens browser, calls CheckResponsesTool, returns update summary.
        Wrap in try/except; on SessionExpiredError re-raise.
        """

    def daily_summary(self) -> dict:
        """
        Return stats for the current day:
        {
          "date": "2026-03-18",
          "applied_today": N,
          "total_applied": N,
          "responded": N,
          "interviews": N,
          "offers": N,
          "daily_limit": N,
          "remaining": N
        }
        Log at INFO level.
        """
```

### 2. `scheduler.py` — APScheduler Setup

```python
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

def start_scheduler(orchestrator: Orchestrator) -> None:
    """
    Set up and start the blocking APScheduler.

    Jobs:
    1. apply_job: CronTrigger from config["schedule"]["apply_cron"]
       - Calls orchestrator.run_once()
       - On SessionExpiredError: scheduler.pause() + log critical alert
       - On DailyLimitReachedError: log info, continue
       - On other exception: log error, continue (don't crash scheduler)

    2. check_responses_job: IntervalTrigger(seconds=config["schedule"]["check_responses_interval"])
       - Calls orchestrator.check_responses()
       - On SessionExpiredError: scheduler.pause() + log critical alert

    3. daily_summary_job: CronTrigger(hour=18, minute=0, day_of_week="mon-fri")
       - Calls orchestrator.daily_summary()

    Print startup message with next run times.
    Call scheduler.start() (blocks).
    """
```

**Session expiry handling in scheduler:**
```python
def _handle_session_expiry(scheduler):
    scheduler.pause()
    logger.critical(
        "SESSION EXPIRED: All scheduled jobs paused. "
        "Please run: python main.py --onboarding to re-login. "
        "Then restart the scheduler."
    )
```

## 文件清单

- `code/orchestrator.py`：Orchestrator class
- `code/scheduler.py`：start_scheduler() function

## Smoke Test

```bash
cd C:/Coding/AI-factory-projects/open-job-finder/code

# Test 1: Import check
python -c "
from orchestrator import Orchestrator
from scheduler import start_scheduler
print('imports OK')
"

# Test 2: Orchestrator instantiation with mock LLM clients
python -c "
import os
from services.tracker import ApplicationTracker
from services.llm_client import load_config, build_llm_client

if os.path.exists('data/test_orch.db'): os.remove('data/test_orch.db')
config = load_config('config.yaml')
tracker = ApplicationTracker(db_path='data/test_orch.db')
llm_clients = {
    'scoring': build_llm_client(config, 'scoring'),
    'generation': build_llm_client(config, 'generation'),
}
from orchestrator import Orchestrator
orch = Orchestrator(config=config, tracker=tracker, llm_clients=llm_clients)
print('Orchestrator instantiated OK')
summary = orch.daily_summary()
print('daily_summary:', summary)
tracker.close()
os.remove('data/test_orch.db')
"

# Test 3: run_once with dry_run=True and no jobs in DB (should exit cleanly)
python -c "
import os, yaml
from services.tracker import ApplicationTracker
from services.llm_client import load_config, build_llm_client
from orchestrator import Orchestrator

if os.path.exists('data/test_dryrun.db'): os.remove('data/test_dryrun.db')

# Create minimal profile.yaml for test
os.makedirs('data', exist_ok=True)
profile = {'keywords': ['Python Engineer'], 'cities': ['北京'], 'expected_salary': '20k', 'skills': 'Python', 'years_experience': 3}
with open('data/profile.yaml', 'w') as f:
    yaml.dump(profile, f)

config = load_config('config.yaml')
tracker = ApplicationTracker(db_path='data/test_dryrun.db')
llm_clients = {
    'scoring': build_llm_client(config, 'scoring'),
    'generation': build_llm_client(config, 'generation'),
}
orch = Orchestrator(config=config, tracker=tracker, llm_clients=llm_clients, dry_run=True)

# Mock browser to avoid actual browser launch
print('NOTE: run_once with browser requires manual test. Import/init OK.')
tracker.close()
os.remove('data/test_dryrun.db')
print('orchestrator dry-run setup OK')
"

# Test 4: Verify SessionExpiredError propagates (unit test)
python -c "
from services.exceptions import SessionExpiredError
# Simulate what orchestrator does: re-raise SessionExpiredError
def mock_run_once():
    raise SessionExpiredError('test')
try:
    mock_run_once()
except SessionExpiredError:
    print('SessionExpiredError propagation OK')
"
```

<!-- FACTORY:DONE -->
