# Task 005 — Browser Agent (Playwright)

## 目标
Implement the full Playwright-based browser agent for Boss直聘: login/session management, job search, JD scraping, application submission, and chat list polling.

## 上下文
- 依赖：Task 001 (schemas.py, services/exceptions.py, services/logger.py, services/retry.py)
- 代码目录：`C:/Coding/AI-factory-projects/open-job-finder/code/`

## 实现要求

### `services/browser_agent.py` — BrowserAgent

Use `playwright.sync_api` (synchronous API). All browser operations run in headed mode (`headless=False`) by default, configurable to `headless=True` via config.

#### Class Structure

```python
class BrowserAgent:
    BASE_URL = "https://www.zhipin.com"

    def __init__(self, session_path: str = "data/session.json", headless: bool = False):
        self.session_path = session_path
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def start(self) -> None:
        """
        Initialize Playwright, browser, and context.
        If session_path exists, load it: context = browser.new_context(storage_state=session_path)
        Otherwise: context = browser.new_context()
        Create a new page from context.
        """

    def stop(self) -> None:
        """Close page, context, browser, and playwright. Swallow exceptions."""

    def save_session(self) -> None:
        """context.storage_state(path=session_path) — save cookies and localStorage."""

    def ensure_logged_in(self) -> None:
        """
        Navigate to BASE_URL. Check if login prompt is visible.
        If not logged in: raise SessionExpiredError("Session expired or not found. Please log in manually.")
        Detection: look for element with text "登录" in the nav bar, or check URL contains "login".
        """

    def login_interactive(self) -> None:
        """
        Navigate to BASE_URL/web/user/?ka=header-login
        Print instructions: "Please log in manually in the browser window. Press Enter when done."
        Wait for input(). Then verify logged in via ensure_logged_in().
        Save session if successful.
        """
```

#### Search

```python
    def search(self, keywords: str, city: str, limit: int = 30) -> List[Job]:
        """
        Navigate to Boss直聘 job search page with keywords and city params.
        URL pattern: {BASE_URL}/web/geek/job?query={keywords}&city={city_code}

        City code mapping (include at minimum):
        "北京": "101010100", "上海": "101020100", "深圳": "101280600",
        "广州": "101280100", "杭州": "101210100", "成都": "101270100",
        "武汉": "101200100", "南京": "101190100", "西安": "101110100"
        If city not in mapping, use city string as-is.

        Scraping strategy:
        1. Wait for job card elements: selector ".job-card-wrapper" or ".job-list-box .job-card-left"
        2. For each card (up to limit):
           - Extract: title (.job-name), company (.company-name), city+salary from .job-info
           - Extract job URL from the <a> tag href on the card
           - Extract job_id from the URL (e.g., last path segment before .html)
        3. Handle pagination: if fewer than limit results, click next page if available.
        4. Return List[Job] with status=DISCOVERED, jd_text="" (filled by open_job later).
        5. Wrap all Playwright calls with with_retry(func, max_attempts=3, base_delay=2).

        Important: Add random sleep of 1-3 seconds between page actions to avoid detection.
        """
```

#### JD Scraping

```python
    def open_job(self, url: str) -> str:
        """
        Navigate to job URL.
        Wait for and extract the full JD text from:
          - Primary selector: ".job-detail-section" or ".job-sec-text"
          - Fallback: body text if specific selector not found
        Return the text content (stripped).
        Wrap with retry.
        """
```

#### Application Submission

```python
    def apply(self, job: Job, resume_path: str = None) -> bool:
        """
        Navigate to job.url.
        Find and click the "立即沟通" button.
        Wait for the chat dialog to open.
        In the chat input box, type a greeting message.
        Send the message (press Enter or click send button).
        Return True on success, False if button not found or dialog fails.

        Greeting message template:
        "您好，我是[候选人]，看到贵公司的{job.title}职位很感兴趣，希望有机会进一步了解，期待您的回复！"

        Note: If profile is available, use candidate name from profile.
        Selector hints:
          - "立即沟通" button: ".btn-startchat" or button with text "立即沟通"
          - Chat input: ".chat-input" or "[contenteditable='true']"
          - Send button: ".send-btn" or button with text "发送"
        Wrap with retry (max_attempts=2, since apply should be cautious).
        """

    def check_chat_list(self) -> List[StatusUpdate]:
        """
        Navigate to Boss直聘 chat/messages page: {BASE_URL}/web/geek/chat
        For each conversation in the list:
          1. Extract company name and last message preview.
          2. Classify status based on message content keywords:
             - "面试" / "interview" → INTERVIEW
             - "不合适" / "感谢" / "暂时" → REJECTED
             - Any reply → RESPONDED
          3. Extract job_id from the conversation link if available.
        Return List[StatusUpdate] (may be empty).
        Limit to first 20 conversations to avoid over-scraping.
        """
```

#### Context Manager Support

```python
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()
```

#### SearchJobsTool

Also implement `tools/search_jobs.py` in this task since it depends directly on BrowserAgent:

```python
class SearchJobsTool:
    name = "search_jobs"
    description = "Search Boss直聘 for jobs matching keywords and city."

    def __init__(self, browser_agent: BrowserAgent):
        ...

    def execute(self, keywords: str, city: str, limit: int = 30) -> dict:
        """
        Calls browser_agent.search(keywords, city, limit).
        Also calls browser_agent.open_job(job.url) for each job to fill jd_text.
        Returns {"jobs": List[Job]}.
        On SessionExpiredError, re-raise (let orchestrator handle).
        On other errors per-job, log warning and continue.
        """
```

## 文件清单

- `code/services/browser_agent.py`：BrowserAgent class
- `code/tools/search_jobs.py`：SearchJobsTool

## Smoke Test

```bash
cd C:/Coding/AI-factory-projects/open-job-finder/code

# Test 1: Import and instantiate (no browser launch)
python -c "
from services.browser_agent import BrowserAgent
from tools.search_jobs import SearchJobsTool
print('imports OK')
b = BrowserAgent(session_path='data/session.json', headless=True)
print('BrowserAgent instantiation OK')
"

# Test 2: Verify Playwright is installed
python -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    print('playwright available, browsers:', [b for b in ['chromium', 'firefox', 'webkit']])
"

# Test 3: Dry run — launch browser and check BASE_URL reachable (headless)
# NOTE: This test requires a display or headless mode. Run manually if no display available.
python -c "
from services.browser_agent import BrowserAgent
try:
    with BrowserAgent(headless=True) as agent:
        agent._page.goto('https://www.zhipin.com', timeout=15000)
        title = agent._page.title()
        print('Boss直聘 page title:', title[:50])
except Exception as e:
    print('Browser test skipped (expected in headless env):', type(e).__name__, str(e)[:100])
"
```

> Note: Full integration test (login, search, apply) requires a valid Boss直聘 account and must be run manually. The smoke test above only verifies imports and basic connectivity.

<!-- FACTORY:DONE -->
