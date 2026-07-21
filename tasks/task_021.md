# Task 021 — 停止按钮修复（Apply + Check Workflow）

## 背景

Dashboard 的停止按钮（POST /api/workflow/stop）点击后设置
`emitter.stop_requested = True`，但两个 workflow 都没有正确响应这个信号：

**Apply workflow 无效原因：**
- `stop_requested` 只在处理循环（job 与 job 之间，orchestrator.py:292）检查一次
- 搜索阶段（keyword × city 双层循环 + 浏览器操作）没有任何检查点
- 若搜索后无新 job，pending 为空，处理循环不执行，`finish_workflow` 正常完成
  并重置 `stop_requested=False`，用户看不到任何效果
- 即使 break 了，后续调用的是"完成"消息的 `finish_workflow`，前端无法区分
  "正常结束"和"手动停止"

**Check workflow 无效原因：**
- `sync_conversations` 逐会话处理，没有 `stop_requested` 检查点
- 整个 check_tool.execute() 是一个不可打断的黑盒调用

---

## 修改范围

- `orchestrator.py`
- `tools/check_responses.py`
- `services/browser_agent.py`

---

## 详细要求

### 1. Apply workflow 停止检查（`orchestrator.py`）

在 `run_once()` 的搜索阶段，关键字循环和城市循环入口各加一个停止检查：

```python
for keyword in keywords:
    if self.emitter.stop_requested:
        break
    for city in cities:
        if self.emitter.stop_requested:
            break
        # ... 原有搜索逻辑 ...
```

在处理循环之前，也加一个检查（避免搜索刚结束就被绕过）：

```python
if not self.emitter.stop_requested:
    for record in pending:
        if self.emitter.stop_requested:
            ...
            break
        # ... 原有处理逻辑 ...
```

在 `run_once()` 结束时，根据 `stop_requested` 状态选择不同的 `finish_workflow`：

```python
if self.emitter.stop_requested:
    self.emitter.finish_workflow(
        "apply",
        f"已停止：搜索 {summary['searched']}，投递 {summary['applied']} 个",
        status="stopped",
    )
else:
    self.emitter.finish_workflow(
        "apply",
        f"完成：搜索 {summary['searched']}，投递 {summary['applied']} 个",
    )
```

注意：`finish_workflow` 会重置 `stop_requested=False`，所以必须在调用之前读取该值。

### 2. Check workflow 停止检查

#### 2a. `services/browser_agent.py` — `sync_conversations`

新增 `stop_check=None` 参数（callable，无参数，返回 bool）：

```python
def sync_conversations(
    self,
    items: list,
    tracker,
    resume_path=None,
    aggressive=False,
    progress_callback=None,
    stop_check=None,   # ← 新增
) -> list:
    ...
    for i, item in enumerate(items):
        if stop_check and stop_check():
            logger.info("sync_conversations: stop requested, halting at %d/%d", i, len(items))
            break
        # ... 原有逻辑 ...
```

#### 2b. `tools/check_responses.py` — `execute()`

在 `execute()` 中构造 `stop_check` 回调并传给 `sync_conversations`：

```python
_emitter = emitter  # captured from execute() parameter

def _stop_check() -> bool:
    return bool(_emitter and _emitter.stop_requested)

synced_convs = browser_agent.sync_conversations(
    scan.needs_sync,
    self.tracker,
    resume_path=attachment_resume,
    aggressive=self.aggressive_resume,
    progress_callback=_sync_progress,
    stop_check=_stop_check,   # ← 新增
)
```

#### 2c. `orchestrator.py` — `check_responses()`

`check_tool.execute()` 返回后，检查是否被中断，使用不同的 `finish_workflow`：

```python
result = self.check_tool.execute(...)
stopped = self.emitter.stop_requested
total_convs = int(result.get("total_convs", result.get("checked", 0)))
updated = int(result.get("updated", 0))

if result.get("error"):
    self.emitter.finish_workflow("check", "执行中断", status="error")
elif stopped:
    self.emitter.finish_workflow(
        "check",
        f"已停止：处理 {total_convs} 条，更新 {updated} 条",
        status="stopped",
    )
else:
    self.emitter.finish_workflow(
        "check",
        f"完成：处理 {total_convs} 条，更新 {updated} 条",
    )
```

### 3. 不需要修改前端

前端 `app.js` 已有处理 `step === 'stop' && status === 'stopping'` 的逻辑（禁用停止按钮）。
`finish_workflow` 发出的 `step="done"` 事件会触发前端的 workflow 完成逻辑，重置 UI。
前端不需要区分 "stopped" vs "done"——工作流结束就重置按钮状态，这已经正确。

---

## 验收标准

1. `python -m py_compile orchestrator.py` 通过
2. `python -m py_compile tools/check_responses.py` 通过
3. `python -m py_compile services/browser_agent.py` 通过
4. Apply workflow：点击停止后，搜索阶段在当前 keyword/city 迭代结束后停止，
   不继续下一个关键词
5. Apply workflow：`finish_workflow` 在停止时传入 `status="stopped"` 和含"已停止"的消息
6. Check workflow：点击停止后，`sync_conversations` 在当前会话处理完成后停止，
   不继续下一条会话
7. Check workflow：`finish_workflow` 在停止时传入 `status="stopped"` 和含"已停止"的消息

---

## 不需要做的事

- 不修改前端 JS/HTML
- 不修改 `progress_emitter.py`
- 不修改 Dashboard stop 端点
- 不在 `_process_job()` 内部加停止检查（粒度不需要这么细）
