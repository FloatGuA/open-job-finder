"""实例名 ←→ config.yaml 里那份 provider 配置的映射。

设置页的「模型」下拉此前同时说两种话：`<option>` 填的是**实例名**
（`ollama_qwen3:8b`），`value` 填的是**类型**（`ollama`）——value 在选项里根本
不存在，浏览器于是回退显示第一项。用户看到「明明配的是 deepseek 却显示 qwen」。

**更要命的是保存**：下拉被动一下再保存，实例名会被当成 `type` 写进 config.yaml，
`_build_chain` 随即 `ValueError: Unknown provider type`——而**文件已经写坏了**，
下次重启后端直接起不来。

收敛到实例名（类型分不出同类型的不同模型，而那正是这个下拉的用处）。
"""
import pytest

from services.llm_client import (
    ModelRouter,
    capability_head_names,
    configured_provider_specs,
)

CONFIG = {
    "llm": {
        "capabilities": {
            "fast": [{"type": "ollama", "model": "qwen3:8b",
                      "base_url": "http://localhost:11434"}],
            "balanced": [{"type": "openai_compatible", "model": "deepseek-chat",
                          "base_url": "https://api.deepseek.com",
                          "api_key_env": "DEEPSEEK_API_KEY"}],
            "powerful": [{"type": "claude_cli"},
                         {"type": "anthropic_api", "model": "claude-opus-4-8"}],
            "vision": [{"type": "codex_cli"}, {"type": "claude_cli"}],
        }
    }
}


class TestTheNameComesFromTheProvider:
    def test_every_configured_provider_is_listed_by_instance_name(self):
        specs = configured_provider_specs(CONFIG)
        assert set(specs) == {"ollama_qwen3:8b", "openai_compat_deepseek-chat",
                              "claude_cli", "anthropic_claude-opus-4-8", "codex_cli"}

    def test_the_spec_round_trips_back_to_its_config_entry(self):
        """名字要能换回**完整**的那份配置——只留 type 的话，换个模型就把
        base_url/api_key_env 丢了。"""
        spec = configured_provider_specs(CONFIG)["openai_compat_deepseek-chat"]
        assert spec == {"type": "openai_compatible", "model": "deepseek-chat",
                        "base_url": "https://api.deepseek.com",
                        "api_key_env": "DEEPSEEK_API_KEY"}

    def test_names_agree_with_what_the_router_reports(self):
        """**这条是防分叉的。** 名字必须问 provider 自己要，不能按 type+model
        另算一份——重算的那份不会报错，只会在某天 `OllamaProvider.__init__`
        改了命名之后静默对不上。"""
        from services.llm_client import build_model_router

        assert set(configured_provider_specs(CONFIG)) == set(
            build_model_router(CONFIG).configured_provider_names())

    def test_editing_a_returned_spec_does_not_touch_the_config(self):
        specs = configured_provider_specs(CONFIG)
        specs["claude_cli"]["type"] = "wrecked"
        assert CONFIG["llm"]["capabilities"]["powerful"][0]["type"] == "claude_cli"


class TestWhichOneIsCurrentlyHead:
    def test_head_is_reported_per_level_in_the_same_vocabulary(self):
        """跟 `configured_provider_specs` 说同一种话——下拉的 value 和 option
        对不上，正是这个 bug 的全部内容。"""
        heads = capability_head_names(CONFIG)
        assert heads == {"fast": "ollama_qwen3:8b",
                         "balanced": "openai_compat_deepseek-chat",
                         "powerful": "claude_cli",
                         "vision": "codex_cli"}

    def test_vision_is_not_left_out(self):
        """`vision` 一直在 `ModelRouter.LEVELS` 里，是别处手抄了一份三档列表
        才让简历视觉解析那条链在 UI 上完全看不见。"""
        assert "vision" in ModelRouter.LEVELS
        assert set(capability_head_names(CONFIG)) <= set(ModelRouter.LEVELS)

    def test_a_level_with_no_providers_is_absent_not_blank(self):
        heads = capability_head_names({"llm": {"capabilities": {"fast": []}}})
        assert heads == {}


class TestBadConfigFailsLoudly:
    def test_unknown_type_still_raises(self):
        """坏配置就该在这里炸，不能悄悄跳过——那样下拉会少一项，
        而少的那项恰恰是坏的那个。"""
        with pytest.raises(ValueError, match="Unknown provider type"):
            configured_provider_specs(
                {"llm": {"capabilities": {"fast": [{"type": "nope"}]}}})
