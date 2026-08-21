from tools.base import BaseTool, ToolResult


class MatchResume(BaseTool):
    """按岗位从用户已存的简历里选出「该发哪一份」并记进会话行。

    只选不写：Agent 从用户自己维护的几份简历里挑，永不生成/改写简历内容
    （产品边界，用户 2026-08-03 定）。匹配是确定性关键词规则、不调 LLM，
    所以「为什么选了这份」用户一眼可懂、可预期。

    默认行为下这只是条**建议**（真正发出去的仍是 Boss 站内简历），它服务于
    ①前端告诉用户该发哪份 ②事后追溯路由选得准不准。
    """

    name = "match_resume"
    description = "Pick which stored resume fits this job and record it on the conversation."
    input_schema = {
        "type": "object",
        "properties": {
            "conv_id": {"type": "string"},
            "job_id": {"type": "string"},
        },
        "required": ["conv_id"],
    }

    def __init__(self, db) -> None:
        self._db = db

    def execute(self, conv_id: str, job_id: str = "") -> ToolResult:
        from services.resume_library import ResumeLibrary

        job_title = ""
        if job_id:
            rec = self._db.get(job_id)
            if rec:
                job_title = rec.title or ""

        # 从**简历库**里挑（`data/resumes/library/`），只在勾了「允许发送」的里面挑。
        pick = ResumeLibrary().pick(job_title=job_title)
        if not pick.get("file"):
            # 一份可发的都没有：如实报告，不写库（别把空建议落成"选过了"）
            return ToolResult(ok=True, data={"resume": "", "matched": False,
                                             "reason": pick.get("reason", "")})

        self._db.set_matched_resume(conv_id, pick["name"], pick["reason"])
        return ToolResult(ok=True, data={
            "resume": pick["name"],
            "matched": pick["matched"],
            "reason": pick["reason"],
            "job_title": job_title,
        })
