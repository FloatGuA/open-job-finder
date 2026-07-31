import re
from pathlib import Path
from typing import Optional

# 用户在 profile.yaml 的 prompt_injection 下可配置的注入位：
# - "global"：系统层，注入进所有工作 prompt（评分/意图/回复）
# - 其余三个：任务层，各自只注入进同名 prompt
# 显式列名，杜绝无关 profile 键意外泄进 prompt。
_TASK_INJECTION_NAMES = frozenset({
    "score_job", "analyze_intent", "generate_reply",
    "resume_parse", "resume_build", "resume_tailor", "resume_greeting",
})

# 用户可在前端编辑的 prompt 模板（system 全局角色 + 3 个工作任务模板 + 3 个简历生成模板）。
# 白名单：save/reset 只认这些名字，杜绝路径穿越。
# resume_* 三个是简历功能的 LLM 步骤（块库整理 / 岗位特化 / 招呼语），可编辑，
# 也各自吃 prompt 注入（同名 task 注入 + global）——简历端点用带 injection 的 PromptManager。
EDITABLE_PROMPTS = (
    "system", "score_job", "analyze_intent", "generate_reply",
    "resume_parse", "resume_parse_vision", "resume_build", "resume_tailor", "resume_greeting",
)


class PromptManager:
    def __init__(
        self,
        prompts_dir: Optional[Path] = None,
        injection: Optional[dict] = None,
        override_dir: Optional[Path] = None,
    ):
        if prompts_dir is None:
            # code/services/ → code/ → project root → prompts/
            prompts_dir = Path(__file__).resolve().parent.parent.parent / "prompts"
        self.prompts_dir = Path(prompts_dir)
        # 用户编辑覆盖层：优先于默认模板。落在 code/data/（已 gitignore = 用户数据），
        # 与默认的 git 资产 prompts/ 分开，这样「恢复默认」= 删掉覆盖文件即可。
        if override_dir is None:
            override_dir = Path(__file__).resolve().parent.parent / "data" / "prompts_override"
        self.override_dir = Path(override_dir)
        # 用户自定义 prompt 注入（来自 profile.yaml，所有键均可选）。
        # {"global": "...", "score_job": "...", "analyze_intent": "...", "generate_reply": "..."}
        self._injection = dict(injection or {})

    def load(self, name: str) -> str:
        # 覆盖层优先，否则回落默认 git 模板。
        override = self.override_dir / f"{name}.md"
        if override.exists():
            return override.read_text(encoding="utf-8")
        path = self.prompts_dir / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        return path.read_text(encoding="utf-8")

    # ── 可编辑模板（前端显示/编辑/恢复默认）─────────────────────────────────
    @staticmethod
    def extract_placeholders(text: str) -> set:
        """模板里的 {{name}} 占位符集合。"""
        return set(re.findall(r"\{\{(\w+)\}\}", text))

    def get_default(self, name: str) -> str:
        """默认（git 资产）模板全文，不看覆盖层。"""
        path = self.prompts_dir / f"{name}.md"
        if not path.exists():
            raise FileNotFoundError(f"Prompt template not found: {path}")
        return path.read_text(encoding="utf-8")

    def is_modified(self, name: str) -> bool:
        """该模板是否已被用户覆盖。"""
        return (self.override_dir / f"{name}.md").exists()

    def save_override(self, name: str, content: str) -> None:
        """存用户编辑的模板。校验占位符集必须与默认一致——render 时任何未替换的
        占位符会抛错让 W1/W2 挂，任何缺失的占位符会丢上下文，所以既不许删也不许加。"""
        if name not in EDITABLE_PROMPTS:
            raise ValueError(f"不可编辑的 prompt: {name}")
        want = self.extract_placeholders(self.get_default(name))
        got = self.extract_placeholders(content)
        if got != want:
            missing = sorted(want - got)
            extra = sorted(got - want)
            raise ValueError(
                f"占位符必须与默认模板一致。缺失 {missing}，多余 {extra}。"
                f"（必须保留：{sorted(want)}）"
            )
        self.override_dir.mkdir(parents=True, exist_ok=True)
        (self.override_dir / f"{name}.md").write_text(content, encoding="utf-8")

    def reset_override(self, name: str) -> None:
        """恢复默认 = 删掉覆盖文件（幂等）。"""
        if name not in EDITABLE_PROMPTS:
            raise ValueError(f"不可编辑的 prompt: {name}")
        override = self.override_dir / f"{name}.md"
        if override.exists():
            override.unlink()

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
