# Task 042 — Pipeline 接线 + 旧代码清理

## Goal

将 T030–T041 实现的 Pipeline 架构接入实际生产代码路径（main.py + dashboard/server.py），同时清理被替代的旧模块（orchestrator.py、services/event_log.py、tools/ 根层旧工具），使系统整体以新的 W1Pipeline / W2Pipeline 驱动运行。

## Background

T030–T041 实现了完整的 Tool/Step/Pipeline 三层架构（位于 pipeline/ 和 tools/biz_logic、tools/browser、tools/db、tools/llm 目录），但实际生产入口（main.py、dashboard/server.py）仍使用旧的 Orchestrator + BrowserAgent 驱动。本任务完成最后的接线工作。

相关路径（代码目录 = `code/`，以下路径均相对于 `code/`）：
- 旧入口：`orchestrator.py`、`main.py`、`dashboard/server.py`
- 新 Pipeline：`pipeline/w1/pipeline.py`（W1Pipeline）、`pipeline/w2/pipeline.py`（W2Pipeline）
- 工具注册函数：`tools/browser/w1/__init__.py`（register_w1_browser_tools）、`tools/browser/w2/__init__.py`（register_w2_browser_tools）、`tools/db/w1/__init__.py`（register_w1_tools）、`tools/db/w2/__init__.py`（register_w2_tools）
- RunLogger 适配层：`pipeline/run_logger.py`
- 进度推送：`services/progress_emitter.py`（ProgressEmitter、ProgressEvent）

## Change Scope

**In scope（必须改动）：**
- `pipeline/run_logger.py`：新增 emitter + debug 参数，log_step() 发 SSE、log_tool() 在 debug 模式发 SSE
- `services/browser_context.py`（新建）：从 BrowserAgent.start() 提取浏览器启动逻辑
- `pipeline/w1_runner.py`（新建）：组装 ToolRegistry + 注册 W1 工具 + 运行 W1Pipeline 的 run_w1() 函数
- `pipeline/w2_runner.py`（新建）：同上，run_w2()
- `dashboard/server.py`：移除 `from orchestrator import Orchestrator`；替换 `_run_apply_workflow`、`_run_check_workflow`、`_build_orchestrator`
- `main.py`：--once/--dry-run 改调 run_w1()；--check 改调 run_w2()；--chat 输出提示信息后退出
- `tools/registry.py`：删除模块级 TOOLS dict、register_tool()、get_tool()、list_tools()、initialize_tools() 函数；保留 ToolRegistry 类和 _LARGE_FIELDS

**删除以下文件（不再需要的旧模块）：**
- `orchestrator.py`
- `services/event_log.py`
- `tools/apply_job.py`
- `tools/check_responses.py`
- `tools/score_job.py`（根层；不是 tools/llm/score_job.py）
- `tools/critique_job.py`
- `tools/generate_resume.py`
- `tools/search_jobs.py`
- `tools/update_status.py`
- `tools/analyze_hr_message.py`
- `tools/schema_defs.py`
- `tests/test_orchestrator_unit.py`（测试被删代码）
- `tests/test_event_log.py`（测试被删代码）
- `tests/test_check_responses_tool.py`（测试被删代码）

**Out of scope（不要改动）：**
- `services/browser_agent.py`（保留：onboarding.py 仍依赖它）
- `services/chat_agent.py`（保留原文件，但 --chat 入口被禁用）
- `services/tracker.py`、`services/llm_client.py`、`services/profile_loader.py`、`services/prompt_manager.py`、`services/logger.py`、`schemas.py`
- `pipeline/` 下的 Step/Pipeline 实现文件（不修改，只增加 runner）
- `tools/biz_logic/`、`tools/browser/`、`tools/db/`、`tools/llm/`（不修改）

## Depends On

- task_040：pipeline/run_logger.py（RunLogger adapter）已实现，带 log_step() / log_tool() / close()
- task_041：dashboard/server.py 的 runs API 已完成（不要改动 runs 相关函数）
- task_034–039：pipeline/ 下 W1/W2 步骤和工具全部可用

## Consumes

