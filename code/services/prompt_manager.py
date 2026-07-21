import re
from pathlib import Path
from typing import Optional


class PromptManager:
    def __init__(self, prompts_dir: Optional[Path] = None):
        if prompts_dir is None:
            # code/services/ → code/ → project root → prompts/
            prompts_dir = Path(__file__).resolve().parent.parent.parent / "prompts"
        self.prompts_dir = Path(prompts_dir)

    def load(self, name: str) -> str:
        path = self.prompts_dir / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        return path.read_text(encoding="utf-8")

    def load_system(self) -> str:
        try:
            return self.load("system")
        except FileNotFoundError:
            return ""

    def render(self, name: str, context: dict) -> str:
        template = self.load(name)
        for key, value in context.items():
            template = template.replace("{{" + key + "}}", str(value))
        remaining = re.findall(r"\{\{(\w+)\}\}", template)
        if remaining:
            raise ValueError(
                f"Unreplaced placeholders in '{name}': {remaining}"
            )
        return template
