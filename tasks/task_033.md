# Task 033 — Memory Interface

## Goal
封装 Agent 静态知识读取层（ProfileLoader），并为 Reflection Memory 留扩展接口（stub 实现，不做实际功能）。

## Background
现有 profile.yaml 由 orchestrator.py 直接读取，格式验证分散。本 Task 将 profile 读取封装为 ProfileLoader，统一字段类型和默认值处理。

Reflection Memory（Agent 从历史经验中学习）是长期规划，当前 pipeline 完全由 Step 控制，不需要实现。本 Task 只建接口（抽象基类 + NullReflectionMemory）和设计意图说明，为未来扩展预留位置。

## Implementation Requirements

### 1. `code/services/profile_loader.py`

```python
@dataclass
class Profile:
    name: str
    keywords: List[str]          # 职位关键词
    cities: List[str]            # 目标城市
    experience: List[str]        # 工作经验要求（如 "1-3年"）
    salary: str                  # 薪资要求（如 "15-25k"）
    extra_notes: str             # 附加说明（可为空字符串）

class ProfileLoader:
    def __init__(self, profile_path: Optional[Path] = None)
    # 默认路径：data/profile.yaml（相对项目根目录）

    def load(self) -> Profile
    # 读取并解析 profile.yaml
    # 字段缺失时给合理默认值（keywords=[] / cities=[] / experience=[] / salary="" / extra_notes=""）
    # name 缺失或为空时抛 ValueError（name 是必填项）
    # 文件不存在时抛 FileNotFoundError
```

### 2. `code/memory/base.py`

```python
from abc import ABC, abstractmethod
from typing import Optional, Any

class ReflectionMemory(ABC):
    @abstractmethod
    def read(self, query: str) -> Optional[str]: ...

    @abstractmethod
    def write(self, key: str, value: Any) -> None: ...

    @abstractmethod
    def summarize(self) -> str: ...
```

### 3. `code/memory/null_memory.py`

```python
class NullReflectionMemory(ReflectionMemory):
    def read(self, query: str) -> None:
        return None

    def write(self, key: str, value: Any) -> None:
        pass

    def summarize(self) -> str:
        return ""
```

### 4. `code/memory/design.md`

说明 Reflection Memory 的设计意图和预期实现方向（不是功能文档，是给未来实现者的设计备忘）。包含：
- 为什么需要 Reflection Memory（从投递历史中学习，调整评分权重）
- 当前状态：NullReflectionMemory（no-op），pipeline 不调用
- 预期实现：读写 SQLite 或 YAML，存储每次 run 的关键决策和结果
- 实现条件：需要先积累一定量的运行数据，当前不具备

### 5. `code/memory/__init__.py`

空文件，使 memory 成为合法 Python package。

## Acceptance Criteria

- [ ] `ProfileLoader().load()` 在 data/profile.yaml 存在时返回 Profile 对象，name/keywords/cities 字段正确
- [ ] profile.yaml 缺少 keywords 时，Profile.keywords 为 `[]`（不报错）
- [ ] profile.yaml 不存在时抛 FileNotFoundError
- [ ] `NullReflectionMemory().read("anything")` 返回 None 不报错
- [ ] `NullReflectionMemory().write("k", "v")` 不报错
- [ ] code/memory/design.md 存在且说明了"当前 no-op，待实现"

## Reference
- data/profile.yaml（现有字段结构，读取并对照）
- code/schemas.py（现有 Profile 相关定义，避免重复定义）
- code/orchestrator.py（查看当前如何读取 profile，理解使用场景）