```python
# services/progress_emitter.py
class ProgressEvent:
    workflow: str  # "w1" | "w2"
    step: str
    status: str
    message: str
    detail: dict

class ProgressEmitter:
    def subscribe(self) -> queue.Queue: ...
    def emit(self, event: ProgressEvent) -> None: ...
    def start_workflow(self, workflow: str) -> None: ...
    def finish_workflow(self, workflow: str, summary: str, status: str = "done") -> None: ...

# pipeline/run_logger.py (current — to be modified)
class RunLogger:
    def __init__(self, pipeline: str, run_id: Optional[str] = None) -> None: ...
    def log_step(self, step, scope, status, duration_ms, data=None, error=None) -> None: ...
    def log_tool(self, step, tool, scope, status, duration_ms, data=None, error=None) -> None: ...
    def log(self, event, scope, data, *, visible=True) -> None: ...
    def close(self, status, summary=None) -> None: ...

# tools/registry.py (ToolRegistry class — to be kept)
class ToolRegistry:
    def __init__(self, browser=None, db=None, llm_client=None, prompt_manager=None, logger=None) -> None: ...
    def register(self, tool: BaseTool) -> None: ...
    def call(self, name: str, **kwargs) -> ToolResult: ...
    def set_context(self, step: str, scope: dict) -> None: ...
    # .logger attribute: pipeline.run_logger.RunLogger | None

# tools/browser/w1/__init__.py
def register_w1_browser_tools(registry, browser) -> None:
    # browser: DrissionPage ChromiumPage object
    # Registers: navigate_search_url, extract_card_list, scroll_search_results,
    #            click_card_open_panel, read_panel_jd, click_apply_button, handle_apply_dialog

# tools/browser/w2/__init__.py
def register_w2_browser_tools(registry, browser) -> None:
    # Registers: navigate_to_chat_list, extract_conversation_list, scroll_chat_list,
    #            navigate_to_conversation, read_messages, send_chat_message,
    #            click_toolbar_send_resume, upload_resume_file, accept_resume_card

# tools/db/w1/__init__.py
def register_w1_tools(registry, db, llm_client, prompt_manager) -> None:
    # db: ApplicationTracker (exposes .conn: sqlite3.Connection)
    # Registers: classify_job_for_w1, score_job, decode_job_salary, upsert_application

# tools/db/w2/__init__.py
def register_w2_tools(registry, db, llm_client, prompt_manager) -> None:
    # Registers: get_conversation_states, filter_conversations, get_approved_replies,
    #            upsert_hr_conversation, write_hr_messages, update_hr_analysis,
    #            sync_application_status, mark_timeout_statuses, analyze_intent,
    #            detect_resume_request

# pipeline/w1/pipeline.py
class W1Config:
    url: str
    score_threshold: int
    dry_run: bool
    max_cards: Optional[int] = None

class W1Pipeline:
    def __init__(self, registry, profile, logger) -> None: ...
    def run(self, config: W1Config) -> dict: ...

# pipeline/w2/pipeline.py
class W2Config:
    dry_run: bool
    no_response_days: int = 14
    stale_conv_days: int = 30
    resume_path: str = ""

class W2Pipeline:
    def __init__(self, registry, profile, logger) -> None: ...
    def run(self, config: W2Config) -> dict: ...

# services/profile_loader.py
class Profile:
    name: str
    keywords: list
    cities: list
    experience: list
    salary: str
    extra_notes: str

class ProfileLoader:
    def __init__(self, profile_path: Optional[Path] = None) -> None: ...
    def load(self) -> Profile: ...

# services/boss_search_url.py
def build_search_url(profile: dict, keyword: str = None, city: str = None) -> str: ...
# profile 可接受 dict 或 Profile dataclass（通过 hasattr 判断）
```

## Implementation Requirements

### 1. `pipeline/run_logger.py`（修改）

在现有 `RunLogger.__init__` 中新增两个可选参数：
- `emitter: Optional[Any] = None`（类型为 ProgressEmitter，但用 Any 避免循环依赖）
- `debug: bool = False`

**`log_step()` 修改**：在写入 JSONL 后，若 `self._emitter` 不为 None，发送一个 ProgressEvent：
```python
ProgressEvent(
    workflow=self._pipeline,
    step=step,
    status=status,            # "successful" | "degraded" | "skipped" | "failed"
    message=f"Step {step}: {status}",
    detail=data or {},
)
```

**`log_tool()` 修改**：若 `self._emitter` 不为 None 且 `self._debug` 为 True，发送：
```python
ProgressEvent(
    workflow=self._pipeline,
    step=f"{step}/{tool}",
    status=status,
    message=f"[tool] {tool}: {status}",
    detail=data or {},
)
```

`emitter.emit(event)` 调用必须包在 `try/except Exception` 中，确保 SSE 失败不中断 pipeline。

