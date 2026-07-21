# Task: LLM ModelRouter — 基于 capability 的 provider 路由

## Goal
将现有的三链式 `llm_clients` dict 替换为单一 `ModelRouter`，让工具通过声明 `capability` 属性选择 LLM 级别，同时修复 `CodexCLIProvider` 的错误调用方式。

## Background
现有设计：`build_llm_client(config, chain_name)` 按链名（scoring/generation/analysis）构建独立的 `FallbackChain`，runner 持有一个 `llm_clients: dict`，工具在注册时被传入对应链。缺陷：工具无法根据任务复杂度选择 provider 级别，三条链的区分只是约定而非语义。

新设计：`ModelRouter` 持有三条 `FallbackChain`（fast/balanced/powerful），工具声明 `capability: str` 属性，调用时传入 `capability` 参数路由到对应链。

`CodexCLIProvider.complete()` 现在用 `["codex", "exec", full_prompt]`，`codex exec` 子命令不存在，应改为 `["codex", "-q", full_prompt]`。

## Change Scope
- **In scope**:
  - `services/llm_client.py`
  - `config.yaml`
  - `tools/llm/score_job.py`
  - `tools/llm/analyze_intent.py`
  - `tools/db/w1/__init__.py`
  - `tools/db/w2/__init__.py`
  - `pipeline/w1_runner.py`
  - `pipeline/w2_runner.py`
  - `main.py`
  - `dashboard/server.py`
  - `tests/` 中涉及 llm_client 的测试
- **Out of scope**: `tools/biz_logic/`（不使用 LLM）、`services/onboarding.py`、前端

## Implementation Requirements

### 1. `services/llm_client.py`

#### 1a. 修复 `CodexCLIProvider`
```python
# is_available 保持不变（["codex", "--version"]）
# complete() 改为：
result = subprocess.run(
    ["codex", "-q", full_prompt],
    capture_output=True, text=True, timeout=120,
)
```

#### 1b. 新增 `ModelRouter` 类
```python
class ModelRouter:
    """Routes LLM calls to the appropriate FallbackChain based on capability level."""

    LEVELS = ("fast", "balanced", "powerful")

    def __init__(self, chains: dict[str, FallbackChain], default: str = "balanced"):
        # chains: {"fast": FallbackChain, "balanced": FallbackChain, "powerful": FallbackChain}
        # 允许只配置部分级别；missing level fallback 到 "balanced"，若 "balanced" 也缺则取任意可用链
        self._chains = chains
        self._default = default

    def complete(self, prompt: str, system: str = "", capability: str = "balanced") -> tuple[str, str]:
        chain = self._chains.get(capability) or self._chains.get(self._default) or next(iter(self._chains.values()))
        return chain.complete(prompt, system)

    def available_providers(self, capability: str = "balanced") -> list[str]:
        chain = self._chains.get(capability)
        return chain.available_providers if chain else []
```

#### 1c. 新增 `build_model_router(config: dict) -> ModelRouter`
```python
def build_model_router(config: dict) -> ModelRouter:
    caps = config.get("llm", {}).get("capabilities", {})
    chains: dict[str, FallbackChain] = {}
    for level in ModelRouter.LEVELS:
        specs = caps.get(level, [])
        if specs:
            chains[level] = _build_chain(specs, chain_name=level)
    if not chains:
        raise ValueError("config.yaml: llm.capabilities must define at least one level")
    return ModelRouter(chains)
```

内部提取 `_build_chain(specs, chain_name)` 将原 `build_llm_client` 的 provider 构建逻辑复用。

保留 `build_llm_client` 函数签名但标记为 deprecated（内部调用 `build_model_router`）以防旧代码引用。

#### Produces
```python
class ModelRouter:
    def complete(self, prompt: str, system: str = "", capability: str = "balanced") -> tuple[str, str]: ...
    def available_providers(self, capability: str = "balanced") -> list[str]: ...

def build_model_router(config: dict) -> ModelRouter: ...
```

### 2. `config.yaml`

将 `llm.providers` 替换为 `llm.capabilities`：

