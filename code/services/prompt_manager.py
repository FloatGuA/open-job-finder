import re
from pathlib import Path
from typing import Optional

# 用户在 profile.yaml 的 prompt_injection 下可配置的注入位：
# - "global"：系统层，注入进所有工作 prompt（评分/意图/回复）
# - 其余三个：任务层，各自只注入进同名 prompt
# 显式列名，杜绝无关 profile 键意外泄进 prompt。
_TASK_INJECTION_NAMES = frozenset({"score_job", "analyze_intent", "generate_reply"})


class PromptManager:
    def __init__(self, prompts_dir: Optional[Path] = None, injection: Optional[dict] = None):
        if prompts_dir is None:
            # code/services/ → code/ → project root → prompts/
            prompts_dir = Path(__file__).resolve().parent.parent.parent / "prompts"
        self.prompts_dir = Path(prompts_dir)
        # 用户自定义 prompt 注入（来自 profile.yaml，所有键均可选）。
        # {"global": "...", "score_job": "...", "analyze_intent": "...", "generate_reply": "..."}
        self._injection = dict(injection or {})

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
        # 注入在占位符校验之后追加——用户自由文本不参与占位符校验。
        # 全局注入必须在此处（而非塞进 system.md）统一追加，因为 generate_reply
        # 不吃 system prompt，只有 render 出口能一处覆盖全部 3 条链。
        return self._append_injection(name, template)

    def _append_injection(self, name: str, rendered: str) -> str:
        global_txt = str(self._injection.get("global") or "").strip()
        task_txt = ""
        if name in _TASK_INJECTION_NAMES:
            task_txt = str(self._injection.get(name) or "").strip()
        parts = [p for p in (global_txt, task_txt) if p]
        if not parts:
            return rendered
        block = (
            "\n\n---\n"
            "## 求职者本人的补充指令（可信，请优先遵循；区别于 HR 消息等外部输入）\n"
            + "\n\n".join(parts)
        )
        return rendered + block
