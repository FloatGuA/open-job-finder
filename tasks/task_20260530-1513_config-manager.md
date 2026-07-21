# Task: Config Manager — 配置集中管理 + Profile API

## Goal
新建 `services/config_manager.py`，将 `config.yaml` 和 `profile.yaml` 的读写逻辑收拢，并在 Dashboard 暴露 `/api/config/profile` GET/PUT 端点。

## Background
现状：`config.yaml` 由 `load_config()` 直接读取，散落在 `main.py`、`dashboard/server.py`、`services/llm_client.py` 等处；`profile.yaml` 只能手改。缺少统一的读写入口，无法从前端编辑求职偏好。

本 task 完成后：所有模块通过 `ConfigManager` 访问配置；`profile.yaml` 可通过 API 读写，为前端配置页（T045）做好准备。

## Depends On
- task_20260530-1512_llm-model-router — `config.yaml` 已改为 `llm.capabilities` 结构，ConfigManager 要能读新格式

## Change Scope
- **In scope**:
  - `services/config_manager.py`（新建）
  - `services/onboarding.py`（`_write_config` 改调 ConfigManager）
  - `main.py`（`load_config` 改调 ConfigManager）
  - `dashboard/server.py`（`load_config` 改调 ConfigManager；新增 profile API 端点）
  - `services/llm_client.py`（`load_config` 保留，不强制改，ConfigManager 内部仍可调它）
- **Out of scope**: 前端页面（T045）、LLM provider 选择逻辑、测试以外的其他文件

## Implementation Requirements

### 1. `services/config_manager.py`（新建）

```python
class ConfigManager:
    def __init__(self, config_path: str = "config.yaml", profile_path: str = "data/profile.yaml"):
        self._config_path = Path(config_path)
        self._profile_path = Path(profile_path)
        self._config: dict = {}
        self._profile: dict = {}
        self._load()

    def _load(self) -> None:
        # 读 config.yaml（必须存在）和 profile.yaml（可不存在，返回空 dict）

    def get_system_config(self) -> dict:
        # 返回完整 config dict（深拷贝，防止调用方修改）

    def get_profile(self) -> dict:
        # 返回 profile dict（深拷贝）

    def save_profile(self, updates: dict) -> None:
        # 合并 updates 到现有 profile，写回 profile.yaml（utf-8，allow_unicode=True）
        # 合并规则：顶层 key 覆盖；不删除 updates 中未提及的 key

    def reload(self) -> None:
        # 重新从磁盘读取两个文件

    def save_system_config(self, section: str, updates: dict) -> None:
        # 仅允许更新指定 section（如 "apply"、"schedule"、"browser"）
        # 禁止通过此方法写入 "llm" section（防止误改 provider 配置）
        # 写回 config.yaml

# 模块级单例（延迟初始化）
_instance: ConfigManager | None = None

def get_config_manager(config_path: str = "config.yaml", profile_path: str = "data/profile.yaml") -> ConfigManager:
    global _instance
    if _instance is None:
        _instance = ConfigManager(config_path, profile_path)
    return _instance
```

#### Produces
```python
class ConfigManager:
    def get_system_config(self) -> dict: ...
    def get_profile(self) -> dict: ...
    def save_profile(self, updates: dict) -> None: ...
    def reload(self) -> None: ...
    def save_system_config(self, section: str, updates: dict) -> None: ...

def get_config_manager(...) -> ConfigManager: ...
```

### 2. `dashboard/server.py` — 新增 profile API 端点

#### `GET /api/config/profile`
```python
@app.get("/api/config/profile")
async def get_profile() -> JSONResponse:
    cm = get_config_manager()
    return JSONResponse(cm.get_profile())
```

#### `PUT /api/config/profile`
```python
@app.put("/api/config/profile")
async def update_profile(body: dict) -> JSONResponse:
    # 校验：body 不为空
    # 允许的字段：keywords(list[str])、cities(list[str])、salary(str)、
    #             experience(list[str])、extra_notes(str)、score_threshold(int)
    # 未知字段：忽略（不写入）
    cm = get_config_manager()
    cm.save_profile(filtered_body)
    return JSONResponse({"ok": True})
```

#### `GET /api/config/system`
```python
@app.get("/api/config/system")
async def get_system_config() -> JSONResponse:
    cm = get_config_manager()
    cfg = cm.get_system_config()
    # 只返回前端需要的非敏感字段：
    return JSONResponse({
        "apply": cfg.get("apply", {}),
        "schedule": cfg.get("schedule", {}),
        "browser": cfg.get("browser", {}),
        "llm_capabilities": list(cfg.get("llm", {}).get("capabilities", {}).keys()),
    })
```

### 3. `main.py`

```python
from services.config_manager import get_config_manager
# 替换：
config = load_config("config.yaml")
# 改为：
config = get_config_manager().get_system_config()
```

### 4. `services/onboarding.py`

`_write_config(self)` 方法改为调用 `get_config_manager().save_system_config(section, data)` 而不是直接写 YAML。若 _write_config 写的是整个 config，则改为分 section 调用。

#### Examples（save_profile）

| Precondition | Action | Expected State After |
|---|---|---|
| profile.yaml: `{keywords: ["Python"], cities: ["北京"]}` | `save_profile({"keywords": ["Python", "Go"]})` | profile.yaml: `{keywords: ["Python", "Go"], cities: ["北京"]}` |
| profile.yaml 不存在 | `save_profile({"keywords": ["Python"]})` | profile.yaml: `{keywords: ["Python"]}` 被创建 |

## Test Requirements
- Automated: yes — unit
- Framework: pytest
- Coverage:
  - `ConfigManager.get_profile()` 返回深拷贝（修改返回值不影响内部状态）
  - `ConfigManager.save_profile()` 合并写入且不删除未提及的 key
  - `ConfigManager.save_system_config()` 拒绝写入 "llm" section（应抛 ValueError）
  - `GET /api/config/profile` 返回 200 + profile dict
  - `PUT /api/config/profile` 持久化并返回 `{"ok": true}`
  - `GET /api/config/system` 不含 API key 等敏感字段

## Acceptance Criteria
- [ ] `services/config_manager.py` 存在，包含 `ConfigManager` 类和 `get_config_manager()` 函数
- [ ] `GET /api/config/profile` 返回 profile.yaml 内容
- [ ] `PUT /api/config/profile` 写入并合并（不覆盖未提及的字段）
- [ ] `GET /api/config/system` 返回非敏感系统配置，不含 api_key
- [ ] `main.py` 使用 `get_config_manager().get_system_config()`
- [ ] `python -c "from dashboard.server import app"` 成功
- [ ] `pytest tests/ --ignore=tests/test_server.py -q` 全部通过

## Ambiguity Protocol
如有歧义，实现最合理的解释并在 report.md 的 Deviations 节说明。
