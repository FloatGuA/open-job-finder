import os

from tools.base import BaseTool, ToolResult
from tools.browser.helpers import (
    _ele_any,
    _human_pause,
    count_resume_delivered_markers,
    wait_resume_delivered,
)

# Python \uXXXX expands to actual chars at runtime; source stays ASCII-only.
_RESUME_FILE_INPUT = [
    "css:.btn-primary.btn-file input[type=file]",
    "css:input[ka='user-resume-upload-file']",
    "css:input[type=file]",
]
_RESUME_CONFIRM = [
    "css:.pop-submit",
    "css:.btn-sure",
    "css:.btn-sure-v2",
    "xpath://button[text()='\u786e\u5b9a']",
    "xpath://button[contains(text(),'\u786e\u5b9a')]",
    "xpath://button[contains(text(),'\u53d1\u9001')]",
    "xpath://button[contains(text(),'\u786e\u8ba4')]",
]


class UploadResumeFile(BaseTool):
    """把本地 PDF 简历作为附件发给 HR（w2.auto_send_adapted_resume 开启后才走）。

    ⚠️ 选择器对真实 Boss 页面**从未验证过**（这段代码一直是死代码）。首次启用需真机
    试错；失败时调用方回退到 Boss 站内简历，所以风险可控。

    `sent` 是唯一权威成功信号：只有出现**新的**「已发送简历」系统气泡才算真发出去。
    「找到输入框 + 点了确定」远远不够——项目在工具栏那条路上已经吃过一次亏（点了
    但没送达却记成 resume_sent，会话被当作已处理，HR 其实什么都没收到）。
    """

    name = "upload_resume_file"
    description = "Upload a local resume PDF as an attachment in the open Boss chat; verifies delivery."
    input_schema = {
        "type": "object",
        "properties": {"resume_path": {"type": "string"}},
        "required": ["resume_path"],
    }

    def __init__(self, browser=None):
        self._browser = browser

    def execute(self, resume_path: str) -> ToolResult:
        if self._browser is None:
            return ToolResult(ok=False, data={"sent": False}, error="browser not initialized")
        if not os.path.isfile(resume_path):
            return ToolResult(ok=False, data={"sent": False}, error=f"resume file not found: {resume_path}")
        page = self._browser
        try:
            before = count_resume_delivered_markers(page)

            file_input = _ele_any(page, _RESUME_FILE_INPUT, timeout=3)
            if not file_input:
                return ToolResult(ok=False, data={"sent": False}, error="resume file input not found")

            file_input.set.input_file(resume_path)
            _human_pause(1.0, 1.5)

            # 确认框不是每种账号都出现（跨境/大陆行为不同），没有就直接看是否已送达。
            confirm = _ele_any(page, _RESUME_CONFIRM, timeout=4)
            if confirm:
                confirm.click()
                _human_pause(0.8, 1.5)

            sent = wait_resume_delivered(page, before)
            return ToolResult(
                ok=bool(sent),
                data={"sent": sent, "confirm_clicked": bool(confirm), "path": resume_path},
                error=None if sent else "upload not confirmed (no new delivered-resume system message appeared)",
            )
        except Exception as exc:
            return ToolResult(ok=False, data={"sent": False}, error=str(exc))
