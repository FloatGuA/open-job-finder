# Task 001 — Schemas, Protocols & Foundation Services

## 目标
Define all shared data schemas, abstract service protocols, and foundational utility services (logger, retry, rate limiter, LLM parser) that every subsequent task will depend on.

## 上下文
- 依赖：None (this is the foundation)
- 代码目录：`C:/Coding/AI-factory-projects/open-job-finder/code/`

## 实现要求

### 1. `schemas.py` — All Data Classes and Enums

Implement the following using Python `dataclasses` and `enum`. Place this file at the root of the code directory.

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

class AppStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    SCANNED    = "SCANNED"
    SCORED     = "SCORED"
    APPLIED    = "APPLIED"
    RESPONDED  = "RESPONDED"
    INTERVIEW  = "INTERVIEW"
    OFFER      = "OFFER"
    REJECTED   = "REJECTED"
    ERROR      = "ERROR"

@dataclass
class Job:
    job_id: str
    title: str
    company: str
    city: str
    salary: str
    url: str
    jd_text: str
    source_keyword: str
    discovered_at: str   # ISO8601
    status: str = AppStatus.DISCOVERED.value

@dataclass
class ScoreResult:
    job_id: str
    score: int                       # 0-100
    decision: str                    # "apply" | "skip"
    reason: str
    resume_patch: dict               # {"summary": str, "highlights": list}
    raw_response: str
    provider_used: str

@dataclass
class CriticResult:
    job_id: str
    verdict: str                     # "approve" | "reject"
    reason: str
    raw_response: str
    provider_used: str

@dataclass
class ApplicationRecord:
    job_id: str
    title: str
    company: str
    url: str
    status: str
    score: Optional[int] = None
    decision: Optional[str] = None
    critic_verdict: Optional[str] = None
    resume_path: Optional[str] = None
    applied_at: Optional[str] = None
    responded_at: Optional[str] = None
    error_msg: Optional[str] = None
    apply_attempted: bool = False
    created_at: str = ""
    updated_at: str = ""

@dataclass
class StatusUpdate:
    job_id: str
    company: str
    new_status: str
    message: str
    updated_at: str
```

### 2. `protocols.py` — Abstract Service Interfaces

Use `typing.Protocol` with `runtime_checkable`. These allow downstream modules to type-hint against interfaces without circular imports.

```python
from typing import Protocol, runtime_checkable, List
# Import schemas as needed

@runtime_checkable
class LLMProviderProtocol(Protocol):
    name: str
    def is_available(self) -> bool: ...
    def complete(self, prompt: str, system: str = "") -> str: ...

@runtime_checkable
class TrackerProtocol(Protocol):
    def exists(self, job_id: str) -> bool: ...
    def upsert(self, record: ApplicationRecord) -> None: ...
    def count_today(self) -> int: ...
    def get_all(self) -> List[ApplicationRecord]: ...
    def get_pending_responses(self) -> List[ApplicationRecord]: ...
    def has_action(self, job_id: str, action: str) -> bool: ...
    def mark_action(self, job_id: str, action: str) -> None: ...

@runtime_checkable
class BrowserAgentProtocol(Protocol):
    def search(self, keywords: str, city: str, limit: int) -> List[Job]: ...
    def open_job(self, url: str) -> str: ...
    def apply(self, job: Job, resume_path: str) -> bool: ...
    def check_chat_list(self) -> List[StatusUpdate]: ...

@runtime_checkable
class ToolProtocol(Protocol):
    name: str
    description: str
    def execute(self, **kwargs) -> dict: ...
```

### 3. `services/logger.py` — Structured Logger

- `get_job_logger(job_id: str) -> logging.Logger`: returns a Logger that writes to `logs/jobs/{job_id}.log`. Create the directory if missing.
- `get_orchestrator_logger() -> logging.Logger`: writes to `logs/orchestrator.log`.
- Both loggers use a formatter that includes: `%(asctime)s [%(levelname)s] %(message)s`
- File handler uses `encoding="utf-8"`.
- Also attach a StreamHandler (console) at WARNING level.
- Loggers are cached by name to avoid duplicate handlers on repeated calls.

### 4. `services/retry.py` — Exponential Backoff Retry

```python
def with_retry(
    func: Callable,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    exceptions: tuple = (Exception,)
) -> Any:
    """
    Call func(). On exception, wait base_delay * (2 ** attempt) seconds and retry.
    Raise the last exception if all attempts fail.
    Log each retry attempt at WARNING level.
    """
```

Also provide a decorator version:
```python
def retry(max_attempts=3, base_delay=1.0, exceptions=(Exception,)):
    """Decorator wrapping with_retry."""
```

### 5. `services/rate_limiter.py` — Rate Limiter

```python
class RateLimiter:
    def __init__(self, min_wait: float = 10.0, max_wait: float = 30.0, hourly_cap: int = 8):
        ...

    def wait(self) -> None:
        """
        1. Check if hourly_cap has been reached in the current hour window.
           If yes, raise RateLimitExceededError.
        2. Sleep random.uniform(min_wait, max_wait) seconds.
        3. Record this call in the internal counter.
        """

    def reset(self) -> None:
        """Reset the counter (used at the start of each hour window)."""
