import json
import os
import shutil
import subprocess
import tempfile
from typing import List, Optional

import requests
import yaml

from protocols import LLMProviderProtocol
from services.exceptions import AllProvidersFailedError
from services.logger import get_orchestrator_logger

logger = get_orchestrator_logger()


class ClaudeCLIProvider:
    name = "claude_cli"

    def is_available(self) -> bool:
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def complete(self, prompt: str, system: str = "", output_schema: Optional[dict] = None, think: bool = False, images: Optional[list] = None) -> str:
        # think: ignored — claude_cli is an agent shell with no thinking toggle.
        full_prompt = prompt if not system else f"{system}\n\n{prompt}"

        # 视觉输入：claude_cli 是 agent 壳，不吃 base64 image API；改把图片落成临时 PNG
        # 文件、在 prompt 里让 claude 用 Read 工具读它们。走用户的 Claude 订阅额度（不需
        # API key、不额外付费），对密集中文简历版面精度远超本地小 VL（真机实测）。仅简历
        # 视觉解析(vision 链)会走到这里——W1/W2 频繁调用不该用 CLI（抢主对话配额+慢）。
        tmp_files: list[str] = []
        if images:
            import base64
            for img_b64 in images:
                fd, path = tempfile.mkstemp(suffix=".png", prefix="claude_vision_")
                with os.fdopen(fd, "wb") as f:
                    f.write(base64.b64decode(img_b64))
                tmp_files.append(path)
            full_prompt += (
                "\n\n请先用 Read 工具读取以下图片文件，再按上面要求作答：\n"
                + "\n".join(tmp_files)
            )

        # Use list form (never shell=True) to prevent shell injection from prompt content.
        # Set PYTHONUTF8=1 so the subprocess stdout is always UTF-8 on Windows.
        env = {**os.environ, "PYTHONUTF8": "1"}
        # 视觉 + agent 读图较慢（真机 ~50s），给到 300s；纯文本仍 120s。
        timeout = 300 if images else 120
        try:
            result = subprocess.run(
                ["claude", "-p", full_prompt],
                capture_output=True,
                timeout=timeout,
                env=env,
            )
        finally:
            for path in tmp_files:
                try:
                    os.remove(path)
                except OSError:
                    pass
        if result.returncode != 0:
            stderr = (result.stderr or b"").decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"claude CLI failed (exit {result.returncode}): {stderr or 'no stderr output'}"
            )
        return result.stdout.decode("utf-8", errors="replace").strip()


