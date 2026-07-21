# OpenJobFinder — 开发说明

## 你的角色

你是这个项目的维护者，**直接修改代码**。每次改动遵循下方"开发规则"，保证可追溯、有测试守门、文档同步。

（本项目早期由 AI 工厂流程构建，现已退役 factory 流程——不再写 task 文件、不再调 codex/独立 runner、不再生成 report/review。直接开发。）

---

## 项目简介

基于 DrissionPage 的 Boss直聘 自动化求职 AI Agent：按用户求职偏好搜索职位，用 LLM 多维度评分决策，自动投递（W1）；并同步 HR 会话、分析意图、发送简历与审批过的回复、追踪应聘进展（W2）。通过 FastAPI + React Dashboard 实时可视化（SSE）。

两条核心流程：
- **W1（投递）**：搜索 → 分类 → 抓取 JD → LLM 评分 → 超阈值则投递 → 落库
- **W2（检查回应）**：扫描会话列表 → 逐会话导航/读消息 → LLM 分析意图 → （按需发简历）→ （发送审批过的回复）→ 落库 → 收尾（超时关闭/状态同步）

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| 浏览器自动化 | **DrissionPage**（同步，绕过 CDP 反爬；非 Playwright） |
| LLM 调用 | `ModelRouter` + FallbackChain（`claude_cli` / `codex_cli` / `ollama` / `anthropic_api` / `openai_compatible`），按 capability（fast/balanced/powerful）路由 |
| 数据库 | SQLite（`data/jobs.db`） |
| Dashboard 后端 | FastAPI + uvicorn（端口 8765），SSE 推送 workflow 进度 |
| Dashboard 前端 | React 18 + Vite + Tailwind CSS v3（构建产物落入 `dashboard/static/`） |
| 简历生成 | Jinja2 + WeasyPrint（需系统级依赖；当前默认关闭） |
| 配置 | YAML（PyYAML） |

---

## 启动方式

```bash
cd C:/Coding/AI-factory-projects/open-job-finder/code

# 安装依赖
pip install -r requirements.txt

# 首次启动引导（配置 profile、登录 session）
python main.py --onboarding

# 启动 Dashboard（端口 8765；触发 W1/W2 的权威入口）
python -m uvicorn dashboard.server:app --host 0.0.0.0 --port 8765 --reload
# 访问 http://localhost:8765

# CLI 直接跑（注意：会委托给正在运行的 Dashboard server）
python main.py --once     # 跑一次 W1（投递）
python main.py --check    # 跑一次 W2（检查回应）
python main.py --dry-run  # W1 演练，不真实投递

# 端到端手动验证脚本（有头 + 可限规模，绕过 main.py 限制）
python scripts/run_e2e.py verify [--wait N]                       # 用 VerifySessionStep 确认登录
python scripts/run_e2e.py w1 [--max-cards N] [--score-threshold N]
python scripts/run_e2e.py w2 [--no-response-days N] [--stale-conv-days N]

# 测试 / 前端构建
pytest
cd dashboard/frontend && npm run build
```

> **登录态**在 `data/browser_profile/`（DrissionPage 的 Chrome user-data 目录），**不是** `data/session.json`（那是废弃占位）。session 是否有效，唯一权威判断是跑 `VerifySessionStep`（访问 `geek/recommend` 读 `window._PAGE.name`）。

---

## 目录结构（主干，按职责）

```
code/
├── main.py                  # CLI 入口（--once/--check/--onboarding/--dry-run）
├── schemas.py / protocols.py
├── config.yaml              # 系统配置 + workflow 运行参数出厂默认（见"配置"）
├── pipeline/                # W1/W2 流程编排（Step 模式）
│   ├── base.py              # StepStatus / StepOutput
│   ├── run_logger.py        # RunLogger（文件日志 + SSE）
│   ├── common/verify_session.py
│   ├── w1_runner.py / w2_runner.py   # 组装 registry + 运行 pipeline（main.py 与 server 共用入口）
│   ├── w1/                  # pipeline.py / card_pipeline.py / steps/{navigate,fetch_jd,apply}
│   └── w2/                  # pipeline.py / scan_step.py / conversation_pipeline.py / finalize_step.py / steps/{navigate,read,analyze,resume,reply}
├── services/
│   ├── browser_context.py   # open_browser/close_browser（DrissionPage）
│   ├── tracker.py           # SQLite 状态机（applications + hr_conversations + hr_messages）
│   ├── llm_client.py        # ModelRouter + FallbackChain + build_model_router
│   ├── config_manager.py    # 读写 config.yaml / profile.yaml（单例）
│   ├── profile_loader.py    # 加载 profile.yaml → Profile dataclass
│   ├── boss_search_url.py   # 由 profile 拼 Boss 搜索 URL
│   ├── prompt_manager.py    # Prompt 模板加载
│   └── onboarding.py        # 首次引导 + session 验证
├── tools/                   # 工具层（registry.call 调用，统一日志/错误契约）
│   ├── registry.py / base.py
│   ├── browser/             # w1/ w2/ 的 DrissionPage 操作 + verify_current_url
│   ├── db/                  # w1/ w2/ 的 SQLite 持久化
│   ├── llm/                 # score_job / analyze_intent
│   └── biz_logic/           # decode_salary / detect_resume / filter_conversations / url_parsers
├── dashboard/
│   ├── server.py            # FastAPI（所有 API 端点 + SSE + 调度）
│   ├── frontend/            # React 源码（npm run build → static/）
│   └── static/              # 构建产物（不要手改）
├── data/                    # 运行时数据（gitignore）
└── tests/
```

