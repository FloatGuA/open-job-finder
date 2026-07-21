import time
from typing import List, Optional

from tools.base import BaseTool, ToolResult


_LARGE_FIELDS = frozenset({"jd_text", "messages", "cards", "conversations", "states", "conversations_to_process", "items", "decisions"})


class ToolRegistry:
    """Object-oriented tool registry that holds shared resources and manages BaseTool instances."""

    def __init__(
        self,
        browser=None,
        db=None,
        llm_client=None,
        prompt_manager=None,
        logger=None,
    ) -> None:
        self._tools: dict[str, BaseTool] = {}
        self.browser = browser
        self.db = db
        self.llm_client = llm_client
        self.prompt_manager = prompt_manager
        self.logger = logger
        self._current_step: str = ""
        self._current_scope: dict = {}

    def register(self, tool: BaseTool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        if name not in self._tools:
            available = ", ".join(sorted(self._tools)) or "<none>"
            raise KeyError(f"Tool '{name}' not found. Available: {available}")
        return self._tools[name]

    def list_tools(self) -> List[str]:
        return sorted(self._tools)

    def set_context(self, step: str, scope: dict) -> None:
        self._current_step = step
        self._current_scope = scope
        # Surface a step-entry 'running' event so the frontend tree can show the
        # in-progress node (steps otherwise only emit on completion). SSE-only;
        # does not pollute the file log.
        if self.logger is not None:
            self.logger.emit_step_running(step, scope)

    def call(self, name: str, **kwargs) -> ToolResult:
        tool = self.get(name)
        start_ts = time.time()
        try:
            result = tool.execute(**kwargs)
        except Exception as exc:
            # Some tools fail-fast by raising (e.g. DB reads, kept intentionally
            # fail-hard). Without this except, the exception would skip the
            # log_tool call below and the failure would never appear in the tool
            # trace. Log it here, then re-raise to preserve fail-fast -- we record
            # the error without swallowing it.
            if self.logger is not None:
                self.logger.log_tool(
                    step=self._current_step,
                    tool=name,
                    scope=self._current_scope,
                    status="failed",
                    duration_ms=int((time.time() - start_ts) * 1000),
                    data={},
                    error=str(exc),
                )
            raise
        duration_ms = int((time.time() - start_ts) * 1000)
        if self.logger is not None:
            status = "successful" if result.ok else "failed"
            log_data = {k: v for k, v in (result.data or {}).items() if k not in _LARGE_FIELDS}
            self.logger.log_tool(
                step=self._current_step,
                tool=name,
                scope=self._current_scope,
                status=status,
                duration_ms=duration_ms,
                data=log_data,
                error=result.error,
            )
        return result