class CodexCLIProvider:
    name = "codex_cli"

    def __init__(self):
        # Resolve the real executable up front. On Windows the npm-installed CLI is a
        # `codex.CMD` shim, and a bare `subprocess.run(["codex", ...])` (list form, no
        # shell) raises FileNotFoundError -- it never finds the .CMD. shutil.which
        # returns the full `...\codex.CMD` path, which list-form subprocess DOES run.
        self._exe = shutil.which("codex")

    def is_available(self) -> bool:
        if not self._exe:
            return False
        try:
            result = subprocess.run(
                [self._exe, "--version"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=10,
            )
            return result.returncode == 0
        except Exception:
            return False

    def complete(self, prompt: str, system: str = "", output_schema: Optional[dict] = None, think: bool = False, images: Optional[list] = None) -> str:
        # think: ignored — codex_cli is an agent shell (reasoning is its own -c knob).
        if not self._exe:
            raise RuntimeError("codex CLI not found on PATH")
        full_prompt = prompt if not system else f"{system}\n\n{prompt}"
        # `codex exec` is the non-interactive subcommand (codex 0.131; the old `-q`
        # flag is gone). The final model answer prints clean on stdout; the run
        # transcript/metadata goes to stderr. List form (never shell=True) prevents
        # shell injection from prompt content; `-s read-only` keeps the agent from
        # touching the filesystem -- the prompt is UNTRUSTED (HR message text), so it
        # must not be able to run write/destructive commands. force utf-8 so Chinese
        # JSON survives Windows' GBK default decode.
        # `-c model_reasoning_effort="low"`: classification/extraction needs no deep
        # reasoning, so cap the variable "thinking" tokens. NOTE: this does NOT cut the
        # big cost -- `codex exec` carries a ~15k-token irreducible base overhead per
        # call (its agent system prompt + tool schemas), unaffected by reasoning effort
        # or cwd. codex is an emergency fallback only; a real chat-completion provider
        # (anthropic_api / openai_compatible) is far cheaper for routine use.
        # --ephemeral: don't persist a session file per call. These are one-shot
        # classification/extraction calls with no resume, so session files are pure
        # disk clutter under automation.
        # --output-schema <FILE>: constrain the final answer to a JSON Schema when
        # the caller provides one (analyze/score expect a fixed JSON shape). Written to
        # a temp file per call and cleaned up after.
        args = [self._exe, "exec", "-s", "read-only", "--skip-git-repo-check", "--ephemeral",
                "-c", 'model_reasoning_effort="low"']
        schema_file = None
        tmp_files: list[str] = []
        stdin_input = None
        try:
            if images:
                # 视觉输入：codex 原生支持 `-i <FILE>` 附图（走用户 codex 订阅、不需 API key）。
                # 简历密集中文版面精度远超本地小 VL（真机实测）。⚠️ `-i` 的 <FILE>... 是贪婪多值、
                # 会把位置参数 prompt 当成图片路径吞掉 → prompt 必须走 stdin（否则报 no prompt）。
                import base64
                for img_b64 in images:
                    fd, path = tempfile.mkstemp(suffix=".png", prefix="codex_vision_")
                    with os.fdopen(fd, "wb") as f:
                        f.write(base64.b64decode(img_b64))
                    tmp_files.append(path)
                    args += ["-i", path]
                stdin_input = full_prompt
            else:
                if output_schema:
                    fd, schema_file = tempfile.mkstemp(suffix=".json", prefix="codex_schema_")
                    with os.fdopen(fd, "w", encoding="utf-8") as f:
                        json.dump(output_schema, f)
                    args += ["--output-schema", schema_file]
                args.append(full_prompt)
            result = subprocess.run(
                args,
                input=stdin_input,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300 if images else 180,
            )
        finally:
            if schema_file:
                try:
                    os.unlink(schema_file)
                except OSError:
                    pass
            for path in tmp_files:
                try:
                    os.remove(path)
                except OSError:
                    pass
        if result.returncode != 0:
            stderr = (result.stderr or "").strip()
            raise RuntimeError(
                f"codex CLI failed (exit {result.returncode}): {stderr[-400:] or 'no stderr output'}"
            )
        return result.stdout.strip()


class OllamaProvider:
    name: str

    def __init__(self, model: str, base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.name = f"ollama_{model}"

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=5)
            if resp.status_code != 200:
                return False
            data = resp.json()
            models = data.get("models", [])
            return any(model_info.get("name") == self.model for model_info in models)
        except Exception:
            return False

    def complete(self, prompt: str, system: str = "", output_schema: Optional[dict] = None, think: bool = False, images: Optional[list] = None) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            # think toggles the reasoning trace for hybrid thinking models (qwen3).
            # Callers pass think=False for intent classification (needs the model's
            # direct judgment, not a long think trace — that trace pushed qwen3:8b past
            # the read timeout under load; false is fast ~0.3-4s AND more accurate on
            # ambiguous HR messages than non-reasoning qwen2.5). Reply drafting passes
            # think=True so the model deliberates over wording. Ignored by models that
            # don't support thinking.
            "think": think,
        }
        if output_schema:
            # Ollama structured output: pass the JSON Schema as `format` so the model
            # is constrained to emit conforming JSON (no markdown fences / prose to
            # parse around) — a reliability win for the local qwen3 primary.
            payload["format"] = output_schema
        if images:
            # Ollama vision: `images` is a list of raw base64-encoded image strings
            # (no data-URI prefix). Only vision models (qwen2.5vl) act on them; a
            # text-only model would ignore the field. Used by the resume vision parse.
            payload["images"] = images
            # 一张简历页图片就有数千 image token，ollama 默认 num_ctx=4096 装不下
            # 「多页图片 + prompt」→ 400 exceed_context 或**静默截断第二页**（表现为区块串味/
            # 漏读）。视觉请求显式放大上下文，让整份简历都进模型。
            payload.setdefault("options", {})["num_ctx"] = 16384
        # 180s（2026-08-06 从 90s 调回）。90s 当初的理由是「卡住的生成不再拖 3 分钟才
        # fall through 到 codex」——**那个理由现在已经不成立**：balanced 链只剩 ollama 一个
        # provider，压根没有可以 fall through 的下家，缩短超时只是让调用更早地彻底失败。
        # 真机依据（run w2_20260806_0224）：GPU 被其它程序占满时（显存 93%、利用率 63%），
        # qwen3:8b 生成掉到 0.6 token/s，16 次调用里 9 次超过 60s、5 次撞满 90s 而失败；
        # 同一批调用在 GPU 空出来后只要 1-9s。慢的根因是算力被抢，不是模型卡死。
        # 视觉推理本来就更慢（30-60s 典型），保持 240s。
        timeout = 240 if images else 180
        resp = requests.post(f"{self.base_url}/api/generate", json=payload, timeout=timeout)
        if resp.status_code != 200:
            raise RuntimeError(f"Ollama returned status {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        if "response" not in data:
            raise RuntimeError(f"Ollama response missing 'response' key: {data}")
        return str(data["response"]).strip()


class AnthropicAPIProvider:
    name: str

    def __init__(self, model: str = "claude-sonnet-4-6", api_key_env: str = "ANTHROPIC_API_KEY"):
        self.model = model
        self.api_key = os.environ.get(api_key_env, "")
        self.name = f"anthropic_{model}"

    def is_available(self) -> bool:
        return bool(self.api_key)

    def complete(self, prompt: str, system: str = "", output_schema: Optional[dict] = None, think: bool = False, images: Optional[list] = None) -> str:
        # think: ignored — extended thinking is a separate Anthropic API param, not wired here.
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if images:
            # Vision: content is a list of image blocks (base64 PNG) followed by the
            # text prompt. Used as the cloud fallback for the resume vision parse.
            content = [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img}}
                for img in images
            ]
            content.append({"type": "text", "text": prompt})
        else:
            content = prompt
        body = {
            "model": self.model,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": content}],
        }
        if system:
            body["system"] = system

        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers=headers,
            json=body,
            timeout=120
        )
        if resp.status_code != 200:
            raise RuntimeError(f"Anthropic API error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        content = data.get("content")
        if not isinstance(content, list) or not content:
            raise RuntimeError(f"Anthropic response missing content blocks: {data}")

        first_block = content[0]
        text = first_block.get("text") if isinstance(first_block, dict) else None
        if text is None:
            raise RuntimeError(f"Anthropic response missing text content: {data}")

        return str(text).strip()


class OpenAICompatibleProvider:
    name: str

    def __init__(self, model: str, base_url: str, api_key_env: str = "OPENAI_API_KEY"):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = os.environ.get(api_key_env, "")
        self.name = f"openai_compat_{model}"

    def is_available(self) -> bool:
        return bool(self.api_key)

    def complete(self, prompt: str, system: str = "", output_schema: Optional[dict] = None, think: bool = False, images: Optional[list] = None) -> str:
        # think: ignored — no reasoning toggle wired for the OpenAI-compatible path.
        if images:
            raise RuntimeError("openai_compatible provider does not support image input")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "content-type": "application/json",
        }
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        body = {"model": self.model, "messages": messages}
        resp = requests.post(
            f"{self.base_url}/v1/chat/completions",
            headers=headers,
            json=body,
            timeout=120,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"OpenAI-compat API error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError(f"OpenAI-compatible response missing choices: {data}")

        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if content is None:
            raise RuntimeError(f"OpenAI-compatible response missing message content: {data}")

        return str(content).strip()


class FallbackChain:
    def __init__(self, providers: List[LLMProviderProtocol], chain_name: str = "default"):
        self.providers = providers
        self.chain_name = chain_name

    def complete(self, prompt: str, system: str = "", output_schema: Optional[dict] = None, think: bool = False, images: Optional[list] = None) -> tuple[str, str]:
        errors = []
        unavailable = []
        for provider in self.providers:
            try:
                if not provider.is_available():
                    logger.debug("[%s] Provider %s not available, skipping.", self.chain_name, provider.name)
                    unavailable.append(provider.name)
                    continue
                response = provider.complete(prompt, system, output_schema, think, images)
                return response, provider.name
            except Exception as exc:
                logger.warning("[%s] Provider %s failed: %s", self.chain_name, provider.name, exc)
                errors.append(f"{provider.name}: {exc}")

        if unavailable and not errors:
            detail = f"Unavailable providers: {', '.join(unavailable)}"
        elif unavailable:
            detail = f"Errors: {'; '.join(errors)}. Unavailable providers: {', '.join(unavailable)}"
        else:
            detail = f"Errors: {'; '.join(errors)}"

        raise AllProvidersFailedError(
            f"All providers failed for chain '{self.chain_name}'. {detail}"
        )

    @property
    def available_providers(self) -> List[str]:
        return [p.name for p in self.providers if p.is_available()]


def load_config(config_path: str = "config.yaml") -> dict:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_chain(specs: list, chain_name: str) -> FallbackChain:
    providers: List[LLMProviderProtocol] = []
    for spec in specs:
        ptype = spec.get("type")
        if ptype == "claude_cli":
            providers.append(ClaudeCLIProvider())
        elif ptype == "codex_cli":
            providers.append(CodexCLIProvider())
        elif ptype == "ollama":
            providers.append(OllamaProvider(
                model=spec["model"],
                base_url=spec.get("base_url", "http://localhost:11434")
            ))
        elif ptype == "anthropic_api":
            providers.append(AnthropicAPIProvider(
                model=spec.get("model", "claude-sonnet-4-6"),
                api_key_env=spec.get("api_key_env", "ANTHROPIC_API_KEY")
            ))
        elif ptype == "openai_compatible":
            providers.append(OpenAICompatibleProvider(
                model=spec["model"],
                base_url=spec["base_url"],
                api_key_env=spec.get("api_key_env", "OPENAI_API_KEY")
            ))
        else:
            raise ValueError(f"Unknown provider type: {ptype}")
    return FallbackChain(providers, chain_name=chain_name)


class ModelRouter:
    """Routes LLM calls to the appropriate FallbackChain based on capability level.

    Tools declare a capability ("fast"/"balanced"/"powerful") and optionally a
    provider_name to bypass the FallbackChain and call a specific provider directly.
    """

    LEVELS = ("fast", "balanced", "powerful", "vision")

    def __init__(self, chains: dict, default: str = "balanced"):
        self._chains = chains
        self._default = default

    def complete(
        self,
        prompt: str,
        system: str = "",
        capability: str = "balanced",
        provider_name: str = None,
        output_schema: Optional[dict] = None,
        think: bool = False,
        images: Optional[list] = None,
    ) -> tuple[str, str]:
        if provider_name:
            provider = self._find_provider(provider_name)
            if provider is None:
                raise ValueError(f"Provider '{provider_name}' not found in any chain")
            try:
                if not provider.is_available():
                    raise RuntimeError(f"Provider '{provider_name}' not available")
                return provider.complete(prompt, system, output_schema, think, images), provider.name
            except Exception as exc:
                # Log and fall through to capability chain (codex → claude → local order)
                logger.warning(
                    "Preferred provider '%s' failed (%s); falling back to '%s' chain",
                    provider_name, exc, capability,
                )

        chain = (
            self._chains.get(capability)
            or self._chains.get(self._default)
            or next(iter(self._chains.values()))
        )
        return chain.complete(prompt, system, output_schema, think, images)

    def _find_provider(self, name: str):
        for chain in self._chains.values():
            for p in chain.providers:
                if p.name == name:
                    return p
        return None

    def available_providers(self, capability: str = "balanced") -> List[str]:
        chain = self._chains.get(capability)
        return chain.available_providers if chain else []


def build_model_router(config: dict) -> ModelRouter:
    caps = config.get("llm", {}).get("capabilities", {})
    chains: dict = {}
    for level in ModelRouter.LEVELS:
        specs = caps.get(level) or []
        if specs:
            chains[level] = _build_chain(specs, chain_name=level)
    if not chains:
        raise ValueError("config.yaml: llm.capabilities must define at least one level")
    return ModelRouter(chains)


def build_llm_client(config: dict, chain_name: str = "scoring") -> FallbackChain:
    """Deprecated: use build_model_router() instead."""
    provider_specs = config.get("llm", {}).get("providers", {}).get(chain_name, [])
    return _build_chain(provider_specs, chain_name=chain_name)
