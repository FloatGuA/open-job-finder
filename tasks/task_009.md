# Task 009 — Dashboard (FastAPI + Frontend)

## 目标
Implement the FastAPI dashboard with REST API endpoints, resume upload, onboarding checklist, pause/resume control, and a single-page frontend (HTML/JS/CSS).

## 上下文
- 依赖：Task 001-008 (schemas, tracker, resume_parser, resume_manager, onboarding, orchestrator)
- 代码目录：`C:/Coding/AI-factory-projects/open-job-finder/code/`

## 实现要求

### 1. `dashboard/server.py` — FastAPI Application

```python
from fastapi import FastAPI, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

app = FastAPI(title="OpenJobFinder Dashboard")

# Mount static files
app.mount("/static", StaticFiles(directory="dashboard/static"), name="static")
```

#### Startup

On app startup (`@app.on_event("startup")`):
- Load config.yaml
- Initialize ApplicationTracker (shared instance)
- Initialize OnboardingChecker
- Initialize ResumeManager
- Store all in `app.state`

#### API Endpoints

**`GET /`**
- Return `dashboard/static/index.html` as HTMLResponse.

**`GET /api/jobs`**
- Query params: `status: str = None`, `page: int = 1`, `page_size: int = 20`
- Return paginated job list from tracker.
- Response schema:
```json
{
  "jobs": [
    {
      "job_id": "...",
      "title": "...",
      "company": "...",
      "city": "...",
      "salary": "...",
      "status": "APPLIED",
      "score": 85,
      "decision": "apply",
      "critic_verdict": "approve",
      "applied_at": "2026-03-18T09:00:00",
      "resume_path": "/output/resumes/job_id.pdf",
      "error_msg": null
    }
  ],
  "total": 42,
  "page": 1,
  "page_size": 20
}
```

**`GET /api/jobs/{job_id}`**
- Return single ApplicationRecord as JSON.
- 404 if not found.

**`GET /api/stats`**
- Return tracker.get_stats() enriched with onboarding status.
- Response:
```json
{
  "stats": {
    "total": 42,
    "by_status": {"DISCOVERED": 5, "APPLIED": 20, ...},
    "applied_today": 3,
    "daily_limit": 25,
    "remaining_today": 22
  },
  "onboarding": {
    "profile": true,
    "resume": false,
    "session": true,
    "llm_provider": true,
    "all_ok": false
  }
}
```

**`POST /api/pause`**
- Set a global pause flag in app.state.
- Response: `{"paused": true, "message": "Scheduler paused."}`
- Note: actual scheduler pausing requires the orchestrator/scheduler to be running in the same process. If running separately, write a `data/control.json` flag file that the scheduler reads.

**`POST /api/resume`**
- Clear the pause flag / delete `data/control.json`.
- Response: `{"paused": false, "message": "Scheduler resumed."}`

**`POST /api/resume/upload`**
- Accept multipart file upload (PDF or .docx).
- Save to `data/resume_raw_{timestamp}.{ext}`.
- Call `parse_resume_file(saved_path)` to parse.
- Save result to `data/resume_base.yaml`.
- Return:
```json
{
  "success": true,
  "message": "Resume parsed and saved.",
  "sections_found": ["name", "experience", "education", "skills"]
}
```
- On error: return 400 with error detail.

**`GET /api/onboarding/status`**
- Return OnboardingChecker.check_all() result as JSON.

**`GET /api/control/status`**
- Read `data/control.json` if exists, return pause status.
- Response: `{"paused": bool, "paused_at": "ISO8601 or null"}`

#### Control Flag File

`data/control.json` format:
```json
{"paused": true, "paused_at": "2026-03-18T10:00:00"}
```

The orchestrator's `run_once()` should check this file at the start of each cycle and skip if `paused == true`.

Add to `orchestrator.py` a method:
```python
def _is_paused(self) -> bool:
    """Read data/control.json, return paused flag. Default False if file missing."""
```

And call `_is_paused()` at the start of `run_once()`.

### 2. `dashboard/static/index.html` — Single Page Application

Structure:
```html
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>OpenJobFinder Dashboard</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <header>
    <h1>OpenJobFinder</h1>
    <div id="controls">
      <button id="btn-pause">Pause</button>
      <button id="btn-resume">Resume</button>
    </div>
  </header>

  <!-- Onboarding Checklist (shown when any item is incomplete) -->
  <section id="onboarding-section">
    <h2>Setup Checklist</h2>
    <ul id="onboarding-list">
      <!-- Items injected by JS -->
    </ul>
    <!-- Resume upload card (shown only when resume is missing) -->
    <div id="resume-upload-card" style="display:none">
      <h3>Upload Resume</h3>
      <p>Upload your Boss直聘 exported PDF or Word file</p>
      <input type="file" id="resume-file" accept=".pdf,.docx">
      <button id="btn-upload-resume">Upload & Parse</button>
      <div id="upload-status"></div>
    </div>
  </section>

  <!-- Stats Bar -->
  <section id="stats-bar">
    <!-- Applied today / total / remaining / responded / interviews / offers -->
  </section>

  <!-- Job List -->
  <section id="job-list-section">
    <h2>Applications</h2>
    <div id="status-filter">
      <!-- Filter buttons: All / APPLIED / RESPONDED / INTERVIEW / OFFER / REJECTED / ERROR -->
    </div>
    <table id="jobs-table">
      <thead>
        <tr>
          <th>Company</th><th>Title</th><th>City</th><th>Salary</th>
          <th>Score</th><th>Status</th><th>Applied At</th><th>Actions</th>
        </tr>
      </thead>
      <tbody id="jobs-tbody"><!-- rows injected by JS --></tbody>
    </table>
    <div id="pagination">
      <button id="btn-prev">Previous</button>
      <span id="page-info">Page 1</span>
      <button id="btn-next">Next</button>
    </div>
  </section>

  <script src="/static/app.js"></script>
</body>
</html>
```

