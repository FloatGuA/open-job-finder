# Task 017 — Dashboard Workflow 触发按钮 + 进度可视化

## 背景与目标

Dashboard 目前只能被动展示投递状态，用户需要到终端手动运行 `python main.py --once` 或 `--check`。本 task 将两个核心 workflow 的触发能力直接内置到 Dashboard：

1. **触发按钮**：Apply（搜索+投递）、Check（扫描回复），参数可在界面上调整后再触发
2. **进度可视化**：类地铁线路图的步骤追踪，实时显示当前执行到哪一步、每步的决策结果

通信方式选用 **SSE（Server-Sent Events）**：后端主动推送进度事件，前端监听并渲染，无需 WebSocket 握手，与 FastAPI 天然兼容。

---

## 修改清单

### 1. `services/progress_emitter.py`（新建）

全局进度发射器，Orchestrator 和 Tools 在执行中调用它发出事件；SSE endpoint 订阅并转发。

```python
import queue, threading, time
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class ProgressEvent:
    workflow: str          # "apply" | "check"
    step: str              # 步骤 ID，见下方定义
    status: str            # "running" | "done" | "skipped" | "error"
    message: str           # 人类可读描述，如 "已评分 12/30，通过 5 个"
    detail: Optional[dict] = field(default_factory=dict)  # 附加数据（可选）
    ts: float = field(default_factory=time.time)

class ProgressEmitter:
    """线程安全的进度事件总线。单例，挂在 app.state.emitter 上。"""

    def __init__(self):
        self._queues: list[queue.Queue] = []
        self._lock = threading.Lock()
        self.current_workflow: Optional[str] = None

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=200)
        with self._lock:
            self._queues.append(q)
        return q

    def unsubscribe(self, q: queue.Queue) -> None:
        with self._lock:
            self._queues = [x for x in self._queues if x is not q]

    def emit(self, event: ProgressEvent) -> None:
        with self._lock:
            for q in self._queues:
                try:
                    q.put_nowait(event)
                except queue.Full:
                    pass  # 慢速消费者直接丢弃旧事件

    def start_workflow(self, workflow: str) -> None:
        self.current_workflow = workflow
        self.emit(ProgressEvent(workflow=workflow, step="start", status="running",
                                message=f"开始 {workflow} workflow"))

    def finish_workflow(self, workflow: str, summary: str) -> None:
        self.current_workflow = None
        self.emit(ProgressEvent(workflow=workflow, step="done", status="done",
                                message=summary))
```

**Apply workflow 步骤 ID（按顺序）**：
`start` → `search` → `score` → `critique` → `resume` → `apply` → `done`

**Check workflow 步骤 ID（按顺序）**：
`start` → `open_chat` → `classify` → `update_status` → `send_attachment` → `done`

---

### 2. `orchestrator.py` — 注入 ProgressEmitter 发出事件

在 `run_once()` 和 `check_responses()` 的关键节点调用 `emitter.emit()`：

**`run_once()` 中注入点**：
- 开始：`emitter.start_workflow("apply")`
- 搜索完成：`emitter.emit(ProgressEvent("apply", "search", "done", f"搜索到 {len(jobs)} 个职位"))`
- 每条 job 评分后：`emitter.emit(ProgressEvent("apply", "score", "running", f"已评分 {i}/{total}，通过 {passed} 个"))`
- Critic 审核后：`emitter.emit(ProgressEvent("apply", "critique", "running", f"已审核 {i}/{total}，通过 {approved} 个"))`
- 简历生成后：`emitter.emit(ProgressEvent("apply", "resume", "running", f"已生成简历 {i}/{approved} 个"))`
- 每次投递后：`emitter.emit(ProgressEvent("apply", "apply", "running", f"已投递 {applied}/{approved} 个"))`
- 完成：`emitter.finish_workflow("apply", f"完成：搜索 {total}，投递 {applied} 个")`

**`check_responses()` 中注入点**：
- 开始：`emitter.start_workflow("check")`
- 打开聊天列表后：`emitter.emit(ProgressEvent("check", "open_chat", "done", f"加载 {n} 条会话"))`
- 每条分类后：`emitter.emit(ProgressEvent("check", "classify", "running", f"已处理 {i}/{n}"))`
- 更新状态后：`emitter.emit(ProgressEvent("check", "update_status", "running", f"更新 {updated} 条"))`
- 发送附件后（如有）：`emitter.emit(ProgressEvent("check", "send_attachment", "done", f"发送 {sent} 份附件简历"))`
- 完成：`emitter.finish_workflow("check", f"完成：处理 {n} 条，更新 {updated} 条")`