### 2. `services/browser_context.py`（新建）

提取 `BrowserAgent.start()` 中的浏览器启动逻辑，提供两个函数：

```python
def open_browser(data_dir: Path, headless: bool = True) -> ChromiumPage:
    """打开 DrissionPage 浏览器并返回 ChromiumPage 对象。"""

def close_browser(page) -> None:
    """安全关闭 ChromiumPage。"""
```

`open_browser()` 实现步骤（完全复制 BrowserAgent.start() 的逻辑）：
1. `profile_dir = data_dir / "browser_profile"`，`profile_dir.mkdir(parents=True, exist_ok=True)`
2. 调用 `_kill_stale_chrome(profile_dir)` 杀残留 Chrome 进程（同 BrowserAgent 的 static method 实现）
3. 清理 `profile_dir / "LOCK"`、`profile_dir / "Default" / "LOCK"` 文件（`unlink()` 静默失败）
4. 构建 ChromiumOptions：
   ```python
   options = ChromiumOptions()
   options.set_user_data_path(str(profile_dir))
   options.headless(headless)
   options.set_argument("--disable-blink-features=AutomationControlled")
   options.set_argument("--no-first-run")
   options.set_argument("--no-default-browser-check")
   options.remove_argument("--enable-automation")
   options.set_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
   ```
5. `page = ChromiumPage(addr_or_opts=options)`
6. 注入 stealth JS（同 BrowserAgent：先尝试 CDP addScriptToEvaluateOnNewDocument，fallback 到 run_js）
7. 返回 page

`_kill_stale_chrome(profile_dir: Path)` 私有函数（直接复制 BrowserAgent 中的静态方法实现，Windows only）。

`close_browser(page)` 实现：`try: page.quit() except Exception: pass`

文件顶部导入：`from DrissionPage import ChromiumOptions, ChromiumPage`（不要导入 BrowserAgent）

### 3. `pipeline/w1_runner.py`（新建）

提供一个公开函数 `run_w1()`：

```python
def run_w1(
    config: dict,
    tracker,
    llm_clients: dict,
    emitter=None,
    dry_run: bool = False,
    score_threshold: int = 72,
    max_cards: Optional[int] = None,
    search_url: Optional[str] = None,
    headless: bool = True,
    debug: bool = False,
    data_dir: Optional[Path] = None,
) -> dict:
```

**实现逻辑：**
1. 计算 `data_dir`：若未提供，使用 `Path(__file__).resolve().parent.parent / "data"`
2. 加载 profile：`ProfileLoader(data_dir / "profile.yaml").load()`，失败时 return 错误 summary
3. 加载 prompt_manager：`PromptManager()`（自动寻找 prompts/ 目录）
4. 加载 `llm_client`（ScoreJob 和 analysis 用）：优先 `llm_clients.get("scoring")`
5. 构建 search_url：若 `search_url` 未提供，调用 `build_search_url(profile, keyword=profile.keywords[0] if profile.keywords else None, city=profile.cities[0] if profile.cities else None)`；注意：`build_search_url` 在 `services/boss_search_url.py`，接受 dict 或 Profile（见 Consumes 说明，若接受 dict 则传 `profile.__dict__` 或直接传 Profile）
6. 若 `emitter` 不为 None，调用 `emitter.start_workflow("w1")`
7. 打开浏览器：`from services.browser_context import open_browser, close_browser; page = open_browser(data_dir, headless=headless)`
8. 创建 ToolRegistry：
   ```python
   registry = ToolRegistry(browser=page, db=tracker, llm_client=llm_client, prompt_manager=prompt_manager)
   ```
9. 创建 RunLogger：
   ```python
   logger = RunLogger(pipeline="w1", emitter=emitter, debug=debug)
   registry.logger = logger
   ```
10. 注册工具：
    ```python
    register_w1_browser_tools(registry, page)
    register_w1_tools(registry, tracker, llm_client, prompt_manager)
    ```
11. 运行 Pipeline：
    ```python
    pipeline = W1Pipeline(registry=registry, profile=profile, logger=logger)
    config_obj = W1Config(url=search_url, score_threshold=score_threshold, dry_run=dry_run, max_cards=max_cards)
    summary = pipeline.run(config_obj)
    ```
12. 关闭浏览器：`close_browser(page)`（放在 `finally` 块）
13. 若 `emitter` 不为 None，调用 `emitter.finish_workflow("w1", str(summary), status="done")`
14. 返回 summary

