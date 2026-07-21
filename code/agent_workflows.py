"""
Workflow registry and config helpers for the Chat Agent.
Adding a new workflow only requires adding an entry to WORKFLOW_REGISTRY.
"""
from pathlib import Path

import yaml

WORKFLOW_REGISTRY: dict[str, dict] = {
    "apply": {
        "description": "搜索并自动投递职位",
        "trigger_intents": ["apply"],
        "config_source": "profile",
        "config_fields": [
            "keywords", "cities", "job_type", "experience",
            "degree", "salary", "boss_online", "score_threshold",
        ],
        "requires_confirmation": True,
        "guard": "check_apply",
    },
    "check": {
        "description": "检查 HR 聊天回复并更新状态",
        "trigger_intents": ["check"],
        "config_source": "config",
        "config_fields": ["check_responses_days", "check_responses_max"],
        "requires_confirmation": True,
        "guard": "check_responses",
    },
    "summary": {
        "description": "查看今日投递统计",
        "trigger_intents": ["summary"],
        "config_source": None,
        "config_fields": [],
        "requires_confirmation": False,
        "guard": None,
    },
}

_PROFILE_PATH = Path("data/profile.yaml")
_CONFIG_PATH = Path("config.yaml")

_FIELD_LABELS = {
    "keywords": "关键词",
    "cities": "城市",
    "job_type": "岗位类型",
    "experience": "经验要求",
    "degree": "学历要求",
    "salary": "薪资期望",
    "boss_online": "仅活跃HR",
    "score_threshold": "评分阈值",
    "check_responses_days": "扫描天数",
    "check_responses_max": "最多条数",
}


def read_profile() -> dict:
    """Read data/profile.yaml. Returns empty dict if not found."""
    try:
        with _PROFILE_PATH.open(encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}


def update_profile(field: str, value) -> bool:
    """Update a single field in data/profile.yaml. Returns True on success."""
    try:
        profile = read_profile()
        profile[field] = value
        _PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with _PROFILE_PATH.open("w", encoding="utf-8") as f:
            yaml.dump(profile, f, allow_unicode=True, default_flow_style=False)
        return True
    except Exception:
        return False


def read_config() -> dict:
    """Read config.yaml, return schedule and apply sections."""
    try:
        with _CONFIG_PATH.open(encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        result = {}
        result.update(cfg.get("schedule", {}))
        result.update(cfg.get("apply", {}))
        return result
    except FileNotFoundError:
        return {}


def format_config_for_display(workflow_key: str) -> str:
    """
    Read the config fields required by a workflow and format as a human-readable string.
    e.g. "关键词：AI / 城市：深圳 / 评分阈值：50"
    """
    wf = WORKFLOW_REGISTRY.get(workflow_key)
    if not wf:
        return "(未知 workflow)"

    source = wf["config_source"]
    fields = wf["config_fields"]

    if source == "profile":
        data = read_profile()
    elif source == "config":
        data = read_config()
    else:
        return "(无需配置)"

    parts = []
    for field in fields:
        label = _FIELD_LABELS.get(field, field)
        val = data.get(field)
        if val is None:
            val = "未设置"
        elif isinstance(val, bool):
            val = "是" if val else "否"
        elif isinstance(val, list):
            val = "、".join(str(v) for v in val) if val else "未设置"
        parts.append(f"{label}：{val}")

    return " / ".join(parts)
