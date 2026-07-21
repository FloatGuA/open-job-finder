# Task 004 — Tool Registry & Intelligence Tools

## 目标
Implement the Tool Registry and all intelligence tools: ScoreJobTool, CritiqueJobTool, and UpdateStatusTool, with their LLM prompt templates.

## 上下文
- 依赖：Task 001 (schemas.py, protocols.py, services/llm_parser.py, services/exceptions.py), Task 002 (services/tracker.py), Task 003 (services/llm_client.py)
- 代码目录：`C:/Coding/AI-factory-projects/open-job-finder/code/`

## 实现要求

### 1. `tools/__init__.py`

Empty file.

### 2. `tools/registry.py` — Tool Registry

```python
# Global tool registry
TOOLS: dict[str, ToolProtocol] = {}

def register_tool(tool: ToolProtocol) -> None:
    """Register a tool instance by its name."""
    TOOLS[tool.name] = tool

def get_tool(name: str) -> ToolProtocol:
    """
    Return the tool with the given name.
    Raise KeyError with a helpful message if not found.
    """

def list_tools() -> List[str]:
    """Return sorted list of registered tool names."""

def initialize_tools(config: dict, tracker, llm_clients: dict) -> None:
    """
    Instantiate and register all tools.
    Called once at startup after config and services are initialized.

    Parameters:
      config: parsed config.yaml
      tracker: ApplicationTracker instance
      llm_clients: dict like {"scoring": FallbackChain, "generation": FallbackChain}

    Registers: score_job, critique_job, update_status
    (search_jobs, apply_job, generate_resume, check_responses registered in their own tasks)
    """
```

### 3. `tools/score_job.py` — ScoreJobTool

```python
class ScoreJobTool:
    name = "score_job"
    description = "Score a job against user profile using LLM. Returns ScoreResult."

    def __init__(self, llm_chain: FallbackChain, score_threshold: int = 72):
        ...

    def execute(self, job: Job, profile: dict) -> dict:
        """
        Returns {"result": ScoreResult}

        Steps:
        1. Build prompt using SCORE_JOB_PROMPT template (see below).
        2. Call llm_chain.complete(prompt, system=SCORE_JOB_SYSTEM).
        3. Parse response with safe_parse_json(required_fields={"score": int, "decision": str}).
        4. Validate: score must be 0-100 (clamp if out of range).
                     decision must be "apply" or "skip" (default "skip" if invalid).
        5. Build and return ScoreResult.
        """
```

**SCORE_JOB_SYSTEM:**
```
You are an expert job application advisor. Evaluate job postings against a candidate profile and return a structured JSON assessment. Be honest and precise. Focus on skill match, role level fit, and growth potential.
```

**SCORE_JOB_PROMPT template** (use Python f-string with job and profile parameters):
```
Evaluate this job posting against the candidate profile.

## Job Details
Title: {job.title}
Company: {job.company}
City: {job.city}
Salary: {job.salary}
Job Description:
{job.jd_text}

## Candidate Profile
{profile_yaml_str}

## Instructions
Return ONLY a JSON object with this exact structure:
```json
{{
  "score": <integer 0-100, overall match score>,
  "decision": "<apply|skip>",
  "reason": "<2-3 sentences explaining the decision in Chinese>",
  "resume_patch": {{
    "summary": "<optional: suggested profile summary tweak for this role>",
    "highlights": ["<bullet 1>", "<bullet 2>"]
  }}
}}
```

Scoring guide:
- 90-100: Excellent match, apply immediately
- 72-89: Good match, worth applying
- 50-71: Partial match, consider carefully
- 0-49: Poor match, skip
```

Use `yaml.dump(profile, allow_unicode=True)` to format the profile as `profile_yaml_str`.

### 4. `tools/critique_job.py` — CritiqueJobTool

```python
class CritiqueJobTool:
    name = "critique_job"
    description = "Independent LLM review of a score decision. Returns CriticResult."

    def __init__(self, llm_chain: FallbackChain):
        ...

    def execute(self, job: Job, score_result: ScoreResult, profile: dict) -> dict:
        """
        Returns {"result": CriticResult}

        Steps:
        1. Build prompt using CRITIQUE_PROMPT template.
        2. Call llm_chain.complete(prompt, system=CRITIQUE_SYSTEM).
        3. Parse with safe_parse_json(required_fields={"verdict": str}).
        4. Validate: verdict must be "approve" or "reject".
        5. Return CriticResult.
        """
```

