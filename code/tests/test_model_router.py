"""Unit tests for ModelRouter and CodexCLIProvider (Task: llm-model-router)."""
import os
import re
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from services.llm_client import (
    ClaudeCLIProvider,
    CodexCLIProvider,
    FallbackChain,
    ModelRouter,
    OllamaProvider,
    OpenAICompatibleProvider,
    build_model_router,
)


# ── FallbackChain stub ────────────────────────────────────────────────────────

def _make_chain(response: str = "ok", provider_name: str = "stub") -> FallbackChain:
    provider = MagicMock()
    provider.name = provider_name
    provider.is_available.return_value = True
    provider.complete.return_value = response
    chain = FallbackChain([provider], chain_name="test")
    # Override complete to return tuple (text, provider_name)
    chain.complete = MagicMock(return_value=(response, provider_name))
    return chain


# ── ModelRouter routing ───────────────────────────────────────────────────────

def test_model_router_routes_to_correct_chain():
    fast_chain = _make_chain("fast-response", "fast-provider")
    balanced_chain = _make_chain("balanced-response", "balanced-provider")
    powerful_chain = _make_chain("powerful-response", "powerful-provider")

    router = ModelRouter(
        chains={"fast": fast_chain, "balanced": balanced_chain, "powerful": powerful_chain}
    )

    text, provider = router.complete("hello", capability="fast")
    assert text == "fast-response"
    fast_chain.complete.assert_called_once_with("hello", "", None, False, None)

    text, provider = router.complete("hello", capability="powerful")
    assert text == "powerful-response"
    powerful_chain.complete.assert_called_once_with("hello", "", None, False, None)


def test_model_router_threads_images_to_chain():
    """视觉解析：images 参数必须一路透传到目标链（parse_resume_vision 依赖它）。"""
    vision_chain = _make_chain("vision-response", "ollama_qwen2.5vl:7b")
    router = ModelRouter(chains={"vision": vision_chain})

    text, _ = router.complete("read this", capability="vision", images=["B64IMG"])
    assert text == "vision-response"
    vision_chain.complete.assert_called_once_with("read this", "", None, False, ["B64IMG"])


def test_model_router_fallback_to_balanced_when_capability_missing():
    balanced_chain = _make_chain("balanced-response", "balanced-provider")
    router = ModelRouter(chains={"balanced": balanced_chain})

    # "fast" not configured — should fall back to "balanced"
    text, _ = router.complete("hello", capability="fast")
    assert text == "balanced-response"
    balanced_chain.complete.assert_called_once()


def test_model_router_fallback_to_first_chain_when_no_balanced():
    only_chain = _make_chain("only-response", "only-provider")
    router = ModelRouter(chains={"powerful": only_chain}, default="balanced")

    # Neither "fast" nor "balanced" exists — falls back to first available chain
    text, _ = router.complete("hello", capability="fast")
    assert text == "only-response"


def test_model_router_available_providers_returns_list():
    chain = MagicMock(spec=FallbackChain)
    type(chain).available_providers = property(lambda self: ["stub"])
    router = ModelRouter(chains={"balanced": chain})

    providers = router.available_providers(capability="balanced")
    assert providers == ["stub"]


def test_model_router_available_providers_missing_capability_returns_empty():
    router = ModelRouter(chains={"balanced": _make_chain()})
    providers = router.available_providers(capability="fast")
    assert providers == []


# ── build_model_router ────────────────────────────────────────────────────────

def test_build_model_router_from_config():
    config = {
        "llm": {
            "capabilities": {
                "balanced": [{"type": "claude_cli"}],
            }
        }
    }
    router = build_model_router(config)
    assert isinstance(router, ModelRouter)
    assert "balanced" in router._chains


def test_build_model_router_multiple_levels():
    config = {
        "llm": {
            "capabilities": {
                "fast": [{"type": "claude_cli"}],
                "balanced": [{"type": "claude_cli"}],
                "powerful": [{"type": "claude_cli"}],
            }
        }
    }
    router = build_model_router(config)
    assert set(router._chains.keys()) == {"fast", "balanced", "powerful"}


def test_build_model_router_raises_when_no_capabilities():
    config = {"llm": {"capabilities": {}}}
    with pytest.raises(ValueError, match="llm.capabilities must define at least one level"):
        build_model_router(config)


def test_build_model_router_raises_when_llm_missing():
    config = {}
    with pytest.raises(ValueError, match="llm.capabilities must define at least one level"):
        build_model_router(config)


# ── 视觉 images 透传 ──────────────────────────────────────────────────────────

def test_ollama_provider_passes_images_in_payload():
    provider = OllamaProvider(model="qwen2.5vl:7b")
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = {"response": "  ok  "}
    with patch("services.llm_client.requests.post", return_value=resp) as mp:
        out = provider.complete("read this resume", images=["IMG64"])
    assert out == "ok"
    payload = mp.call_args.kwargs["json"]
    assert payload["images"] == ["IMG64"]


