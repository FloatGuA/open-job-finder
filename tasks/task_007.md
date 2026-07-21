# Task 007 — Apply Tool, Search Tool Extensions & Onboarding

## 目标
Implement ApplyJobTool with idempotency + rate limiting, CheckResponsesTool, and the onboarding service for first-run setup guidance.

## 上下文
- 依赖：Task 001 (schemas.py, services/exceptions.py, services/rate_limiter.py, services/logger.py), Task 002 (services/tracker.py), Task 005 (services/browser_agent.py)
- 代码目录：`C:/Coding/AI-factory-projects/open-job-finder/code/`

## 实现要求

### 1. `tools/apply_job.py` — ApplyJobTool

```python
class ApplyJobTool:
    name = "apply_job"
    description = "Apply to a job on Boss直聘 with idempotency guard and rate limiting."

    def __init__(
        self,
        browser_agent: BrowserAgent,
        tracker: ApplicationTracker,
        rate_limiter: RateLimiter,
        dry_run: bool = False
    ):
        ...

    def execute(self, job: Job, resume_path: str = None, dry_run: bool = None) -> dict:
        """
        dry_run: if None, use self.dry_run; otherwise override for this call.

        Steps:
        1. IDEMPOTENCY CHECK: if tracker.has_action(job.job_id, "apply_attempted"):
           Return {"success": False, "message": "Already attempted, skipping.", "skipped": True}

        2. MARK ATTEMPTED (before actual apply, so crash doesn't cause re-apply):
           tracker.mark_action(job.job_id, "apply_attempted")
           tracker.update_status(job.job_id, AppStatus.SCORED,
               apply_attempted=True)  # keep SCORED status, just set flag

        3. DRY RUN CHECK: if effective_dry_run:
           Log: "[DRY RUN] Would apply to {job.title} at {job.company}"
           Return {"success": True, "message": "dry_run: skipped", "dry_run": True}

        4. RATE LIMIT: call rate_limiter.wait()
           On RateLimitExceededError: re-raise (orchestrator handles)

        5. APPLY: success = browser_agent.apply(job, resume_path)

        6. UPDATE STATUS:
           if success:
               tracker.update_status(job.job_id, AppStatus.APPLIED,
                   applied_at=datetime.utcnow().isoformat())
               Return {"success": True, "message": f"Applied to {job.title}"}
           else:
               tracker.update_status(job.job_id, AppStatus.ERROR,
                   error_msg="apply() returned False")
               Return {"success": False, "message": "Apply failed (button not found)"}

        7. On any unexpected exception:
           tracker.update_status(job.job_id, AppStatus.ERROR, error_msg=str(e))
           Re-raise.
        """
```

### 2. `tools/check_responses.py` — CheckResponsesTool

```python
class CheckResponsesTool:
    name = "check_responses"
    description = "Check Boss直聘 chat list for responses to submitted applications."

    def __init__(self, browser_agent: BrowserAgent, tracker: ApplicationTracker):
        ...

    def execute(self) -> dict:
        """
        1. Get StatusUpdate list from browser_agent.check_chat_list().
        2. For each update:
           a. Look up job in tracker by matching company name or job_id.
           b. If found and current status is APPLIED or RESPONDED:
              tracker.update_status(job_id, AppStatus(update.new_status),
                  responded_at=update.updated_at)
        3. Return {
             "checked": int (total updates from chat),
             "updated": int (records actually updated in tracker),
             "updates": [{"job_id": ..., "new_status": ..., "company": ...}]
           }
        On SessionExpiredError: re-raise.
        On other errors: log and return {"checked": 0, "updated": 0, "updates": [], "error": str(e)}.
        """
```

### 3. `services/onboarding.py` — Onboarding Service

Handles first-run detection and CLI-guided setup. Called at system startup before scheduler launches.

```python
class OnboardingChecker:
    def __init__(
        self,
        profile_path: str = "data/profile.yaml",
        resume_yaml_path: str = "data/resume_base.yaml",
        session_path: str = "data/session.json",
        config: dict = None
    ):
        ...

    def check_all(self) -> dict:
        """
        Run all checks and return status dict:
        {
          "profile": bool,        # data/profile.yaml exists and non-empty
          "resume": bool,         # data/resume_base.yaml exists and non-empty
          "session": bool,        # data/session.json exists
          "llm_provider": bool,   # at least one provider is_available()
          "all_ok": bool          # all four are True
        }
        """

    def run_interactive_setup(self) -> None:
        """
        For each failed check, guide the user interactively:

        1. PROFILE MISSING:
           Print: "No profile found. Let's set up your job search preferences."
           Ask questions via input():
             - "Enter job keywords (comma-separated, e.g. Python后端工程师): "
             - "Enter target cities (comma-separated, e.g. 北京,上海): "
             - "Enter expected salary range (e.g. 20-35k): "
             - "Describe your top skills (e.g. Python, FastAPI, PostgreSQL): "
             - "Years of experience: "
           Save to data/profile.yaml.

        2. RESUME MISSING:
           Print: "No resume found. Please upload your resume via the Dashboard."
           Print: "Dashboard URL: http://localhost:{config.get('dashboard', {}).get('port', 8765)}"
           Print: "Or place your Boss直聘 exported PDF/Word at: data/resume_raw.[pdf|docx]"
           Print: "Proceeding without resume — apply operations will be blocked."
           (Do NOT block — just warn)

        3. SESSION MISSING:
           Print: "No browser session found. You need to log in to Boss直聘 manually."
           Ask: "Launch browser for manual login now? (y/n): "
           If y: instantiate BrowserAgent and call login_interactive().
           If n: print warning and continue.

        4. LLM PROVIDER UNAVAILABLE:
           Print: "Warning: No LLM provider is currently available."
           Print current config's provider list.
           Print: "Please check your config.yaml llm.providers section."
           (Do NOT block — jobs can still be discovered and tracked)
        """

    def get_status(self) -> dict:
        """Alias for check_all(). Used by Dashboard API."""

    def _create_default_profile(self, keywords: list, cities: list, salary: str,
                                  skills: str, years: str) -> None:
        """Write data/profile.yaml with provided values."""
```

