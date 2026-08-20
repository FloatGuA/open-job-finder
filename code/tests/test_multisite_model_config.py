"""ReAct 那两处（`create_react_agent` / `with_structured_output`）的模型参数从
config.yaml 的 `multisite.model` 读，不再写死在代码里。

**为什么它不能走 `ModelRouter`**：`create_react_agent` 要的是一个 LangChain 的
chat model 且必须支持 tool calling，而 `FallbackChain.complete()` 返回的是文本。
所以这两处拿不到兜底，但至少要能配。

**为什么是独立的 `multisite.model` 节、而不是复用 `llm.capabilities.balanced` 的
第一条**：那条链是给 `FallbackChain` 用的，第一条不保证是 `openai_compatible`——
哪天把 ollama 或 claude_cli 放到链首，`build_model` 就会拿到一个没有 base_url 的
条目，m1 当场挂掉。这里的约束跟那条链不是一回事（必须支持 tool calling），
写成独立的节才说得清楚。
"""
import pytest

from multisite import agent_runtime


CFG = {"multisite": {"model": {
    "type": "openai_compatible",
    "model": "some-tool-calling-model",
    "base_url": "https://example.test/v1",
    "api_key_env": "PROBE_KEY_ENV",
}}}


class TestBuildModelReadsConfig:
    def test_it_uses_the_model_named_in_config(self, monkeypatch):
        monkeypatch.setenv("PROBE_KEY_ENV", "sk-probe")
        monkeypatch.setattr(agent_runtime, "load_config", lambda: CFG)
        llm = agent_runtime.build_model()
        assert llm.model_name == "some-tool-calling-model"

    def test_a_missing_section_fails_loudly(self, monkeypatch):
        """缺配置就在这里炸，而不是带着空值走到第一次网络调用才报 401
        （沿用 `build_model` 原本对 api_key 的 fail-fast 立场）。"""
        monkeypatch.setattr(agent_runtime, "load_config", lambda: {"llm": {}})
        with pytest.raises(Exception, match="multisite"):
            agent_runtime.build_model()

    def test_the_factory_config_has_the_section(self):
        """出厂 config.yaml 必须自带这一节，否则装好就跑不起来。"""
        from pathlib import Path

        import yaml
        cfg = yaml.safe_load(
            (Path(__file__).parent.parent / "config.yaml").read_text(encoding="utf-8"))
        node = (cfg.get("multisite") or {}).get("model") or {}
        assert node.get("model"), "config.yaml 缺 multisite.model"
        assert node.get("base_url") and node.get("api_key_env")