Orchestrator `__init__` 接受可选的 `emitter: Optional[ProgressEmitter] = None` 参数；若为 None，则使用 no-op stub（避免非 Dashboard 路径依赖）：

```python
class _NoopEmitter:
    def emit(self, event): pass
    def start_workflow(self, w): pass
    def finish_workflow(self, w, s): pass
    current_workflow = None
```

---

### 3. `dashboard/server.py` — 新增 3 个 API

#### `GET /api/workflow/stream`（SSE）

```python
from sse_starlette.sse import EventSourceResponse  # pip install sse-starlette

@app.get("/api/workflow/stream")
async def workflow_stream(request: Request):
    emitter: ProgressEmitter = request.app.state.emitter
    q = emitter.subscribe()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event: ProgressEvent = q.get_nowait()
                    yield {
                        "event": event.step,
                        "data": json.dumps({
                            "workflow": event.workflow,
                            "step": event.step,
                            "status": event.status,
                            "message": event.message,
                            "detail": event.detail,
                            "ts": event.ts,
                        })
                    }
                except queue.Empty:
                    await asyncio.sleep(0.2)
        finally:
            emitter.unsubscribe(q)

    return EventSourceResponse(event_generator())
```

#### `POST /api/workflow/apply`

```python
@app.post("/api/workflow/apply")
async def trigger_apply(body: dict, background_tasks: BackgroundTasks):
    """
    body 可选参数：
    {
      "dry_run": false,
      "limit": 30,           # 本次最多处理职位数
      "score_threshold": 60  # 覆盖 config.yaml 中的阈值（仅本次）
    }
    """
    # 若已有 workflow 在运行，返回 409
    if app.state.emitter.current_workflow:
        raise HTTPException(409, detail="已有 workflow 正在运行")

    dry_run = body.get("dry_run", False)
    limit = int(body.get("limit", config.get("job_search", {}).get("limit_per_run", 30)))
    score_threshold = int(body.get("score_threshold",
                                   config.get("apply", {}).get("score_threshold", 60)))

    def _run():
        orch = Orchestrator(config, emitter=app.state.emitter)
        orch.run_once(dry_run=dry_run, limit=limit, score_threshold=score_threshold)

    background_tasks.add_task(_run)
    return {"status": "started", "dry_run": dry_run}
```

#### `POST /api/workflow/check`

```python
@app.post("/api/workflow/check")
async def trigger_check(body: dict, background_tasks: BackgroundTasks):
    """
    body 可选参数：
    {
      "max_conversations": 30,
      "days": 7
    }
    """
    if app.state.emitter.current_workflow:
        raise HTTPException(409, detail="已有 workflow 正在运行")

    max_conv = int(body.get("max_conversations",
                            config.get("schedule", {}).get("check_responses_max", 30)))
    days = int(body.get("days",
                        config.get("schedule", {}).get("check_responses_days", 7)))

    def _run():
        orch = Orchestrator(config, emitter=app.state.emitter)
        orch.check_responses(max_conversations=max_conv, days=days)

    background_tasks.add_task(_run)
    return {"status": "started"}
```

#### `GET /api/workflow/status`

```python
@app.get("/api/workflow/status")
def workflow_status():
    """返回当前是否有 workflow 在运行。"""
    return {"running": app.state.emitter.current_workflow}
```

在 `startup` 事件中初始化：

```python
@app.on_event("startup")
async def startup():
    app.state.emitter = ProgressEmitter()
```

---

### 4. `dashboard/static/app.js` — 触发按钮 + 进度面板

#### 新增页面区块：`workflow` section

在 `index.html` 的 `<main>` 中加入 `<section id="page-workflow" class="page hidden">`，导航栏加对应入口。

**触发按钮区**（两列卡片布局，左 Apply 右 Check）：

Apply 卡片参数：
- `limit`：本次最多职位数（number input，默认 30，范围 1–200）
- `score_threshold`：评分阈值（number input，默认读取 config，范围 0–100）
- `dry_run`：演练模式（checkbox）
- 按钮："开始投递"（primary）

