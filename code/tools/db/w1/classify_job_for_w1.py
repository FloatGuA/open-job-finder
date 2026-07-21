from schemas import AppStatus
from tools.base import BaseTool, ToolResult

# REJECTED 不在终态集合：被拒/超时无回应的岗位若在搜索页重新刷到，允许重投。
# Boss 不过滤已投岗位，老岗位会持续复现；用户要求重新出现就再投一次。
# upsert_application 用 ON CONFLICT 直接覆写 status，绕过状态机校验，REJECTED→APPLIED 能落库。
_TERMINAL_STATUSES = {
    AppStatus.APPLIED.value,
    AppStatus.INTERVIEWING.value,
    AppStatus.OFFER.value,
}


class ClassifyJobForW1(BaseTool):
    name = "classify_job_for_w1"
    description = "Classify a job_id into W1 routing: full_pipeline / apply_only / skip."
    input_schema = {
        "type": "object",
        "properties": {
            "job_id": {"type": "string"},
        },
        "required": ["job_id"],
    }

    def __init__(self, db) -> None:
        self._db = db

    def execute(self, *, job_id: str) -> ToolResult:
        row = self._db.conn.execute(
            "SELECT status FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()

        if row is None:
            return ToolResult(ok=True, data={
                "action": "full_pipeline",
                "reason": "not in DB, process from scratch",
            })

        status = row["status"]

        if status in _TERMINAL_STATUSES:
            return ToolResult(ok=True, data={
                "action": "skip",
                "reason": f"status {status}, already processed",
                "prior_status": status,
            })

        # REJECTED (重投), FOUND, or any unrecognised status → full pipeline
        return ToolResult(ok=True, data={
            "action": "full_pipeline",
            "reason": f"status {status}, run full pipeline",
        })
