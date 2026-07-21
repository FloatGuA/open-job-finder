# Task 003 — LLM Client (Multi-Provider with Fallback)

## 目标
Implement all four LLM provider backends and the FallbackChain, plus the `build_llm_client()` factory function that reads config.yaml to assemble provider chains for different tasks.

## 上下文
- 依赖：Task 001 (protocols.py, services/exceptions.py, services/logger.py)
- 代码目录：`C:/Coding/AI-factory-projects/open-job-finder/code/`

## 实现要求

### `services/llm_client.py`

#### 1. ClaudeCLIProvider

Calls the `claude` CLI via `subprocess.run`.

```python
class ClaudeCLIProvider:
    name = "claude_cli"

    def is_available(self) -> bool:
        """Run `claude --version`, return True if exit code 0."""

    def complete(self, prompt: str, system: str = "") -> str:
        """
        Build command: ["claude", "-p", prompt]
        If system is non-empty, prepend it to prompt as: f"System: {system}\n\n{prompt}"
        Run with subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        Return stdout. Raise RuntimeError if returncode != 0 (include stderr in message).
        """
```

- Timeout: 120 seconds.
- Strip leading/trailing whitespace from stdout before returning.

#### 2. OllamaProvider

Calls Ollama HTTP API at `base_url` (default: `http://localhost:11434`).

```python
class OllamaProvider:
    name: str  # set to f"ollama_{model}"

    def __init__(self, model: str, base_url: str = "http://localhost:11434"):
        ...

    def is_available(self) -> bool:
        """GET {base_url}/api/tags, return True if status 200 and model in response."""

    def complete(self, prompt: str, system: str = "") -> str:
        """
        POST {base_url}/api/generate
        Body: {"model": self.model, "prompt": prompt, "system": system, "stream": false}
        Return response["response"]. Timeout: 180s.
        Raise RuntimeError on non-200 status or missing "response" key.
        """
```

#### 3. AnthropicAPIProvider

Calls `https://api.anthropic.com/v1/messages` directly via HTTP (no SDK).

```python
class AnthropicAPIProvider:
    name: str  # set to f"anthropic_{model}"

    def __init__(self, model: str = "claude-sonnet-4-6", api_key_env: str = "ANTHROPIC_API_KEY"):
        self.model = model
        self.api_key = os.environ.get(api_key_env, "")

    def is_available(self) -> bool:
        """Return True if self.api_key is non-empty."""

    def complete(self, prompt: str, system: str = "") -> str:
        """
        POST https://api.anthropic.com/v1/messages
        Headers: x-api-key, anthropic-version: 2023-06-01, content-type: application/json
        Body: {
          "model": self.model,
          "max_tokens": 2048,
          "system": system (omit if empty),
          "messages": [{"role": "user", "content": prompt}]
        }
        Return response["content"][0]["text"]. Timeout: 120s.
        """
```

#### 4. OpenAICompatibleProvider

Calls any OpenAI-compatible API endpoint.

```python
class OpenAICompatibleProvider:
    name: str  # set to f"openai_compat_{model}"

    def __init__(self, model: str, base_url: str, api_key_env: str = "OPENAI_API_KEY"):
        ...

    def is_available(self) -> bool:
        """Return True if api_key is non-empty."""

    def complete(self, prompt: str, system: str = "") -> str:
        """
        POST {base_url}/v1/chat/completions
        Body: {
          "model": self.model,
          "messages": [
            {"role": "system", "content": system},  # omit if system is empty
            {"role": "user", "content": prompt}
          ]
        }
        Return response["choices"][0]["message"]["content"]. Timeout: 120s.
        """
```

#### 5. FallbackChain

```python
class FallbackChain:
    def __init__(self, providers: List[LLMProviderProtocol], chain_name: str = "default"):
        self.providers = providers
        self.chain_name = chain_name

    def complete(self, prompt: str, system: str = "") -> tuple[str, str]:
        """
        Try each provider in order:
        1. Check is_available(). Skip if False, log DEBUG.
        2. Call complete(). On success, return (response_text, provider.name).
        3. On exception, log WARNING with provider name + error, try next.
        Raise AllProvidersFailedError if all providers fail or are unavailable.
        """

    @property
    def available_providers(self) -> List[str]:
        """Return list of provider names where is_available() is True."""
```

#### 6. `build_llm_client(config: dict, chain_name: str) -> FallbackChain`

Factory function that reads the `llm.providers.{chain_name}` section of config and instantiates the appropriate providers.

```python
def build_llm_client(config: dict, chain_name: str = "scoring") -> FallbackChain:
    """
    config is the parsed config.yaml dict.
    Reads config["llm"]["providers"][chain_name] — a list of provider specs.
    For each spec:
      - type: "claude_cli"  → ClaudeCLIProvider()
      - type: "ollama"      → OllamaProvider(model=spec["model"], base_url=spec.get("base_url", ...))
      - type: "anthropic_api" → AnthropicAPIProvider(model=spec["model"], api_key_env=spec.get("api_key_env", "ANTHROPIC_API_KEY"))
      - type: "openai_compatible" → OpenAICompatibleProvider(...)
    Returns FallbackChain(providers, chain_name=chain_name).
    Raise ValueError for unknown provider type.
    """
```

Also add a convenience function:
```python
def load_config(config_path: str = "config.yaml") -> dict:
    """Load and return config.yaml as dict. Raise FileNotFoundError if missing."""
```

## 文件清单

- `code/services/llm_client.py`：all 4 providers + FallbackChain + build_llm_client + load_config

## Smoke Test

```bash
cd C:/Coding/AI-factory-projects/open-job-finder/code

# Test 1: ClaudeCLIProvider availability check (should work if claude is installed)
python -c "
from services.llm_client import ClaudeCLIProvider
p = ClaudeCLIProvider()
print('claude_cli available:', p.is_available())
"

# Test 2: OllamaProvider availability check (may be False if Ollama not running)
python -c "
from services.llm_client import OllamaProvider
p = OllamaProvider(model='llama3.2')
print('ollama available:', p.is_available())
"

# Test 3: FallbackChain with unavailable providers raises AllProvidersFailedError
python -c "
from services.llm_client import OllamaProvider, FallbackChain
from services.exceptions import AllProvidersFailedError

class AlwaysUnavailable:
    name = 'fake'
    def is_available(self): return False
    def complete(self, prompt, system=''): return ''

chain = FallbackChain([AlwaysUnavailable()])
try:
    chain.complete('test')
    assert False, 'Should have raised'
except AllProvidersFailedError as e:
    print('FallbackChain correctly raises AllProvidersFailedError:', e)
"

# Test 4: build_llm_client from config
python -c "
from services.llm_client import build_llm_client, load_config
config = load_config('config.yaml')
chain = build_llm_client(config, chain_name='scoring')
print('scoring chain providers:', [p.name for p in chain.providers])
print('available:', chain.available_providers)
"

# Test 5: End-to-end with ClaudeCLI (only if available)
python -c "
from services.llm_client import ClaudeCLIProvider, FallbackChain
p = ClaudeCLIProvider()
if p.is_available():
    chain = FallbackChain([p])
    response, used = chain.complete('Say exactly: HELLO')
    print(f'Response from {used}:', response[:50])
else:
    print('claude_cli not available, skipping live test')
"
```

<!-- FACTORY:DONE -->