```

- `RateLimitExceededError(Exception)`: custom exception, message includes current count and cap.
- Track calls with a list of timestamps; count only those within the last 3600 seconds.

### 6. `services/llm_parser.py` — LLM Output Parser

```python
def safe_parse_json(text: str, required_fields: dict = None) -> dict:
    """
    Three-layer parsing:
    1. Regex: extract content inside ```json ... ``` code fences.
       If not found, try to find the first {...} block.
    2. json-repair: call repair(extracted_text) if initial json.loads fails.
    3. Field coercion: apply required_fields type mapping.
       e.g., required_fields={"score": int, "decision": str}
       For missing fields, use None. For type errors, attempt cast; on failure use None.
    Returns the parsed dict. Raises LLMParseError if all layers fail.
    """

class LLMParseError(Exception):
    pass
```

- Import `json_repair` (the `json-repair` PyPI package). Handle `ImportError` gracefully (log warning, skip repair step).
- Log the original text at DEBUG level when parsing fails at each layer.

### 7. `services/exceptions.py` — Custom Exceptions

Define all project-wide custom exceptions in one file:

```python
class OpenJobFinderError(Exception): pass
class SessionExpiredError(OpenJobFinderError): pass
class RateLimitExceededError(OpenJobFinderError): pass
class LLMParseError(OpenJobFinderError): pass
class AllProvidersFailedError(OpenJobFinderError): pass
class OnboardingIncompleteError(OpenJobFinderError): pass
class DailyLimitReachedError(OpenJobFinderError): pass
```

### 8. `requirements.txt`

List all Python dependencies:
```
playwright>=1.40.0
apscheduler>=3.10.0
pyyaml>=6.0
jinja2>=3.1.0
weasyprint>=60.0
json-repair>=0.6.0
requests>=2.31.0
fastapi>=0.104.0
uvicorn>=0.24.0
python-multipart>=0.0.6
pdfminer.six>=20221105
python-docx>=1.1.0
```

### 9. `config.yaml` — Default Configuration Template

Create a well-commented default config at the root of the code directory:

```yaml
# OpenJobFinder Configuration
llm:
  providers:
    scoring:
      - type: claude_cli
      - type: anthropic_api
        model: claude-sonnet-4-6
        api_key_env: ANTHROPIC_API_KEY
    generation:
      - type: ollama
        model: llama3.2
        base_url: http://localhost:11434
      - type: claude_cli

job_search:
  keywords:
    - "Python 后端工程师"
  cities:
    - "北京"
  limit_per_run: 30

apply:
  score_threshold: 72
  daily_limit: 25
  dry_run: false

schedule:
  apply_cron: "0 9 * * 1-5"
  check_responses_interval: 3600

dashboard:
  port: 8765
```

## 文件清单

- `code/schemas.py`：所有 dataclass + AppStatus enum
- `code/protocols.py`：所有 Protocol 抽象接口
- `code/services/__init__.py`：空文件
- `code/services/exceptions.py`：所有自定义异常
- `code/services/logger.py`：job-level + orchestrator-level logger
- `code/services/retry.py`：with_retry() + retry decorator
- `code/services/rate_limiter.py`：RateLimiter class
- `code/services/llm_parser.py`：safe_parse_json()
- `code/requirements.txt`：依赖清单
- `code/config.yaml`：默认配置模板

## Smoke Test

```bash
cd C:/Coding/AI-factory-projects/open-job-finder/code

# 1. Verify schemas import cleanly
python -c "from schemas import Job, ScoreResult, CriticResult, ApplicationRecord, StatusUpdate, AppStatus; print('schemas OK')"

# 2. Verify protocols import
python -c "from protocols import LLMProviderProtocol, TrackerProtocol, ToolProtocol; print('protocols OK')"

# 3. Test retry (should retry 3x then raise)
python -c "
from services.retry import with_retry
attempts = []
def fail(): attempts.append(1); raise ValueError('test')
try: with_retry(fail, max_attempts=3, base_delay=0.01)
except ValueError: pass
assert len(attempts) == 3, f'Expected 3 attempts, got {len(attempts)}'
print('retry OK')
"

# 4. Test rate limiter
python -c "
from services.rate_limiter import RateLimiter
rl = RateLimiter(min_wait=0.0, max_wait=0.01, hourly_cap=3)
rl.wait(); rl.wait(); rl.wait()
try: rl.wait(); assert False, 'Should have raised'
except Exception as e: print('rate_limiter OK:', e)
"

# 5. Test llm_parser
python -c "
from services.llm_parser import safe_parse_json
result = safe_parse_json('\`\`\`json\n{\"score\": \"85\", \"decision\": \"apply\"}\n\`\`\`', required_fields={'score': int})
assert result['score'] == 85
print('llm_parser OK, score coerced to int:', result['score'])
"
```

<!-- FACTORY:DONE -->
