import copy
from pathlib import Path
from typing import Any

import yaml


class ConfigManager:
    def __init__(
        self,
        config_path: str = "config.yaml",
        profile_path: str = "data/profile.yaml",
    ):
        self._config_path = Path(config_path)
        self._profile_path = Path(profile_path)
        self._config: dict = {}
        self._profile: dict = {}
        self._load()

    def _load(self) -> None:
        if not self._config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self._config_path}")
        with self._config_path.open("r", encoding="utf-8") as f:
            self._config = yaml.safe_load(f) or {}

        if self._profile_path.exists():
            with self._profile_path.open("r", encoding="utf-8") as f:
                self._profile = yaml.safe_load(f) or {}
        else:
            self._profile = {}

    def get_system_config(self) -> dict:
        return copy.deepcopy(self._config)

    def get_profile(self) -> dict:
        return copy.deepcopy(self._profile)

    def save_profile(self, updates: dict) -> None:
        self._profile.update(updates)
        self._profile_path.parent.mkdir(parents=True, exist_ok=True)
        with self._profile_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                self._profile, f, allow_unicode=True, default_flow_style=False, sort_keys=False
            )

    def reload(self) -> None:
        self._load()

    def save_system_config(self, section: str, updates: dict) -> None:
        if section == "llm":
            raise ValueError("Writing to the 'llm' section is not allowed via save_system_config.")
        self._config.setdefault(section, {}).update(updates)
        with self._config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(
                self._config, f, allow_unicode=True, default_flow_style=False, sort_keys=False
            )


_instance: "ConfigManager | None" = None


def get_config_manager(
    config_path: str = "config.yaml",
    profile_path: str = "data/profile.yaml",
) -> ConfigManager:
    global _instance
    if _instance is None:
        _instance = ConfigManager(config_path, profile_path)
    elif (
        config_path != "config.yaml" and str(_instance._config_path) != config_path
        or profile_path != "data/profile.yaml" and str(_instance._profile_path) != profile_path
    ):
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "get_config_manager called with different paths (%s, %s) but singleton already "
            "initialized with (%s, %s); returning existing instance.",
            config_path, profile_path,
            _instance._config_path, _instance._profile_path,
        )
    return _instance
