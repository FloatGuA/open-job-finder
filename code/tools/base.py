from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolResult:
    ok: bool
    data: dict = field(default_factory=dict)
    error: Optional[str] = None


class BaseTool(ABC):
    name: str
    description: str
    input_schema: dict  # JSON Schema, for future LLM tool enumeration

    @abstractmethod
    def execute(self, **kwargs) -> ToolResult: ...
