# Task 031 — 核心框架

## Goal
新建三个基础设施组件：Step 基类、RunLogger（JSONL 日志写入器）、Tool 基础设施（ToolResult + BaseTool + ToolRegistry）。后续所有 Task 都依赖这里的类型和接口。

## Background
现有 `code/services/event_log.py` 是旧的日志系统，将在本 Task 中被新的 RunLogger 替代。现有 `code/tools/` 下的工具是平铺的无层次结构，本 Task 建立 BaseTool 抽象和 ToolRegistry 统一管理。

本 Task 只实现基础设施能力，不要求接入所有 Step/Tool（全量埋点接入是 T040 的工作）。完成标准：RunLogger 可用、ToolRegistry 可用，带最小验证测试。

## Implementation Requirements

### 1. `code/pipeline/base.py`

```python
from enum import Enum
from dataclasses import dataclass
from typing import Optional

class StepStatus(Enum):
    SUCCESSFUL = "successful"
    DEGRADED   = "degraded"
    SKIPPED    = "skipped"
    FAILED     = "failed"

@dataclass
class StepOutput:
    status: StepStatus
    error: Optional[str] = None
```

### 2. `code/services/run_logger.py`

RunLogger：per-run JSONL 写入器，写入 `logs/runs/{run_id}.jsonl`。

```python
class RunLogger:
    def __init__(self, run_id: str, pipeline: str)

    def log_run_start(self) -> None
    def log_run_end(self, status: str, summary: dict) -> None
    def log_step(self, step: str, scope: dict, status: str,
                 duration_ms: int, data: dict, error: Optional[str]) -> None
    def log_tool(self, step: str, tool: str, scope: dict, status: str,
                 duration_ms: int, data: dict, error: Optional[str]) -> None
    def log_business_event(self, event: str, scope: dict, data: dict) -> None
```

每条写入的 JSONL 行格式严格对照 design/logging.md：
- 公共字段：event / run_id / ts（ISO 8601）
- step 条目额外字段：pipeline / step / scope / status / duration_ms / data / error
- tool 条目额外字段：step / tool / scope / status / duration_ms / data / error
- business event 无 status / duration_ms
- run_start / run_end 格式见 design/logging.md「Run 级别条目」

`logs/runs/` 目录不存在时自动创建。写入使用追加模式，线程安全（文件锁或 per-run 单写入器保证）。

**移除旧引用**：删除 `code/services/event_log.py` 中的 RunLogger 类（或整个文件，视现有内容而定），更新所有 import 到新路径。

### 3. `code/tools/base.py`

```python
from dataclasses import dataclass, field
from typing import Any, Optional
from abc import ABC, abstractmethod

@dataclass
class ToolResult:
    ok: bool
    data: dict = field(default_factory=dict)
    error: Optional[str] = None

class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict   # JSON Schema，供未来 LLM 枚举工具用

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult: ...
```

### 4. `code/tools/registry.py`

```python
class ToolRegistry:
    def __init__(self, browser=None, db=None, llm_client=None,
                 prompt_manager=None, logger=None)

    def register(self, tool: BaseTool) -> None
    def get(self, name: str) -> BaseTool          # 未找到抛 KeyError
    def list_tools(self) -> List[str]
    def call(self, name: str, **kwargs) -> ToolResult  # registry.get(name).execute(**kwargs)
```

ToolRegistry 在初始化时持有共享资源引用（browser / db / llm_client / prompt_manager / logger），后续 Tool 从 registry 构造时注入所需资源。具体注入方式由 T034~T038 实现时决定。

## Acceptance Criteria

- [ ] 可以实例化 ToolRegistry，register 一个 mock Tool，`registry.call(name)` 返回 ToolResult(ok=True)
- [ ] RunLogger 写一条 log_tool 后，`logs/runs/` 下出现对应 JSONL 文件
- [ ] JSONL 文件中的条目包含 event / run_id / tool / status / ts 字段
- [ ] 条目格式与 design/logging.md 「Tool 级别条目」一致
- [ ] 旧 event_log.py 中的 RunLogger 相关引用已清除（无 ImportError）

## Reference
- design/logging.md（全部条目格式规范）
- code/services/event_log.py（旧系统，读懂后废弃）