异常处理：整个 pipeline.run() 调用放在 try/finally 中，finally 执行 close_browser。若 pipeline.run() 抛出异常，logger.close("failed") 并 re-raise。

### 4. `pipeline/w2_runner.py`（新建）

提供一个公开函数 `run_w2()`：

```python
def run_w2(
    config: dict,
    tracker,
    llm_clients: dict,
    emitter=None,
    dry_run: bool = False,
    max_conversations: int = 200,
    no_response_days: int = 14,
    stale_conv_days: int = 30,
    headless: bool = True,
    debug: bool = False,
    data_dir: Optional[Path] = None,
) -> dict:
```

**实现逻辑（类似 run_w1，差异点）：**
1. 同样加载 profile 和 prompt_manager
2. `llm_client`：优先 `llm_clients.get("analysis") or llm_clients.get("scoring")`
3. 若 emitter 不为 None，调用 `emitter.start_workflow("w2")`
4. 打开浏览器（同 W1）
5. 创建 ToolRegistry（同 W1）
6. 创建 RunLogger：`RunLogger(pipeline="w2", emitter=emitter, debug=debug)`
7. 注册工具：
   ```python
   register_w2_browser_tools(registry, page)
   register_w2_tools(registry, tracker, llm_client, prompt_manager)
   ```
8. 运行 Pipeline：
   ```python
   pipeline = W2Pipeline(registry=registry, profile=profile, logger=logger)
   config_obj = W2Config(dry_run=dry_run, no_response_days=no_response_days, stale_conv_days=stale_conv_days)
   summary = pipeline.run(config_obj)
   ```
9. 关闭浏览器（finally 块）
10. 调用 `emitter.finish_workflow("w2", str(summary), status="done")`
11. 返回 summary

### 5. `dashboard/server.py`（修改）

**移除：**
- 第 22 行的 `from orchestrator import Orchestrator`（顶层 import）
- `_build_orchestrator()` 函数整体

**替换 `_run_apply_workflow(params)`：**
```python
def _run_apply_workflow(params: dict[str, Any]) -> str:
    from pipeline.w1_runner import run_w1
    _initialize_state()
    headless = bool(params.get("headless", True))
    debug = bool(params.get("debug", False))
    apply_limit_raw = params.get("apply_limit", 0)
    max_cards = int(apply_limit_raw) if apply_limit_raw and int(apply_limit_raw) > 0 else None
    run_w1(
        config=app.state.config,
        tracker=app.state.tracker,
        llm_clients=app.state.llm_clients,
        emitter=getattr(app.state, "emitter", None),
        dry_run=bool(params.get("dry_run", False)),
        score_threshold=int(params.get("score_threshold", 60)),
        max_cards=max_cards,
        search_url=params.get("search_url") or None,
        headless=headless,
        debug=debug,
        data_dir=DATA_DIR,
    )
    return "apply 工作流完成"
```

**替换 `_run_check_workflow(params)`：**
```python
def _run_check_workflow(params: dict[str, Any]) -> str:
    from pipeline.w2_runner import run_w2
    _initialize_state()
    headless = bool(params.get("headless", True))
    debug = bool(params.get("debug", False))
    run_w2(
        config=app.state.config,
        tracker=app.state.tracker,
        llm_clients=app.state.llm_clients,
        emitter=getattr(app.state, "emitter", None),
        dry_run=bool(params.get("dry_run", False)),
        max_conversations=int(params.get("max_conversations", 200)),
        no_response_days=int(params.get("no_response_days", 14)),
        headless=headless,
        debug=debug,
        data_dir=DATA_DIR,
    )
    return "check 工作流完成"
```

**注意：** 不修改 runs API（GET /api/runs、GET /api/runs/{run_id}）及相关函数，它们在 T041 已完成。

### 6. `main.py`（修改）

**移除：**
- `from orchestrator import Orchestrator` 的 import（在函数内部，需要找到并删除）
- `from scheduler import start_scheduler` 的 import 及调用（暂时禁用调度器，参见下方说明）
- 构建 orchestrator 的代码块

**更新 `main()` 函数中的条件分支：**