### 3. `dashboard/static/app.js` — Frontend Logic

Implement the following functions:

```javascript
const API = {
  getStats: () => fetch('/api/stats').then(r => r.json()),
  getJobs: (status, page) => fetch(`/api/jobs?status=${status||''}&page=${page||1}`).then(r => r.json()),
  getJob: (id) => fetch(`/api/jobs/${id}`).then(r => r.json()),
  pause: () => fetch('/api/pause', {method: 'POST'}).then(r => r.json()),
  resume: () => fetch('/api/resume', {method: 'POST'}).then(r => r.json()),
  getOnboarding: () => fetch('/api/onboarding/status').then(r => r.json()),
  uploadResume: (file) => {
    const fd = new FormData(); fd.append('file', file);
    return fetch('/api/resume/upload', {method: 'POST', body: fd}).then(r => r.json());
  }
};

// State
let currentPage = 1;
let currentFilter = null;
let autoRefreshInterval = null;

// Functions to implement:
// - renderOnboarding(status): show/hide onboarding section and resume upload card
// - renderStats(stats): update stats bar
// - renderJobs(data): populate table rows
// - renderPagination(data): update page info and button states
// - applyFilter(status): set currentFilter and reload jobs
// - loadAll(): call getStats() and getJobs() and update all sections
// - startAutoRefresh(): setInterval(loadAll, 30000) to refresh every 30 seconds

// Event listeners:
// - btn-pause: API.pause() then loadAll()
// - btn-resume: API.resume() then loadAll()
// - btn-upload-resume: read file, API.uploadResume(), show result
// - status filter buttons: applyFilter(status)
// - btn-prev / btn-next: pagination
// - Row click: show job detail (could be inline expand or modal)

// Status colors (map status to CSS class):
// DISCOVERED: gray, SCANNED: blue, SCORED: purple, APPLIED: orange,
// RESPONDED: teal, INTERVIEW: gold, OFFER: green, REJECTED: red, ERROR: red

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
  loadAll();
  startAutoRefresh();
});
```

### 4. `dashboard/static/style.css` — Styles

Implement a clean, minimal dark-themed dashboard:

- Background: `#1a1a2e`, text: `#e0e0e0`
- Header: fixed top bar with title and control buttons
- Onboarding section: yellow-bordered info box, hidden when `all_ok=true`
- Resume upload card: dashed border file drop area
- Stats bar: horizontal flex, each stat in a card with large number
- Job table: striped rows, hover highlight, status badge (colored pill)
- Status badge CSS classes: `.status-applied { background: #f59e0b }`, etc.
- Buttons: rounded, primary color `#2E5BFF`
- Pagination: centered, with disabled state styling
- Responsive: works at 1200px+ minimum width

## 文件清单

- `code/dashboard/__init__.py`：空文件
- `code/dashboard/server.py`：FastAPI app + all endpoints
- `code/dashboard/static/index.html`：SPA shell
- `code/dashboard/static/app.js`：frontend logic
- `code/dashboard/static/style.css`：dark theme styles

## Smoke Test

```bash
cd C:/Coding/AI-factory-projects/open-job-finder/code

# Test 1: Import FastAPI app
python -c "
from dashboard.server import app
print('FastAPI app imported OK')
print('Routes:', [r.path for r in app.routes])
"

# Test 2: Start server and test endpoints (requires uvicorn)
# Run in background:
# python -m uvicorn dashboard.server:app --host 0.0.0.0 --port 8765 &
# Then:
# curl http://localhost:8765/api/stats
# curl http://localhost:8765/api/jobs
# curl http://localhost:8765/api/onboarding/status

# Test 3: Resume upload endpoint (unit test without live server)
python -c "
from fastapi.testclient import TestClient
from dashboard.server import app

client = TestClient(app)

# Test stats endpoint
resp = client.get('/api/stats')
print('GET /api/stats status:', resp.status_code)
if resp.status_code == 200:
    data = resp.json()
    print('stats keys:', list(data.keys()))

# Test jobs endpoint
resp = client.get('/api/jobs')
print('GET /api/jobs status:', resp.status_code)
if resp.status_code == 200:
    data = resp.json()
    print('jobs response keys:', list(data.keys()))

# Test onboarding
resp = client.get('/api/onboarding/status')
print('GET /api/onboarding/status status:', resp.status_code)
if resp.status_code == 200:
    print('onboarding:', resp.json())
"

# Test 4: Verify static files exist
python -c "
import os
for f in ['dashboard/static/index.html', 'dashboard/static/app.js', 'dashboard/static/style.css']:
    exists = os.path.exists(f)
    print(f'{f}: {\"OK\" if exists else \"MISSING\"}')
"
```

## Dashboard Startup Command

```bash
cd C:/Coding/AI-factory-projects/open-job-finder/code
python -m uvicorn dashboard.server:app --host 0.0.0.0 --port 8765 --reload
# Access: http://localhost:8765
```

<!-- FACTORY:DONE -->
