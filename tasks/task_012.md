# Task 012 — Tool Schema 统一 + Registry 完整注册

## 背景

当前 tool 架构存在两个问题：
1. `ToolProtocol` 只有 `name`/`description`/`execute()`，没有输入输出契约
2. `registry.py` 的 `initialize_tools()` 只注册了 3 个 tool（score、critique、update），
   其余 4 个（search_jobs、apply_job、generate_resume、check_responses）在 orchestrator
   里直接实例化，绕过了注册表

本 task 做两件事：
- 给所有 tool 加 `input_schema` / `output_schema` 类属性（OpenAI function calling 格式）
- 把所有 tool 都注册进 registry，orchestrator 改为通过 registry 取用

---

## 修改清单

### 1. `protocols.py` — 扩展 ToolProtocol

在 `ToolProtocol` 中新增两个属性：

```python
@runtime_checkable
class ToolProtocol(Protocol):
    name: str
    description: str
    input_schema: dict   # OpenAI function calling 格式的参数定义
    output_schema: dict  # 返回值结构定义

    def execute(self, **kwargs) -> dict: ...
```

### 2. 各 tool 文件 — 加 schema 类属性

每个 tool 类加上 `input_schema` 和 `output_schema`，格式如下：

```python
class SearchJobsTool:
    name = "search_jobs"
    description = "在 Boss直聘按关键词和城市搜索职位，返回职位列表"
    input_schema = {
        "type": "object",
        "properties": {
            "keywords": {"type": "string", "description": "职位关键词，如 Python后端工程师"},
            "city":     {"type": "string", "description": "目标城市，如 北京"},
            "limit":    {"type": "integer", "description": "最多返回条数", "default": 30},
        },
        "required": ["keywords", "city"],
    }
    output_schema = {
        "type": "object",
        "properties": {
            "jobs": {
                "type": "array",
                "description": "搜索到的职位列表",
                "items": {
                    "type": "object",
                    "properties": {
                        "job_id":   {"type": "string"},
                        "title":    {"type": "string"},
                        "company":  {"type": "string"},
                        "city":     {"type": "string"},
                        "salary":   {"type": "string"},
                        "url":      {"type": "string"},
                    },
                },
            },
        },
    }
```

**各 tool 的 schema 规格：**

#### `score_job`
- input: `job`（Job 对象）, `profile`（dict，求职偏好）
- output: `result`（ScoreResult：score int, decision str, reason str, resume_patch dict）

#### `critique_job`
- input: `job`, `score_result`（ScoreResult）, `profile`
- output: `result`（CriticResult：verdict str ["approve"|"reject"], reason str）

#### `generate_resume`
- input: `job`, `score_result`
- output: `pdf_path`（str 或 null）, `error`（str，可选）

#### `apply_job`
- input: `job`, `resume_path`（str，可选）, `dry_run`（bool，默认 false）
- output: `success`（bool）, `message`（str）, `skipped`（bool，可选）, `dry_run`（bool，可选）

#### `check_responses`
- input: 无（空 object）
- output: `checked`（int）, `updated`（int）, `updates`（array of StatusUpdate）, `error`（str，可选）

#### `update_status`
- input: `job_id`（str）, `new_status`（str）, `score`（int，可选）, `decision`（str，可选）, `critic_verdict`（str，可选）, `error_msg`（str，可选）
- output: `updated`（bool）, `job_id`（str）, `new_status`（str）, `error`（str，可选）

### 3. `tools/registry.py` — 完整注册所有 tool

`initialize_tools()` 改为接收所有必要依赖，注册全部 7 个 tool：

```python
def initialize_tools(
    config: dict,
    tracker,
    llm_clients: dict,
    browser_agent=None,   # 可为 None，browser-dependent tools 在运行时再绑定
    rate_limiter=None,
    resume_manager=None,
) -> None:
```

browser-dependent tools（search_jobs、apply_job、check_responses）需要 browser_agent，
设计上有两种处理方式，选方式 B：

**方式 B（延迟绑定）**：tool 注册时不传 browser_agent，改为 execute() 接收 browser_agent 作为参数传入。

这样 registry 在启动时就能完整初始化，browser_agent 在运行时由 orchestrator 传入。

需要修改 search_jobs、apply_job、check_responses 的 `execute()` 签名，新增 `browser_agent` 参数。

### 4. `orchestrator.py` — 改为通过 registry 调用

- `_init_tools()` 改为调用 `initialize_tools()`
- `run_once()` 和 `_process_job()` 中的直接实例化改为 `get_tool("xxx").execute(...)`
- browser_agent 作为参数传入各 execute() 调用

---

## 验收标准

1. `ToolProtocol` 包含 `input_schema` 和 `output_schema` 属性
2. 全部 7 个 tool 都有 `input_schema` 和 `output_schema` 类属性，格式符合 OpenAI function calling 规范
3. `list_tools()` 返回 7 个 tool 名称
4. `get_tool("search_jobs").input_schema` 可以直接访问，返回合法 dict
5. `orchestrator.py` 中不再有直接 `SearchJobsTool(...)`、`ApplyJobTool(...)` 等实例化代码
6. `python main.py --dry-run` 流程不报错（功能行为不变）

---

## 不在本次范围内

- LLM 驱动的动态 tool 选择（ReAct 循环）
- schema 运行时校验（validate kwargs against input_schema）
- 求职偏好配置相关的新 tool