---

## 后端分层约定（代码该放哪）

后端按职责严格分四层，新功能**有确定的家**，不要内联手搓：

| 层 | 放什么 | 判据 |
|----|--------|------|
| `tools/` | 对外部系统的**单个副作用操作**（浏览器/DB/LLM）；经 `registry.call` 调用，ToolResult 契约，自动 trace/SSE | "是不是一次碰浏览器/DB/LLM 的活儿" |
| `pipeline/`（Step） | 把多个 tool 编排成**工作流的一个阶段**（W1/W2/未来 W3） | "是不是某条工作流里的一段"——一次性交互动作不算，别造假 Step |
| `services/` | 共享基建/单例（`BrowserSession`、`tracker`、`llm_client`、`config_manager`） | "是不是被多处共用的基建" |
| `dashboard/server.py` | **只做 HTTP 接线**：解析请求 → 调 tool/step/service → 序列化返回 | —— |

**铁律：端点不准内联浏览器/LLM/业务逻辑，必须委托给 tool/step/service。** 违反它必然制造两份分叉实现（加固一个漏一个）+ 不可观测（绕开 registry 就没 trace/SSE）。反例教训：交互端点曾内联遗留 `BrowserAgent`，与流水线的 `VerifySessionStep` 分叉，导致 session 验证误报"过期"。收敛过程与分层论证详见 **`docs/browser-session-convergence.md`**。

> 例外：纯读端点（GET `/api/jobs`、`/api/stats` 等）直接调 `tracker` 序列化即可，**不强行 tool 化**——tool 契约是为流水线可观测/可重放设计的，仪表盘读取用不上，硬包只剩仪式感。

**第二条铁律：一个状态转换只能有一份 SQL。** `tracker` 独占连接、schema、迁移，以及每个写操作的唯一实现；`tools/db/*` 是薄壳（提供 ToolResult 契约与 registry 的 trace/SSE），**调 tracker 而不是自持 SQL**；端点里一律不出现 SQL。

这条不是洁癖——2026-07 一次审查连抓四例同构漂移，全都因为"同一转换有两份实现"：

| 分叉 | 后果 |
|------|------|
| `mark_reply_sent` 三份 | 一份写 `NULL` 而非 `'sent'`，不在保护集里 → **可能给同一 HR 二次发送** |
| `update_hr_analysis` 两份 | tracker 版缺 `last_analyzed_ts` → 误接即回退读/析解耦；传 `None` 时一版保留原值、一版写 NULL 清空草稿 |
| `upsert_application` 的 `applied_at` | 一版"保留首次"、一版"更新为最后" → 重投不计入今日，且被按过期时间提前清理 |
| 冒烟自持执行路径 | 绕过队列的 schedule_log / trigger 映射 / 错误清理 |

**识别判据：同一列在不同实现里的 CASE 分支不一致。** 发现分叉时不要两边同步，选正确的那版收敛掉另一版（见 `docs/audit-remediation-log.md`）。

> **反例，同样重要**：`upsert_hr_conversation` 的两个实现**不是**分叉，是有意的职责分离——工具版是运行时规范写路径（W1 stub + W2 扫描，写 `last_msg_ts`/`hr_title`/`job_id`，**故意不碰** intent 三件套），tracker 版只服务 onboarding 播种（写 intent 三件套）。列集不同、调用方不同。判断分叉前先看**调用方是否重叠、列集是否相同**；文件顶部注释往往已经写明了取舍（这里就写了），先读它再动手。

