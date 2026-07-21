from schemas import AppStatus
from tools.base import BaseTool, ToolResult
from tools.biz_logic.content_fingerprint import compute_content_hash

# Statuses where a re-encountered posting must NOT be re-applied. REJECTED is
# intentionally excluded — the user wants rejected/timeout jobs re-appliable when they
# resurface; this dedup only protects active/successful applications (e.g. don't re-apply
# to a job you're already INTERVIEWING for just because Boss rotated its encryptJobId).
# Mirrors _TERMINAL_STATUSES in classify_job_for_w1 (kept in sync intentionally).
_DEDUP_STATUSES = sorted({
    AppStatus.APPLIED.value,
    AppStatus.INTERVIEWING.value,
    AppStatus.OFFER.value,
})


class CheckContentDuplicate(BaseTool):
    name = "check_content_duplicate"
    description = (
        "Content-fingerprint dedup: detect the SAME posting re-encountered under a rotated "
        "encryptJobId. Returns is_duplicate + the computed content_hash."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "title":      {"type": "string"},
            "company_id": {"type": "string"},
            "jd_text":    {"type": "string"},
        },
        "required": ["title", "company_id", "jd_text"],
    }

    def __init__(self, db) -> None:
        self._db = db

    def execute(self, *, title: str, company_id: str, jd_text: str) -> ToolResult:
        content_hash = compute_content_hash(title, company_id, jd_text)
        placeholders = ",".join("?" * len(_DEDUP_STATUSES))
        row = self._db.conn.execute(
            f"SELECT job_id, status FROM applications "
            f"WHERE content_hash = ? AND status IN ({placeholders}) LIMIT 1",
            (content_hash, *_DEDUP_STATUSES),
        ).fetchone()
        if row:
            return ToolResult(ok=True, data={
                "is_duplicate": True,
                "content_hash": content_hash,
                "prior_job_id": row["job_id"],
                "prior_status": row["status"],
            })
        return ToolResult(ok=True, data={"is_duplicate": False, "content_hash": content_hash})
