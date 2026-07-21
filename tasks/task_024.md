# Task 024 — 后端新功能：headless 参数、generate_resume 覆盖、W2/W3 详细进度事件

## 背景

前端即将迁移到 React，在迁移过程中同步集成以下新功能。本 task 只改后端，与框架无关，迁移完成后直接可用。

---

## 改动范围

### 1. `config.yaml`

在文件末尾（dashboard 段前）新增 browser 配置块：

```yaml
browser:
  headless: true  # true = 无头模式，不弹出浏览器窗口；false = 有头模式（调试用）
```

---

### 2. `orchestrator.py`

**2a. 构造函数加 `headless` 参数**

```python
def __init__(
    self,
    config: dict,
    tracker: ApplicationTracker,
    llm_clients: dict,
    dry_run: bool = False,
    emitter: Optional[ProgressEmitter] = None,
    headless: bool = True,
):
    ...
    self.headless = headless
```

**2b. `run_once()` 加 `generate_resume` 参数**

```python
def run_once(
    self,
    dry_run: bool = None,
    limit: Optional[int] = None,
    score_threshold: Optional[int] = None,
    generate_resume: Optional[bool] = None,
) -> dict:
```

在 profile 加载后，若 `generate_resume is not None`，覆盖 `self.config["apply"]["generate_resume"]`：

```python
if generate_resume is not None:
    self.config.setdefault("apply", {})["generate_resume"] = generate_resume
```

**2c. BrowserAgent 构造时传入 headless**

两处 `with BrowserAgent() as agent:` 改为：

```python
with BrowserAgent(headless=self.headless) as agent:
```

**2d. 搜索阶段详细进度事件**

在 `run_once()` 搜索每个 keyword+city 之前，emit：

```python
self.emitter.emit(ProgressEvent(
    workflow="apply",
    step="search",
    status="running",
    message=f"搜索关键词「{keyword}」城市「{city}」，URL: {url}",
))
```

**2e. score_threshold=0 快速路径的 skip 事件**

在 `_process_job()` 快速路径分支（`if self.score_threshold == 0:`）开头 emit：

```python
self.emitter.emit(ProgressEvent(
    workflow="apply",
    step="score",
    status="skipped",
    message="score_threshold=0，跳过评分与审核（全部投递）",
))
```

**2f. generate_resume=false 的 skip 事件**

在 `_process_job()` 的 `elif not generate_resume:` 分支 emit：

```python
self.emitter.emit(ProgressEvent(
    workflow="apply",
    step="resume",
    status="skipped",
    message="generate_resume=false，跳过简历生成",
))
```

**2g. 投递阶段 per-job 进度事件**

在 `run_once()` 的 job 处理循环中，每次调用 `_process_job()` 前 emit：

```python
self.emitter.emit(ProgressEvent(
    workflow="apply",
    step="apply",
    status="running",
    message=f"[{summary['processed'] + 1}/{total_pending}] 正在处理：{record.company} · {record.title}",
))
```

---

### 3. `dashboard/server.py`

**3a. `_build_orchestrator()` 加 `headless` 参数**

```python
def _build_orchestrator(headless: bool = True) -> Orchestrator:
    return Orchestrator(
        config=app.state.config,
        tracker=app.state.tracker,
        llm_clients=app.state.llm_clients,
        emitter=app.state.emitter,
        headless=headless,
    )
```

**3b. `trigger_apply` 接收 headless 和 generate_resume**

```python
headless = bool(body.get("headless", config.get("browser", {}).get("headless", True)))
generate_resume = body.get("generate_resume", None)
if generate_resume is not None:
    generate_resume = bool(generate_resume)
```

在 `_run()` 内：

```python
orch = _build_orchestrator(headless=headless)
orch.run_once(dry_run=dry_run, limit=limit, score_threshold=score_threshold, generate_resume=generate_resume)
```

**3c. `trigger_check` 接收 headless**

```python
headless = bool(body.get("headless", config.get("browser", {}).get("headless", True)))
```

在 `_run()` 内：

```python
orch = _build_orchestrator(headless=headless)
orch.check_responses(max_conversations=max_conv, days=days)
```

---

### 4. `tools/check_responses.py`

**4a. Phase 1（scan_chat_list 后）emit 脏检查统计**

当前：
```python
_emit("open_chat", "done", f"已扫描 {scan.total_convs} 条会话，{scan.unread_count} 条未读，{len(scan.needs_sync)} 条需要处理")
```

改为：
```python
skipped = scan.total_convs - len(scan.needs_sync)
_emit(
    "open_chat", "done",
    f"扫描 {scan.total_convs} 条会话，脏检查通过 {len(scan.needs_sync)} 条，跳过 {skipped} 条",
)
```

**4b. Phase 2（sync 循环）per-conv emit**

`_sync_progress` 回调当前只 emit classify running，保持不变。确认其格式为：

```python
f"处理 {idx}/{total_to_sync}：{company} — {action}"
```

格式已符合需求，不需修改。

**4c. Phase 3（legacy update）emit 汇总统计**

在 Phase 3 结束后，在现有两个 `_emit` 前统计：

```python
replied_count = sum(
    1 for r in update_records
    if r.get("new_status") in (AppStatus.RESPONDED.value, AppStatus.INTERVIEW.value, AppStatus.OFFER.value)
)
resume_req_count = sum(
    1 for r in update_records
    if r.get("new_status") == AppStatus.RESUME_REQUESTED.value
)
_emit(
    "update_status", "done",
    f"HR 回复 {replied_count} 条，简历请求 {resume_req_count} 条，状态更新 {updated_count} 条",
)
```

将原来的 `_emit("update_status", "done", ...)` 替换为上面这一段。

---

## 验证点

1. 启动服务器，在 Dashboard 触发 Apply workflow（headless=true）：
   - 不应弹出浏览器窗口
   - Metro track 的 search 节点应显示关键词 + URL 消息
   - score 节点应显示"跳过评分"（因为 score_threshold=0）
   - resume 节点应显示"跳过简历生成"（因为 generate_resume=false）
   - apply 节点应显示 [n/N] 当前公司

2. 触发 Check workflow：
   - Metro track 的 open_chat 节点应显示脏检查统计（通过 N 条，跳过 M 条）
   - classify 节点应逐条显示会话处理进度
   - update_status 节点应显示 HR 回复数、简历请求数、总更新数

3. 前端（暂时仍是旧 vanilla JS）触发时传入 `{"headless": false}`，应弹出浏览器窗口。
