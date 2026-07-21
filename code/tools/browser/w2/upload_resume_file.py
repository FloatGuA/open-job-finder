import os

from tools.base import BaseTool, ToolResult
from tools.browser.helpers import _ele_any, _human_pause

# Python \uXXXX expands to actual chars at runtime; source stays ASCII-only.
_RESUME_FILE_INPUT = [
    "css:.btn-primary.btn-file input[type=file]",
    "css:input[ka='user-resume-upload-file']",
]
_RESUME_CONFIRM = [
    "css:.pop-submit",
    "css:.btn-sure",
    "xpath://button[text()='\u786e\u5b9a']",
    "xpath://button[contains(text(),'\u786e\u5b9a')]",
    "xpath://button[contains(text(),'\u53d1\u9001')]",
    "xpath://button[contains(text(),'\u786e\u8ba4')]",
]


class UploadResumeFile(BaseTool):
    name = "upload_resume_file"
    description = "Upload a resume PDF via the file input control in Boss Zhipin chat"
    input_schema = {
        "type": "object",
        "properties": {"resume_path": {"type": "string"}},
        "required": ["resume_path"],
    }

    def __init__(self, browser=None):
        self._browser = browser

    def execute(self, resume_path: str) -> ToolResult:
        if self._browser is None:
            return ToolResult(ok=False, data={}, error="browser not initialized")
        if not os.path.isfile(resume_path):
            return ToolResult(ok=False, data={}, error=f"resume file not found: {resume_path}")
        page = self._browser
        try:
            file_input = _ele_any(page, _RESUME_FILE_INPUT, timeout=3)
            if not file_input:
                return ToolResult(ok=False, data={}, error="resume file input not found")

            file_input.set.input_file(resume_path)
            _human_pause(1.0, 1.5)

            confirm = _ele_any(page, _RESUME_CONFIRM, timeout=4)
            if not confirm:
                return ToolResult(ok=False, data={}, error="confirm button not found after file upload")

            confirm.click()
            _human_pause(0.8, 1.5)
            return ToolResult(ok=True, data={})
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=str(exc))
