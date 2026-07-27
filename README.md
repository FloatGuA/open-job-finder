# OpenJobFinder

基于 Boss直聘 的 AI 自动化求职 Agent，三条流程：**W1 投递**（按求职偏好搜索职位、LLM 多维度评分筛选、自动投递）；**W2 检查回应**（同步 HR 会话、分析意图、按需发送附件简历、追踪应聘进展并草拟回复）；**W3 发送已批准回复**（把你审批过的回复定位会话发出，并重扫验证投递落地）。

An AI-powered job application agent for Boss Zhipin, in three workflows: **W1 (apply)** — search jobs by your preferences, score them with LLM across multiple dimensions, auto-apply; **W2 (check responses)** — sync HR conversations, analyze intent, send resume attachments on demand, track progress and draft replies; **W3 (send approved replies)** — locate the conversation, send the reply you approved, and verify delivery by re-scanning the thread.

---

## 功能特性 / Features

- 自动搜索职位，支持多关键词 + 多城市组合，按无限滚动方式抓取结果
  Automated job search with multi-keyword and multi-city combinations, using infinite scroll scraping

- LLM 结构化评分：将职位按技能匹配、经验匹配、城市、薪资、发展潜力 5 个维度独立打分，Python 端加权汇总，结果稳定可预期
  Structured LLM scoring across 5 independent dimensions (skill match, experience, city, salary, growth potential), with Python-side weighted aggregation for consistent results

- 评分阈值用户可配置：在求职偏好设置中交互调整（0-100，默认 60）
  User-configurable score threshold: set interactively in profile setup (0-100, default 60)

- 幂等投递保护：数据库层面防止重复投递同一职位，程序崩溃重启后安全续跑
  Idempotent application protection: database-level guard prevents duplicate submissions, safe to restart after crash

- 多 Provider LLM 支持，自动 Fallback：支持 claude CLI、Ollama、Anthropic API、OpenAI 兼容接口
  Multi-provider LLM with automatic fallback: supports claude CLI, Ollama, Anthropic API, and OpenAI-compatible endpoints

- HR 会话完整读取与本地缓存：逐一点入聊天对话，读取完整消息历史，存入 SQLite；增量脏检查，只同步有新消息的会话
  Full HR conversation sync with local cache: reads complete message history per chat, stores in SQLite; incremental dirty-check syncs only updated conversations

- 自动发送附件简历：检测到 HR 索要简历时按路径发送——HR 请求卡片点"同意"或点工具栏"发简历"按钮；发送成功以聊天框出现「附件简历」系统消息为唯一判据
  Automatic resume attachment sending: when an HR resume request is detected, sends via the matching path — accept the HR card or click the toolbar send button; delivery is confirmed only when the "resume attachment" system message appears in chat

- 聊天回应分阶段追踪：HR 会话按 stage（普通/已发简历/面试阶段）管理，stage 只升不降，Dashboard 可按 stage 过滤查看
  Stage-based HR conversation tracking: conversations progress through stages (general → resume_sent → interview), stages never downgrade; filterable in the Dashboard

- 人工审批 + 自动发送回复（W3）：W2 对需要回复的 HR 消息草拟建议回复，你在 Dashboard 会话页批准/修改/驳回；W3 用聊天搜索框定位会话、发送你批准的回复，并通过重扫会话确认消息真正落地后才标记已发（避免"发了没发出去"的假成功）
  Human-approved auto-reply (W3): W2 drafts a suggested reply for HR messages that need one; you approve/edit/dismiss it on the Dashboard chat page; W3 then locates the conversation via the chat search box, sends the approved reply, and marks it sent only after re-scanning the thread confirms the message actually landed (no false "sent" without delivery)