---

## 开发规则

1. **直接修改代码**，做最小可行改动（surgical change），不顺手重构无关代码。
2. **先读懂再动手**：改某字段/配置/接口前，先 grep 它的消费方（谁读它、谁写它）。看到报错不要猜着绕过——先搞清楚根因。（教训：曾因 `ProfileLoader` 要求 `name` 报错就去填值绕过，实际投递根本不用 name，是残留校验。）
3. **测试守门**：改完跑 `pytest`，绿了才算完成；涉及前端跑 `npm run build`（tsc 必须无悬空引用）。
4. **改动留痕**：每次有代码改动 → 更新 `PROGRESS.md`（progress-writer skill）；重要决策/踩坑 → worklog + 项目记忆（project-memory skill）。
5. **文档同步**：影响架构/接口的改动触发 `doc-sync`（TECHNICAL.md / README）。
6. **版本号**：见下方"版本管理"。
7. **大改动先给方案**：跨多文件的重构，先把方案/目标结构摆给用户确认，再动手。

并遵守全局原则（`~/.claude/CLAUDE.md`）：simplicity first、fail fast（内部路径不写防御性 swallow）、models judge / code decides、暴露冲突而非兼容两套、约定优先于个人偏好。

---

## 配置

配置采用**三层模型**（系统配置 / 用户偏好 / workflow 运行参数），按所有权分文件存放。完整说明、文件职责、优先级链、"设为默认"机制见 **`docs/configuration.md`**。

---

## 版本管理

版本号文件：`code/dashboard/frontend/src/version.ts`（git 追踪，构建时打包进前端）。

格式 **`X.Y.Z.N`（四段）**：

| 位 | 含义 | 何时递增 | 谁来做 |
|----|------|----------|--------|
| `X` 大版本 | 整个模块上线 / 重大重构完整交付 | 里程碑 | **动手前**我提醒，你决定 |
| `Y` 功能版 | 一个完整功能开发完成；`Z`、`N` 归零 | 功能交付 | **动手前**我提醒，你决定 |
| `Z` 补丁 | 有代码改动的普通会话（bug 修复 / 小改） | 每次有改动的会话 | 我按需提，可选 |
| `N` 构建号 | 每次 `npm run build` | 每次构建 | `scripts/build.mjs` **自动** +1，不用管 |

**规则**：
- `N`（第四段）由 `scripts/build.mjs` 在每次 `npm run build` 时**自动递增**，无需手动修改。因为每次有代码改动收尾都会 build，所以 `N` 天然记录了每一次改动——**这一层不用任何人操心**。
- `X` / `Y` 是需要人判断量级的语义位。**由我在每次动手改代码之前主动提醒你**——"这次准备做 XX，属于 [小修 / 新功能 / 整个模块]，要不要升 `X`/`Y`？"。你定完我先改 `version.ts`（升位并把更低位按需归零）再动代码；收尾 build 时 `N` 自动跟上。**你不必记得发起，我不会漏提醒。**
- `Z` 视改动是否值得单独标记，由我按需提，非强制。
- 版本号是沟通的锚点——"你用的哪个版本"比"你刷新了没有"更精确。

---

## 踩坑记录

- **改配置/字段前先查消费方**：本项目重构后残留大量死字段/断链配置（详见 `docs/configuration.md` 审计）。看到 `'X' is required` 之类报错，先 grep X 被谁消费，再决定是补值还是删校验，不要猜着填值绕过。
- **登录态在 `data/browser_profile/`**，不是 `session.json`；判断是否登录唯一权威是跑 `VerifySessionStep`。
- **React TSX/TS 中 CJK 必须 `\uXXXX`**：Windows GBK 工具链 + Prettier format-on-save 双重因素会将裸中文损坏；纯 ASCII escape 是唯一安全做法（JSX 文本节点用 `{'\uXXXX'}`，JS 字符串字面量直接转义）。
- **JSX 属性双引号字符串不处理 `\uXXXX`**：`label="中文"` 会渲染为字面量乱码。必须改为 JS 表达式 `label={'\uXXXX'}`。受影响属性：`label=`、`title=`、`aria-label=`、`placeholder=`。原因：JSX 属性双引号串是 JSX 语法层，不走 JS 字符串转义；esbuild 只对 JSX 文本节点处理转义，属性字符串不处理。
- 更多 DrissionPage / W2 相关踩坑见项目记忆（`~/.claude/projects/.../memory/`）。