def test_openai_compatible_rejects_images():
    # openai_compatible 未接视觉 → 收到 images 必须 raise，让 FallbackChain 跳过。
    with pytest.raises(RuntimeError, match="does not support image"):
        OpenAICompatibleProvider(model="deepseek", base_url="http://x").complete("p", images=["x"])


def test_claude_cli_vision_saves_images_and_injects_paths():
    # claude_cli 视觉：把 base64 图落临时 PNG、路径注入 prompt 让 claude 用 Read 读；用后清理。
    provider = ClaudeCLIProvider()
    captured = {}

    def fake_run(args, **kwargs):
        prompt = args[-1]  # ["claude", "-p", full_prompt]
        paths = re.findall(r"\S*claude_vision_\S+\.png", prompt)
        captured["paths"] = paths
        captured["exist_during"] = [os.path.exists(p) for p in paths]
        m = MagicMock(); m.returncode = 0; m.stdout = b'{"ok":1}'
        return m

    with patch("subprocess.run", side_effect=fake_run):
        out = provider.complete("PROMPT", images=["aGVsbG8="])  # base64("hello")
    assert out == '{"ok":1}'
    assert len(captured["paths"]) == 1
    assert all(captured["exist_during"])          # 调用时临时文件在
    assert not any(os.path.exists(p) for p in captured["paths"])  # 调用后已清理


def test_codex_cli_vision_uses_i_flag_and_stdin():
    # codex_cli 视觉：`-i <FILE>` 附图 + prompt 走 stdin（-i 贪婪多值会吞位置参数）。
    provider = CodexCLIProvider()
    provider._exe = "codex.CMD"
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["stdin"] = kwargs.get("input")
        idxs = [i for i, a in enumerate(args) if a == "-i"]
        captured["paths"] = [args[i + 1] for i in idxs]
        captured["exist_during"] = [os.path.exists(p) for p in captured["paths"]]
        m = MagicMock(); m.returncode = 0; m.stdout = '{"ok":1}'
        return m

    with patch("subprocess.run", side_effect=fake_run):
        out = provider.complete("PROMPT", images=["aGVsbG8="])
    assert out == '{"ok":1}'
    assert "-i" in captured["args"]
    assert captured["stdin"] == "PROMPT"          # prompt 走 stdin
    assert "PROMPT" not in captured["args"]        # 不作位置参数（否则被 -i 吞）
    assert len(captured["paths"]) == 1
    assert all(captured["exist_during"])
    assert not any(os.path.exists(p) for p in captured["paths"])


# ── CodexCLIProvider ──────────────────────────────────────────────────────────

def test_codex_cli_provider_uses_exec_readonly_subcommand():
    provider = CodexCLIProvider()
    provider._exe = "codex.CMD"  # pin so the test does not depend on codex being on PATH
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "  codex response  "

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        result = provider.complete("my prompt")

    args_used = mock_run.call_args[0][0]
    # full resolved path (resolves the Windows .CMD shim), not bare "codex"
    assert args_used[0] == "codex.CMD"
    # non-interactive subcommand for codex 0.131 (the old `-q` flag is gone)
    assert "exec" in args_used
    # untrusted prompt (HR message text) must not get filesystem write access
    assert "-s" in args_used and "read-only" in args_used
    # classification needs no deep reasoning -> low effort
    assert 'model_reasoning_effort="low"' in args_used
    assert args_used[-1] == "my prompt"  # prompt is the final arg
    assert result == "codex response"


def test_codex_cli_provider_includes_system_in_prompt():
    provider = CodexCLIProvider()
    provider._exe = "codex.CMD"
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "response"

    with patch("subprocess.run", return_value=mock_result) as mock_run:
        provider.complete("user prompt", system="system text")

    full_prompt = mock_run.call_args[0][0][-1]
    assert "system text" in full_prompt
    assert "user prompt" in full_prompt


def test_codex_cli_provider_raises_on_nonzero_returncode():
    provider = CodexCLIProvider()
    provider._exe = "codex.CMD"
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stderr = "error message"

    with patch("subprocess.run", return_value=mock_result):
        with pytest.raises(RuntimeError, match="codex CLI failed"):
            provider.complete("prompt")


def test_codex_cli_provider_unavailable_when_not_on_path():
    # The Windows .CMD shim fix hinges on resolving an executable path; when codex is
    # not installed shutil.which returns None -> the provider must report unavailable
    # (so FallbackChain skips it) rather than crash.
    provider = CodexCLIProvider()
    provider._exe = None
    assert provider.is_available() is False
    with pytest.raises(RuntimeError, match="not found"):
        provider.complete("prompt")