- FastAPI Dashboard：可视化查看所有投递状态，支持简历上传、手动暂停/继续、HR 会话浏览；主面板直接查看与修改每日投递上限（Boss直聘 平台硬上限，默认 150）；内置自动调度卡片，可为 W1/W2 分别配置指定时间点（HH:MM）和间隔小时；"配置"页面可直接在浏览器中编辑求职偏好，无需手动修改 YAML；LLM Provider 配置按能力级别（fast/balanced/powerful）组织，保存后立即生效无需重启
  FastAPI Dashboard: visualize all application statuses, upload resumes, manually pause/resume, and browse HR conversations; view and edit the daily application limit (Boss Zhipin's platform hard cap, default 150) right on the main panel; built-in scheduling card for W1/W2 time-of-day and interval triggers; a Config page lets you edit job search preferences directly in the browser without touching YAML files; LLM providers are configured by capability level (fast/balanced/powerful) and take effect immediately without restart

- 工作流队列（控制台）：所有工作流启动（手动触发 / 定时调度 / 自检 / W1→W2 一键链）统一进入队列顺序执行，不再「忙时被拒或漏跑」；控制台队列面板支持拖拽改序、暂停/继续、移除、查看加入时间与最近完成
  Workflow queue (console): every workflow start — manual trigger, scheduled job, self-check, or a one-click W1->W2 chain — is enqueued and run in order (no more "rejected or skipped while busy"); the console queue panel supports drag-to-reorder, pause/resume, remove, and shows enqueue time and recent runs

- 自检模块（独立页面）：一键探针检查浏览器登录态、数据库、LLM 可用性；可运行完整自检周期（真实跑一轮 W1/W2）并查看历史记录；支持每 12 小时自动自检（W1 10 个职位 + W2 全量，不含 W3）
  Self-check module (dedicated page): one-click probes for browser login state, database, and LLM availability; run a full self-check cycle (actually executes a W1/W2 round) with history; optional automatic self-check every 12 hours (W1 10 jobs + full W2, excluding W3)

- 结构化简历模块（独立页面）：上传简历 + 自我描述后，由 LLM 解析成可排列组合的段落块（教育/实习/项目/技能/获奖），支持 FlowCV 式手动增删改与排序；可针对单个职位生成定制简历与招呼语（含关键词匹配的预制模板），并用 Chromium 渲染导出 PDF，无需 WeasyPrint/GTK 系统依赖（简历自动发送功能尚未实现）
  Structured resume module (dedicated page): upload a resume plus a self-description and let the LLM parse it into recombinant blocks (education / internship / project / skills / awards), editable and reorderable FlowCV-style; generate a tailored resume and greeting per job (with keyword-matched preset templates) and export to PDF rendered via Chromium — no WeasyPrint/GTK system dependencies required (automatic resume sending is not yet implemented)

- 日志页"概览"视图：把每次 workflow 运行的日志解析成类实时（live）的可读时间线，无需直接阅读原始 JSON
  Logs "overview" view: parses each workflow run's log into a live-style readable timeline, no need to read raw JSON

---

## 安装 / Installation

**前提条件 / Prerequisites**

- Python 3.11+
- Chrome 浏览器（已安装即可，DrissionPage 会复用；简历 PDF 也由它渲染，无需额外系统依赖）
  Chrome browser (already installed; DrissionPage reuses it, and resume PDFs are rendered through it — no extra system dependencies needed)

```bash
# 克隆仓库 / Clone the repo
git clone <repo-url>
cd open-job-finder/code

# 安装 Python 依赖 / Install Python dependencies
pip install -r requirements.txt
```

若你会向本仓库提交代码，安装 pre-commit 钩子，防止个人数据（真实 HR 姓名、公司、聊天内容）误提交——它按文件位置和内容双重扫描暂存区。

If you will commit to this repo, install the pre-commit hook to keep personal data (real HR names, companies, chat content) from being committed by mistake — it scans staged changes by both file location and content.

```bash
# 在仓库根目录运行 / Run at the repo root
python code/scripts/install_hooks.py
```

---

## 使用方式 / Usage

### 首次配置 / First-time setup

登录 Boss直聘 由 **Dashboard** 完成（CLI 登录已退役）：启动 Dashboard 后在「设置 → 环境&Session」点「打开登录浏览器」完成登录，登录态保存在 `data/browser_profile/`。`python main.py --onboarding` 现在只会提示改用 Dashboard。

Login to Boss Zhipin is handled by the **Dashboard** (CLI login is retired): start the Dashboard, then under "Settings → Environment & Session" click "Open login browser" to log in; the session lives in `data/browser_profile/`. `python main.py --onboarding` now just points you to the Dashboard.

### 配置求职偏好 / Configure job search preferences

设置关键词、城市、薪资期望、经验要求、是否仅显示最近活跃 HR、评分阈值等（共 9 项，均可留空）。

Set keywords, cities, salary expectations, experience requirements, active-HR filter, score threshold, and more (9 fields, all optional).

```bash
python main.py --setup-profile
```

**评分阈值 / Score threshold**：第 9 步输入 0-100 的整数。数值越低，投递范围越广；建议初次使用设为 55-65。此值写入 `data/profile.yaml`，优先于 `config.yaml` 中的默认值。

The 9th step prompts for an integer from 0-100. Lower values cast a wider net; 55-65 is recommended for initial use. This value is saved to `data/profile.yaml` and overrides the default in `config.yaml`.

**打招呼语 / Greeting message**：系统点击"立即沟通"后，Boss直聘自动发送你在 App 中预设的打招呼语。请在 Boss直聘 App →「我」→「求职设置」→「打招呼语」中提前配置。

The system clicks "Start Chat" and Boss Zhipin automatically sends your pre-configured greeting message. Set it in the Boss Zhipin App under Profile → Job Search Settings → Greeting Message.

### 验证全流程（不实际投递）/ Dry run

```bash
python main.py --dry-run
```

### 单次执行（真实投递）/ Run one apply cycle

```bash
python main.py --once
```

### 定时调度 / Scheduling

定时触发已内置在 Dashboard 中（不再用无参 `python main.py` 启动调度器）。在 Dashboard 的「自动调度」卡片为 W1/W2 分别配置指定时间点（HH:MM）或间隔小时即可。

Scheduling is built into the Dashboard (the bare `python main.py` scheduler is no longer available). Configure time-of-day (HH:MM) or interval-hour triggers for W1/W2 in the Dashboard's scheduling card.

### 仅检查聊天回应 / Check responses only

读取聊天列表，同步有新消息的 HR 对话（含完整消息历史），检测简历请求并自动发送附件简历，更新投递状态。

Reads the chat list, syncs conversations with new messages (including full history), detects resume requests and auto-sends attachment, and updates application statuses.

```bash
python main.py --check
```

扫描范围由 `config.yaml` 的 `w2` 段控制（Dashboard「配置」页也可覆盖）：

Scanning scope is controlled via the `w2` section of `config.yaml` (also overridable in the Dashboard Config page):

```yaml
w2:
  max_conversations: 200    # 本次最多处理会话数 / Max conversations per run
  no_response_days: 14      # 投递后无回应判超时拒绝 / Days before no-response timeout
  stale_conv_days: 14       # 最后一条消息满 N 天无更新判陈旧关闭 / Days since last message before stale-close
```

### 启动 Dashboard / Start the Dashboard

前端构建产物已预先包含在仓库中（`dashboard/static/`），直接启动后端即可：

The frontend build artifacts are already included in the repo (`dashboard/static/`). Just start the backend:

```bash
cd code
python -m uvicorn dashboard.server:app --host 0.0.0.0 --port 8765 --reload
# 访问 / Open: http://localhost:8765
```

**前端开发模式 / Frontend dev mode**

如需修改前端代码，需同时启动后端（用于 API）和前端开发服务器（热更新）：

To modify frontend code, start both the backend (for API) and the frontend dev server (HMR) in separate terminals:

```bash
# 终端 1 — 后端 / Terminal 1 — Backend
cd code
python -m uvicorn dashboard.server:app --host 0.0.0.0 --port 8765 --reload

# 终端 2 — 前端开发服务器 / Terminal 2 — Frontend dev server
cd code/dashboard/frontend
npm install        # 首次 / first time only
npm run dev
# 访问 / Open: http://localhost:5173
```

**重新构建前端 / Rebuild frontend**

修改完成后构建产物，uvicorn 将直接服务编译后的静态文件：

After modifying frontend code, rebuild the artifacts so uvicorn serves the compiled output:

```bash
cd code/dashboard/frontend
npm run build
# 产物输出到 dashboard/static/，之后直接访问 :8765 即可
# Build output goes to dashboard/static/; then access :8765 directly
```

---

## 配置文件 / Configuration

`config.yaml` 管理系统级配置（LLM Provider、调度时间、每日投递上限等）。

`config.yaml` manages system-level settings (LLM providers, schedule, daily application limit, etc.).

求职偏好（关键词、城市、阈值等用户个性化设置）通过 `--setup-profile` 写入 `data/profile.yaml`，其中的值优先于 `config.yaml` 中的对应项。

Job search preferences (keywords, cities, threshold, etc.) are written to `data/profile.yaml` via `--setup-profile` and take precedence over `config.yaml`.

---

## 技术栈 / Tech Stack

- Python 3.11+ — 主语言 / Primary language
- DrissionPage — 浏览器自动化，绕过反爬检测 / Browser automation with anti-bot bypass
- APScheduler — 定时任务调度 / Scheduled task execution
- SQLite — 求职状态与 HR 会话持久化 / Application state and HR conversation persistence
- FastAPI + uvicorn — Dashboard 后端 / Dashboard backend
- React 18 + Vite + Tailwind CSS v3 — Dashboard 前端 SPA / Dashboard frontend SPA
- Jinja2 + Chromium (DrissionPage CDP) — 结构化简历 HTML 渲染与 PDF 导出 / Structured resume HTML rendering and PDF export
- PyYAML — 配置与 profile 读写 / Config and profile I/O
- questionary — 交互式 TUI 配置引导 / Interactive TUI for profile setup
- json-repair — LLM 输出 JSON 容错修复 / Fault-tolerant JSON parsing for LLM output
