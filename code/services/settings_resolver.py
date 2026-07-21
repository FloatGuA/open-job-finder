"""
Layer 3 (workflow 运行参数) 解析：三级 fallback。

优先级（后者覆盖前者）：
  config.yaml[workflow]                 出厂默认（git 跟踪，开发者维护）
  < data/user_settings.yaml[workflow]   用户"设为默认"保存的覆盖（gitignore，懒创建）
  < overrides                           本次 API/CLI 传入（None 值忽略，不覆盖）

user_settings.yaml 懒创建：用户没点过"设为默认"时该文件不存在，直接用出厂默认。
完整说明见 docs/configuration.md。
"""
from pathlib import Path

import yaml


def _user_settings_path(data_dir: Path) -> Path:
    return data_dir / "user_settings.yaml"


def load_user_settings(data_dir: Path) -> dict:
    """读 user_settings.yaml；不存在则返回 {}（懒创建语义）。"""
    path = _user_settings_path(data_dir)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def resolve_params(workflow: str, overrides: dict, config: dict, data_dir: Path) -> dict:
    """合并出厂默认 < 用户默认 < 本次 override，返回该 workflow 的完整运行参数。

    Args:
        workflow: "w1" | "w2"
        overrides: 本次请求传入的参数；值为 None 的键忽略（不覆盖默认）
        config: get_system_config() 返回的系统配置 dict（含 w1/w2 出厂默认节）
        data_dir: data/ 目录路径（user_settings.yaml 所在）
    """
    merged: dict = dict(config.get(workflow, {}) or {})
    merged.update(load_user_settings(data_dir).get(workflow, {}) or {})
    merged.update({k: v for k, v in (overrides or {}).items() if v is not None})
    return merged


def save_user_default(workflow: str, updates: dict, data_dir: Path) -> dict:
    """前端"设为默认"调用：把 updates 写入 user_settings.yaml[workflow]（部分覆盖）。

    只写入/更新 updates 里的键，其余保持原样。返回更新后的完整 user_settings dict。
    """
    settings = load_user_settings(data_dir)
    section = dict(settings.get(workflow, {}) or {})
    section.update(updates)
    settings[workflow] = section
    path = _user_settings_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(settings, fh, allow_unicode=True, default_flow_style=False, sort_keys=False)
    return settings
