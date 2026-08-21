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
        # 'llm' is refused here because this is a flat top-level update, and the llm
        # section is nested (capabilities[level] is a LIST of provider dicts). A plain
        # dict.update would flatten it. Use save_llm_settings, which knows the shape.
        if section == "llm":
            raise ValueError(
                "Writing to the 'llm' section is not allowed via save_system_config; "
                "use save_llm_settings()."
            )
        self._config.setdefault(section, {}).update(updates)
        self._write_config()

    def save_llm_settings(
        self,
        capabilities: dict[str, dict] | None = None,
        tool_providers: dict[str, Any] | None = None,
    ) -> None:
        """Structured update of the llm section, keeping its nesting intact.

        `capabilities` 把每档（fast/balanced/powerful/vision）映射到**一整份
        provider 配置**，放到那一档 FallbackChain 的链首。

        **收整份而不是只收一个 type**：换模型要连 `base_url`/`api_key_env` 一起
        换过去，只改 type 会留着上一个 provider 的连接参数，配出一个谁都没配过
        的组合。名字换回配置这件事由调用方做（`llm_client.configured_provider_specs`），
        本模块不认识 provider——它只负责按 config.yaml 的形状写。

        已经在链里的那份是**换位**，不是复制一份到链首把原链首挤掉：链首之后
        那些是 fallback，用户选主力模型不该顺手删掉一个兜底。

        Exists because the dashboard used to read/modify/write config.yaml inline for
        this one section, which left the singleton's cached copy stale -- a later
        get_system_config() would hand back the pre-edit config.
        """
        llm = self._config.setdefault("llm", {})
        if capabilities:
            caps = llm.setdefault("capabilities", {})
            for level, spec in capabilities.items():
                if not spec:
                    continue
                chain = list(caps.get(level) or [])
                if spec in chain:
                    chain.remove(spec)
                    chain.insert(0, spec)
                elif chain:
                    chain[0] = spec
                else:
                    chain = [spec]
                caps[level] = chain
        if tool_providers is not None:
            llm["tool_providers"] = tool_providers
        self._write_config()

    def _write_config(self) -> None:
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