```python
def main():
    parser = argparse.ArgumentParser(description="OpenJobFinder")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--onboarding", action="store_true")
    parser.add_argument("--setup-profile", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--chat", action="store_true")
    parser.add_argument("--debug", action="store_true", help="Enable tool-level SSE events")
    args = parser.parse_args()

    logger = get_orchestrator_logger()
    config = load_config("config.yaml")

    checker = OnboardingChecker(config=config)
    status = checker.check_all()

    if args.onboarding or not status["session"]:
        checker.run_interactive_setup()
        return

    if args.setup_profile:
        checker.run_setup_profile()
        return

    if args.chat:
        print("--chat mode is temporarily unavailable (pending migration to new pipeline architecture).")
        return

    from pipeline.w1_runner import run_w1
    from pipeline.w2_runner import run_w2
    from services.tracker import ApplicationTracker

    tracker = ApplicationTracker()
    llm_clients = {
        "scoring": build_llm_client(config, "scoring"),
        "generation": build_llm_client(config, "generation"),
        "analysis": build_llm_client(config, "analysis"),
    }

    if args.once or args.dry_run:
        dry_run = args.dry_run or config.get("apply", {}).get("dry_run", False)
        if _try_delegate_to_server("apply", dry_run=dry_run):
            return
        summary = run_w1(
            config=config,
            tracker=tracker,
            llm_clients=llm_clients,
            dry_run=dry_run,
            score_threshold=config.get("apply", {}).get("score_threshold", 72),
            debug=args.debug,
        )
        print(f"\nRun complete: {summary}")
    elif args.check:
        if _try_delegate_to_server("check"):
            return
        summary = run_w2(
            config=config,
            tracker=tracker,
            llm_clients=llm_clients,
            debug=args.debug,
        )
        print(f"\nCheck complete: {summary}")
    else:
        print("Scheduler mode not yet available in new pipeline. Use --once or --check.")
```

注：`--chat` 输出提示后退出，调度器模式（无 flag 默认）同样输出提示。保留 `_try_delegate_to_server` 函数不改。

### 7. `tools/registry.py`（修改）

**删除以下内容：**
- 模块顶层 `TOOLS: dict[str, ToolProtocol] = {}` 变量声明
- `register_tool(tool)` 函数
- `get_tool(name)` 函数
- `list_tools()` 模块级函数（注意：ToolRegistry 类内部也有同名方法，保留类方法，只删模块级函数）
- `initialize_tools(...)` 函数（包括整个函数体）

**保留以下内容：**
- `import time` 等必要的 import 语句
- `_LARGE_FIELDS` frozenset
- `ToolRegistry` 类（完整保留，包括 register、get、list_tools、set_context、call 方法）

删除后，`tools/registry.py` 只包含：`_LARGE_FIELDS`、`ToolRegistry` 类。

### 8. 删除文件

删除以下文件（直接删除，不要修改）：
```
orchestrator.py
services/event_log.py
tools/apply_job.py
tools/check_responses.py
tools/score_job.py
tools/critique_job.py
tools/generate_resume.py
tools/search_jobs.py
tools/update_status.py
tools/analyze_hr_message.py
tools/schema_defs.py
tests/test_orchestrator_unit.py
tests/test_event_log.py
tests/test_check_responses_tool.py
```

## Test Requirements

- Automated tests: no（本 task 不需要新增测试，但要确保现有测试通过）
- 执行 `pytest tests/ -x --ignore=tests/test_run_logger_and_registry.py` 验证：
  - 删除文件对应的测试已移除（不会报 ImportError）
  - 其余测试不受影响
- 不需要真实浏览器的端对端测试（run_w1/run_w2 需要真实 Boss直聘 环境，不在自动化范围内）

## Acceptance Criteria

- [ ] `python -c "from pipeline.w1_runner import run_w1; print('ok')"` 成功
- [ ] `python -c "from pipeline.w2_runner import run_w2; print('ok')"` 成功
- [ ] `python -c "from dashboard.server import app; print('ok')"` 成功（server 不再 import orchestrator）
- [ ] `python main.py --help` 输出包含 `--debug` 参数
- [ ] `pytest tests/ -x` 通过（或仅有与本 task 无关的预存失败）
- [ ] `orchestrator.py` 文件不存在（已删除）
- [ ] `services/event_log.py` 文件不存在（已删除）
- [ ] `tools/registry.py` 中不存在 `initialize_tools` 函数
- [ ] `services/browser_context.py` 文件存在且可 import

## Ambiguity Protocol

如果任何需求不清晰或无法实现：

1. 按最合理的解释实现
2. 不要静默跳过或绕过问题
3. 在 `report.md` 的 **Deviations** 章节列出每个歧义点、采用了什么假设、有哪些备选解释、以及为什么做出这个选择
