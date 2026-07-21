"""Unit tests for ModelRouter and CodexCLIProvider (Task: llm-model-router)."""
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from services.llm_client import (
    CodexCLIProvider,
    FallbackChain,
    ModelRouter,
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
    fast_chain.complete.assert_called_once_with("hello", "", None, False)

    text, provider = router.complete("hello", capability="powerful")
    assert text == "powerful-response"
    powerful_chain.complete.assert_called_once_with("hello", "", None, False)


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