**`data/profile.yaml` structure:**
```yaml
# Job search preferences
keywords:
  - "Python 后端工程师"
cities:
  - "北京"
expected_salary: "20-35k"
skills: "Python, FastAPI, PostgreSQL, Redis"
years_experience: 3
notes: ""
```

### 4. Entry Point — `main.py`

Create a simple CLI entry point at the root of the code directory:

```python
#!/usr/bin/env python3
"""
OpenJobFinder — Main entry point.
Usage:
  python main.py                # Start scheduler (default)
  python main.py --once         # Run one apply cycle immediately
  python main.py --check        # Check responses only
  python main.py --onboarding   # Run onboarding setup
  python main.py --dry-run      # Run once in dry-run mode
"""
import argparse
import sys
from services.llm_client import load_config, build_llm_client
from services.tracker import ApplicationTracker
from services.onboarding import OnboardingChecker
from services.logger import get_orchestrator_logger

def main():
    parser = argparse.ArgumentParser(description="OpenJobFinder")
    parser.add_argument("--once", action="store_true", help="Run one apply cycle")
    parser.add_argument("--check", action="store_true", help="Check responses only")
    parser.add_argument("--onboarding", action="store_true", help="Run onboarding setup")
    parser.add_argument("--dry-run", action="store_true", help="Dry run mode")
    args = parser.parse_args()

    logger = get_orchestrator_logger()
    config = load_config("config.yaml")

    # Onboarding check
    checker = OnboardingChecker(config=config)
    status = checker.check_all()

    if args.onboarding or not status["profile"]:
        checker.run_interactive_setup()
        status = checker.check_all()

    if not status["all_ok"]:
        logger.warning(f"Onboarding incomplete: {status}")

    # Import here to avoid circular imports at module load time
    from orchestrator import Orchestrator
    from scheduler import start_scheduler

    tracker = ApplicationTracker()
    llm_clients = {
        "scoring": build_llm_client(config, "scoring"),
        "generation": build_llm_client(config, "generation"),
    }

    orchestrator = Orchestrator(config=config, tracker=tracker, llm_clients=llm_clients)

    if args.once or args.dry_run:
        dry_run = args.dry_run or config.get("apply", {}).get("dry_run", False)
        orchestrator.run_once(dry_run=dry_run)
    elif args.check:
        orchestrator.check_responses()
    else:
        start_scheduler(orchestrator)

if __name__ == "__main__":
    main()
```

## 文件清单

- `code/tools/apply_job.py`：ApplyJobTool
- `code/tools/check_responses.py`：CheckResponsesTool
- `code/services/onboarding.py`：OnboardingChecker
- `code/main.py`：CLI entry point

## Smoke Test

```bash
cd C:/Coding/AI-factory-projects/open-job-finder/code

# Test 1: Imports
python -c "
from tools.apply_job import ApplyJobTool
from tools.check_responses import CheckResponsesTool
from services.onboarding import OnboardingChecker
print('imports OK')
"

# Test 2: ApplyJobTool dry run (idempotency + dry run without browser)
python -c "
import datetime, os
from schemas import Job, AppStatus, ApplicationRecord
from services.tracker import ApplicationTracker
from services.rate_limiter import RateLimiter
from tools.apply_job import ApplyJobTool

if os.path.exists('data/test_apply.db'): os.remove('data/test_apply.db')
tracker = ApplicationTracker(db_path='data/test_apply.db')
now = datetime.datetime.utcnow().isoformat()
job = Job(
    job_id='j_apply_test', title='Python Dev', company='TestCo',
    city='Beijing', salary='20k', url='https://example.com',
    jd_text='test jd', source_keyword='python',
    discovered_at=now, status='SCORED'
)
tracker.upsert(ApplicationRecord(
    job_id=job.job_id, title=job.title, company=job.company,
    url=job.url, status='SCORED', created_at=now, updated_at=now
))

tool = ApplyJobTool(
    browser_agent=None,  # not needed for dry run
    tracker=tracker,
    rate_limiter=RateLimiter(min_wait=0, max_wait=0),
    dry_run=True
)
result = tool.execute(job=job)
assert result['dry_run'] == True, f'Expected dry_run=True, got {result}'
print('dry_run result:', result)

# Test idempotency: second call should be skipped
result2 = tool.execute(job=job)
assert result2.get('skipped') == True, f'Expected skipped=True, got {result2}'
print('idempotency OK:', result2)

tracker.close()
os.remove('data/test_apply.db')
"

# Test 3: OnboardingChecker.check_all()
python -c "
from services.onboarding import OnboardingChecker
checker = OnboardingChecker()
status = checker.check_all()
print('onboarding status:', status)
print('onboarding check_all OK')
"

# Test 4: main.py --help
python main.py --help
```

<!-- FACTORY:DONE -->
