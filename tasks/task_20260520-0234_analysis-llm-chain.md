# Task: 为 HR 意图分析新增独立 LLM 链（analysis chain）

## 目标

在 `config.yaml` 中新增 `analysis` provider 链，让 HR 意图分析（`AnalyzeHRMessageTool`）与职位评分（scoring）可以独立配置不同的 LLM 模型。同时更新 Dashboard Setup 页面，使用户可以在 UI 中选择 analysis 链的 provider。

## 背景

`AnalyzeHRMessageTool` 目前调用 `build_llm_client(config, "scoring")`，与职位评分共用同一个 LLM provider 链。用户希望两者能独立配置（例如分析用轻量 Ollama，评分用 Claude CLI）。

涉及文件：
- `code/config.yaml`
- `code/tools/analyze_hr_message.py`
- `code/dashboard/server.py`
- `code/dashboard/frontend/src/pages/Setup.tsx`

## 实现要求

### 1. `code/config.yaml`

在 `llm.providers` 下新增 `analysis` 链（紧跟在 `generation` 后面），默认值与 `scoring` 相同：

```yaml
llm:
  providers:
    scoring:
    - type: claude_cli
    generation:
    - type: claude_cli
    analysis:
    - type: claude_cli
```

### 2. `code/tools/analyze_hr_message.py`

`AnalyzeHRMessageTool.__init__` 中，将 `build_llm_client(config, "scoring")` 改为使用 `analysis` 链，并在 `analysis` 链未配置时回退到 `scoring`：

```python
def __init__(self, config: dict):
    providers = config.get("llm", {}).get("providers", {})
    chain = "analysis" if "analysis" in providers else "scoring"
    self.llm = build_llm_client(config, chain)
```

### 3. `code/dashboard/server.py`

三处修改，都很小：

**a) `_initialize_state()` 中的 `app.state.llm_clients`（约第 122 行）**

新增 `analysis` 链的实例化：

```python
app.state.llm_clients = {
    "scoring": build_llm_client(config, "scoring"),
    "generation": build_llm_client(config, "generation"),
    "analysis": build_llm_client(config, "analysis"),
}
```

**b) `GET /api/config/llm` 返回值（约第 625 行）**

新增 `analysis` 字段：

```python
scoring = (providers.get("scoring") or [{}])[0].get("type", "claude_cli")
generation = (providers.get("generation") or [{}])[0].get("type", "claude_cli")
analysis = (providers.get("analysis") or [{}])[0].get("type", "claude_cli")
return JSONResponse({"scoring": scoring, "generation": generation, "analysis": analysis})
```

**c) `POST /api/config/llm` 写入逻辑（约第 634 行）**

读取 `analysis_type` 并写入 config：

```python
scoring_type = data.get("scoring", "claude_cli")
generation_type = data.get("generation", "claude_cli")
analysis_type = data.get("analysis", "claude_cli")

existing.setdefault("llm", {})["providers"] = {
    "scoring": [{"type": scoring_type}],
    "generation": [{"type": generation_type}],
    "analysis": [{"type": analysis_type}],
}
```

### 4. `code/dashboard/frontend/src/pages/Setup.tsx`

在 LLM providers 列表数组中，紧跟 `generation` 之后插入 `analysis` 条目（注意用 `\uXXXX` 转义所有 CJK）：

```tsx
[
  ['scoring', '评分 / Critic'],
  ['generation', '简历生成'],
  ['analysis', 'HR 意图分析'],
] as [keyof typeof llm, string][]
```

同时在 `llm` state 类型定义处（`useState` 初始值或 interface）新增 `analysis` 字段，初始值 `'claude_cli'`。

**注意**：在 `GET /api/config/llm` 响应中读取 `analysis` 字段，与 `scoring` / `generation` 处理方式完全一致。

## 验收标准

- [ ] `config.yaml` 包含 `analysis` 链，默认 `claude_cli`
- [ ] `AnalyzeHRMessageTool` 使用 `analysis` 链；若 `analysis` 未配置则回退 `scoring`
- [ ] `GET /api/config/llm` 返回 `{scoring, generation, analysis}` 三个字段
- [ ] `POST /api/config/llm` 保存时同时写入 `analysis` provider
- [ ] Dashboard Setup 页面 LLM 区域显示三行（评分/Critic、简历生成、HR 意图分析）
- [ ] 修改任意一个 provider 并保存，重读 config 后三个值均正确持久化
- [ ] `npm run build` 无报错
- [ ] `pytest` 全部通过