Check 卡片参数：
- `max_conversations`：扫描条数（number input，默认 30，范围 1–200）
- `days`：最近 N 天（number input，默认 7，范围 1–30）
- 按钮："扫描回复"（primary）

**进度面板**（触发后展开）：地铁线路图样式。

Apply 线路（7 个站点）：
```
[开始] → [搜索] → [评分] → [审核] → [生成简历] → [投递] → [完成]
```

Check 线路（6 个站点）：
```
[开始] → [打开聊天] → [消息分类] → [更新状态] → [发送附件] → [完成]
```

每个站点显示：
- 状态圆圈：灰色（待执行）/ 蓝色旋转（执行中）/ 绿色勾（完成）/ 红色叉（出错）/ 黄色（跳过）
- 站名
- 进度文字（SSE 推送的 `message` 字段）

SSE 连接逻辑（JavaScript）：
```javascript
function startWorkflowStream() {
    const evtSource = new EventSource('/api/workflow/stream');
    evtSource.addEventListener('message', (e) => {
        const data = JSON.parse(e.data);
        updateProgressStep(data.workflow, data.step, data.status, data.message);
    });
    evtSource.onerror = () => evtSource.close();
    return evtSource;
}
```

`updateProgressStep(workflow, step, status, message)` 根据 step 找到对应站点节点，更新 class 和文字。

---

### 5. `dashboard/static/style.css` — 地铁线路图样式

```css
/* 触发卡片区 */
.workflow-trigger-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--sp-4);
}

/* 进度面板 */
.metro-track {
    display: flex;
    align-items: flex-start;
    gap: 0;
    padding: var(--sp-4) 0;
    overflow-x: auto;
}
.metro-station {
    display: flex;
    flex-direction: column;
    align-items: center;
    flex: 1;
    min-width: 80px;
    position: relative;
}
/* 站点间连线 */
.metro-station:not(:last-child)::after {
    content: '';
    position: absolute;
    top: 14px;
    left: 50%;
    width: 100%;
    height: 2px;
    background: var(--border-subtle);
}
.metro-station.done::after { background: var(--color-success); }
.metro-dot {
    width: 28px; height: 28px;
    border-radius: 50%;
    background: var(--color-bg-card-2);
    border: 2px solid var(--border-subtle);
    display: flex; align-items: center; justify-content: center;
    font-size: 12px; z-index: 1;
    transition: all 0.3s;
}
.metro-station.running  .metro-dot { border-color: var(--color-accent); animation: spin 1s linear infinite; }
.metro-station.done     .metro-dot { background: var(--color-success); border-color: var(--color-success); color: #fff; }
.metro-station.error    .metro-dot { background: var(--color-danger);  border-color: var(--color-danger);  color: #fff; }
.metro-station.skipped  .metro-dot { opacity: 0.4; }
.metro-label { font-size: 11px; color: var(--color-text-3); margin-top: 6px; text-align: center; }
.metro-msg   { font-size: 11px; color: var(--color-text-2); margin-top: 3px; text-align: center; max-width: 90px; }
@keyframes spin { to { transform: rotate(360deg); } }
```

---

## 依赖

```
sse-starlette>=1.6.1
```

在 `requirements.txt` 末尾追加此依赖。

---

## 验收标准

1. Dashboard 导航栏新增"工作流"页面入口，点击可进入
2. Apply 卡片参数（limit/score_threshold/dry_run）可调整，点击"开始投递"后按钮变为不可用并显示"运行中..."
3. Check 卡片参数（max_conversations/days）可调整，点击"扫描回复"后同上
4. 若已有 workflow 在运行，两个按钮均不可点击，页面提示"当前有任务正在运行"
5. 触发后进度面板展开，线路图上各站点按 SSE 事件实时更新颜色和文字
6. Workflow 完成后（step=done）进度面板显示"完成"并展示汇总信息，按钮恢复可用
7. SSE 断开（页面关闭/网络中断）时，后端正在执行的 workflow 不中断
8. `Orchestrator` 在非 Dashboard 路径（CLI）下运行时不依赖 `ProgressEmitter`（no-op stub 正常工作）
9. `--dry-run` 参数正确传递，dry run 下投递步骤显示"演练模式，跳过实际投递"
