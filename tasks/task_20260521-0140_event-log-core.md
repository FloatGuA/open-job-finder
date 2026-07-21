# Task: 结构化事件日志核心模块（event_log.py + API）

## 目标

新增 `services/event_log.py`，提供 per-run JSONL 日志写入；在 `server.py` 新增两个只读 API 端点供前端查询历史 run 列表和单次 run 的事件流。

## 背景

当前系统只有 Python `logging` 文本日志，没有结构化的 workflow 执行记录。每次 W1（apply）/W2（check）run 需要持久化到独立 JSONL 文件中，方便事后 debug、LLM 分析、前端可视化。

SSE/ProgressEmitter 继续负责**实时推送**，不受本 task 影响。

## 实现要求

### 1. `code/services/event_log.py`（新建）

**公共接口**：

```python
import uuid, json
from datetime import datetime, timezone
from pathlib import Path

RUNS_DIR = Path(__file__).resolve().parent.parent.parent / "logs" / "runs"

class RunLogger:
    """
    Per-run JSONL logger. One instance per workflow run.
    Thread-safe: each call holds GIL for a single f.write().
    """
    def __init__(self, workflow: str, run_id: str | None = None):
        """
        workflow: "apply" or "check"
        run_id: optional override; auto-generated if omitted
        """
        ...

    @property
    def run_id(self) -> str: ...

    def log(self, event_type: str, data: dict, *, visible: bool = True) -> None:
        """
        Append one JSON line to the run file.
        Schema: {ts, run_id, workflow, event_type, visible, data}
        ts: ISO-8601 UTC string
        """
        ...

    def close(self, status: str = "done", summary: dict | None = None) -> None:
        """Write workflow_end event and flush."""
        ...
```

**文件命名**：`logs/runs/{workflow}_{YYYYMMDD-HHmmss}_{run_id[:8]}.jsonl`

示例：`logs/runs/apply_20260521-014000_ab12cd34.jsonl`

**目录创建**：`RUNS_DIR.mkdir(parents=True, exist_ok=True)` 在模块 import 时执行。

**write 逻辑**（每条事件）：
```python
line = json.dumps({"ts": ..., "run_id": ..., "workflow": ..., "event_type": ..., "visible": ..., "data": ...}, ensure_ascii=False)
self._f.write(line + "\n")
self._f.flush()
```

**`workflow_start` 事件**：在 `__init__` 末尾自动写入，`data` 包含创建参数（workflow, run_id, started_at）。

**`workflow_end` 事件**：`close()` 写入，`data` 包含 status + summary。

**异常处理**：若写入失败只 `logger.warning`，不向上传播（RunLogger 不能阻断主流程）。

---

### 2. `code/dashboard/server.py` — 新增 API 端点

**路径常量**（已存在的 `BASE_DIR` 旁边）：
```python
RUNS_DIR = BASE_DIR / "logs" / "runs"
```

**GET /api/runs**

返回所有已完成/进行中 run 的摘要列表（倒序，最新在前）：

```json
{
  "runs": [
    {
      "run_id": "ab12cd34ef56...",
      "workflow": "apply",
      "filename": "apply_20260521-014000_ab12cd34.jsonl",
      "started_at": "2026-05-21T01:40:00Z",
      "ended_at": "2026-05-21T01:52:34Z",   // null if still running
      "status": "done",                       // "done" | "error" | "running"
      "summary": {...}                        // from workflow_end event, or null
    }
  ],
  "total": 42
}
```

实现：扫描 RUNS_DIR 下全部 `.jsonl` 文件，读取第一行（workflow_start）和最后一行（workflow_end if present），提取摘要。文件不存在时返回 `{"runs": [], "total": 0}`。

**GET /api/runs/{run_id}**

返回单次 run 的完整事件流：

```json
{
  "run_id": "ab12cd34ef56...",
  "events": [
    {"ts": "...", "event_type": "workflow_start", "visible": true, "data": {...}},
    ...
  ],
  "total": 123
}
```

实现：在 RUNS_DIR 中找文件名含 `run_id[:8]` 的文件，逐行 `json.loads`，返回全部事件数组。找不到时返回 HTTP 404。

**参数**：两个端点均支持 query param `?workflow=apply` 或 `?workflow=check` 过滤（可选，省略则返回全部）。`GET /api/runs/{run_id}` 额外支持 `?visible_only=true`（过滤 `visible=true` 的事件）。

---

## 验收标准

- [ ] `from services.event_log import RunLogger` 可成功 import
- [ ] `RunLogger("apply").log("card_scored", {"job_id": "abc"})` 在 `logs/runs/` 下生成 JSONL 文件，文件第一行是 workflow_start，第二行是 card_scored
- [ ] `RunLogger.close()` 写入 workflow_end 事件后文件不再增长
- [ ] `GET /api/runs` 返回 200 + runs 列表（文件夹空时返回 `{"runs": [], "total": 0}`）
- [ ] `GET /api/runs/{run_id}` 已知 run_id 返回 200，未知返回 404
- [ ] `pytest tests/` 全部通过（无回归）