**CRITIQUE_SYSTEM:**
```
You are a skeptical second-opinion reviewer. Your job is to catch over-optimistic job scoring and prevent wasted applications. Check for: keyword stuffing, unrealistic skill matches, role level mismatches, and near-duplicate jobs the candidate has already applied to.
```

**CRITIQUE_PROMPT template:**
```
Review this job application decision.

## Job
Title: {job.title} | Company: {job.company} | City: {job.city}
Salary: {job.salary}

## First Scorer's Assessment
Score: {score_result.score}/100
Decision: {score_result.decision}
Reason: {score_result.reason}

## Candidate Profile Summary
{profile_summary}

## Your Task
Independently review whether this application decision is sound.
Watch for:
1. Keyword stuffing (JD uses many keywords but role doesn't match)
2. Level mismatch (JD requires 10 years, candidate has 2)
3. Salary expectation mismatch

Return ONLY a JSON object:
```json
{{
  "verdict": "<approve|reject>",
  "reason": "<2-3 sentences in Chinese explaining your verdict>"
}}
```
```

For `profile_summary`, use the first 500 characters of `yaml.dump(profile)`.

### 5. `tools/update_status.py` — UpdateStatusTool

```python
class UpdateStatusTool:
    name = "update_status"
    description = "Update job application status in the tracker."

    def __init__(self, tracker: ApplicationTracker):
        ...

    def execute(self, job_id: str, new_status: str, **extra_fields) -> dict:
        """
        Validate new_status is a valid AppStatus value.
        Call tracker.update_status(job_id, AppStatus(new_status), **extra_fields).
        Return {"updated": True, "job_id": job_id, "new_status": new_status}.
        On error, return {"updated": False, "error": str(e)}.
        """
```

## 文件清单

- `code/tools/__init__.py`：空文件
- `code/tools/registry.py`：TOOLS dict + register_tool + get_tool + initialize_tools
- `code/tools/score_job.py`：ScoreJobTool + prompt templates
- `code/tools/critique_job.py`：CritiqueJobTool + prompt templates
- `code/tools/update_status.py`：UpdateStatusTool

## Smoke Test

```bash
cd C:/Coding/AI-factory-projects/open-job-finder/code

# Test 1: Registry operations
python -c "
from tools.registry import register_tool, get_tool, list_tools

class FakeTool:
    name = 'fake_tool'
    description = 'test'
    def execute(self, **kwargs): return {}

register_tool(FakeTool())
assert 'fake_tool' in list_tools()
assert get_tool('fake_tool').name == 'fake_tool'
try: get_tool('nonexistent')
except KeyError as e: print('KeyError correctly raised:', e)
print('registry OK')
"

# Test 2: ScoreJobTool with mock LLM chain
python -c "
import datetime
from schemas import Job
from tools.score_job import ScoreJobTool

class MockChain:
    def complete(self, prompt, system=''):
        return '\`\`\`json\n{\"score\": 85, \"decision\": \"apply\", \"reason\": \"Good match.\", \"resume_patch\": {\"summary\": \"\", \"highlights\": []}}\n\`\`\`', 'mock'

tool = ScoreJobTool(llm_chain=MockChain())
job = Job(
    job_id='j001', title='Python Engineer', company='TestCorp',
    city='Beijing', salary='20-30k', url='https://example.com',
    jd_text='We need a Python engineer with 3 years experience.',
    source_keyword='python', discovered_at=datetime.datetime.utcnow().isoformat()
)
profile = {'skills': ['Python', 'FastAPI'], 'years_experience': 3}
result = tool.execute(job=job, profile=profile)
assert result['result'].score == 85
assert result['result'].decision == 'apply'
print('ScoreJobTool OK, score:', result['result'].score)
"

# Test 3: UpdateStatusTool
python -c "
import datetime, os
from schemas import ApplicationRecord, AppStatus
from services.tracker import ApplicationTracker
from tools.update_status import UpdateStatusTool

if os.path.exists('data/test_update.db'): os.remove('data/test_update.db')
tracker = ApplicationTracker(db_path='data/test_update.db')
now = datetime.datetime.utcnow().isoformat()
tracker.upsert(ApplicationRecord(
    job_id='j001', title='Test', company='Corp', url='http://x.com',
    status=AppStatus.DISCOVERED.value, created_at=now, updated_at=now
))

tool = UpdateStatusTool(tracker=tracker)
result = tool.execute(job_id='j001', new_status='SCANNED')
assert result['updated'] == True
assert tracker.get('j001').status == 'SCANNED'
print('UpdateStatusTool OK')
tracker.close()
os.remove('data/test_update.db')
"
```

<!-- FACTORY:DONE -->