```yaml
llm:
  capabilities:
    fast:
      - type: ollama
        model: qwen2.5:7b
        base_url: http://localhost:11434
    balanced:
      - type: claude_cli
      - type: codex_cli
    powerful:
      - type: claude_cli
      - type: anthropic_api
        model: claude-opus-4-8
        api_key_env: ANTHROPIC_API_KEY
```

保留其他所有配置项（job_search、apply、schedule、browser、dashboard）不变。

### 3. `tools/llm/score_job.py`

```python
class ScoreJob(BaseTool):
    capability = "balanced"   # 新增类属性

    def execute(self, ...) -> ToolResult:
        ...
        text, provider = self._llm.complete(prompt, system=_SYSTEM, capability=self.capability)
        # 原来是 self._llm.complete(prompt, system=_SYSTEM)，加 capability= 参数
```

### 4. `tools/llm/analyze_intent.py`

同上，加 `capability = "balanced"` 和 `capability=self.capability` 参数。

### 5. `tools/db/w1/__init__.py` 和 `tools/db/w2/__init__.py`

参数名从 `llm_client` 改为 `model_router`，类型是 `ModelRouter`，其余不变：

```python
# w1
def register_w1_tools(registry, db, model_router, prompt_manager) -> None:
    registry.register(ScoreJob(llm_client=model_router, prompt_manager=prompt_manager))
    # ScoreJob.__init__ 参数名不变（仍叫 llm_client），只是传入的是 ModelRouter 实例

# w2
def register_w2_tools(registry, db, model_router, prompt_manager) -> None:
    registry.register(AnalyzeHRIntent(llm_client=model_router, prompt_manager=prompt_manager))
```

### 6. `pipeline/w1_runner.py`

```python
# 签名改为：
def run_w1(config, tracker, model_router, emitter=None, ...):
    ...
    register_w1_tools(registry, tracker, model_router, prompt_manager)
```

删除 `llm_clients.get("scoring")` 这一行。

### 7. `pipeline/w2_runner.py`

同上，`llm_clients` → `model_router`，删除 `llm_clients.get("analysis") or llm_clients.get("scoring")` 逻辑。

### 8. `main.py`

```python
from services.llm_client import build_model_router, load_config
...
model_router = build_model_router(config)
...
run_w1(config, tracker, model_router, ...)
run_w2(config, tracker, model_router, ...)
```

### 9. `dashboard/server.py`

```python
# _initialize_state() 中：
app.state.model_router = build_model_router(config)

# _run_apply_workflow / _run_check_workflow：
run_w1(..., model_router=app.state.model_router, ...)
run_w2(..., model_router=app.state.model_router, ...)
```

删除 `app.state.llm_clients` dict。

## Test Requirements
- Automated: yes — unit
- Framework: pytest
- Coverage:
  - `ModelRouter.complete()` 路由到正确的 chain
  - `ModelRouter.complete()` 当 capability 不存在时 fallback 到 balanced
  - `build_model_router()` 从 config dict 正确构建
  - `CodexCLIProvider` 的 `complete()` 使用 `["codex", "-q", ...]`（mock subprocess）
  - 更新 `tests/test_run_logger_and_registry.py` 中涉及 `llm_clients` 的 fixture

## Acceptance Criteria
- [ ] `CodexCLIProvider.complete()` 使用 `["codex", "-q", full_prompt]`
- [ ] `ModelRouter` 可按 capability 路由到对应 FallbackChain
- [ ] capability 不存在时 fallback 到 balanced，不抛异常
- [ ] `config.yaml` 已更新为 `llm.capabilities` 结构
- [ ] `ScoreJob.capability == "balanced"`，`complete()` 传入 capability 参数
- [ ] `AnalyzeHRIntent.capability == "balanced"`，`complete()` 传入 capability 参数
- [ ] `run_w1` / `run_w2` 签名改为 `model_router` 参数
- [ ] `main.py` 和 `dashboard/server.py` 使用 `build_model_router`
- [ ] `python -c "from dashboard.server import app"` 成功
- [ ] `pytest tests/ --ignore=tests/test_server.py -q` 全部通过

## Ambiguity Protocol
如有歧义，实现最合理的解释并在 report.md 的 Deviations 节说明。
