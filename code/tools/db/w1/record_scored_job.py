from typing import Optional

from tools.base import BaseTool, ToolResult


class RecordScoredJob(BaseTool):
    """Record one W1 scoring event (applied or skipped) for score-eval data
    collection. Thin shell over tracker.record_scored_job (SQL lives there)."""

    name = "record_scored_job"
    description = "Record a W1 scoring event (applied or skipped) for score-eval data collection."
    input_schema = {
        "type": "object",
        "properties": {
            "job_id":          {"type": "string"},
            "title":           {"type": "string"},
            "company":         {"type": "string"},
            "jd_text":         {"type": "string"},
            "score":           {"type": "integer"},
            "dimensions":      {"type": "object"},
            "reason":          {"type": "string"},
            "provider_used":   {"type": "string"},
            "threshold":       {"type": "integer"},
            "above_threshold": {"type": "boolean"},
        },
        "required": ["job_id", "title", "company", "score"],
    }

    def __init__(self, db) -> None:
        self._db = db

    def execute(
        self,
        *,
        job_id: str,
        title: str,
        company: str,
        score: int,
        jd_text: str = "",
        dimensions: Optional[dict] = None,
        reason: str = "",
        provider_used: str = "",
        threshold: int = 0,
        above_threshold: bool = False,
    ) -> ToolResult:
        try:
            self._db.record_scored_job(
                job_id=job_id,
                title=title,
                company=company,
                jd_text=jd_text,
                score=score,
                dimensions=dimensions or {},
                reason=reason,
                provider_used=provider_used,
                threshold=threshold,
                above_threshold=above_threshold,
            )
            return ToolResult(ok=True, data={})
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=str(exc))
