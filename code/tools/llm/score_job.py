from services.exceptions import LLMParseError
from services.llm_parser import safe_parse_json
from tools.base import BaseTool, ToolResult

# Dimension weights — must sum to 1.0
WEIGHTS = {
    "skill_match":      0.40,
    "experience_match": 0.25,
    "city_match":       0.15,
    "salary_match":     0.10,
    "growth_potential": 0.10,
}



def _profile_summary(profile) -> str:
    """Format a Profile dataclass or dict into a short text for the prompt."""
    if hasattr(profile, "keywords"):
        kw = profile.keywords
        cities = profile.cities
        salary = profile.salary
        experience = profile.experience
    else:
        kw = profile.get("keywords") or []
        cities = profile.get("cities") or []
        salary = profile.get("salary") or ""
        experience = profile.get("experience") or []

    parts = []
    if kw:
        parts.append(f"Keywords: {', '.join(kw)}")
    if cities:
        parts.append(f"Cities: {', '.join(cities)}")
    if salary:
        parts.append(f"Expected salary: {salary}")
    if experience:
        parts.append(f"Experience: {'; '.join(experience)}")
    return " | ".join(parts)


class ScoreJob(BaseTool):
    name = "score_job"
    capability = "balanced"
    description = "LLM-based job scoring. Returns score (0-100), per-dimension scores, reason, provider_used."
    input_schema = {
        "type": "object",
        "properties": {
            "job_id":   {"type": "string"},
            "title":    {"type": "string"},
            "company":  {"type": "string"},
            "jd_text":  {"type": "string"},
            "profile":  {"type": "object"},
        },
        "required": ["job_id", "title", "company", "jd_text", "profile"],
    }

    def __init__(self, llm_client, prompt_manager, provider_name: str = None) -> None:
        self._llm = llm_client
        self._pm = prompt_manager
        self._provider_name = provider_name

    def execute(self, *, job_id: str, title: str, company: str, jd_text: str, profile) -> ToolResult:
        try:
            summary = _profile_summary(profile)
            prompt = self._pm.render("score_job", {
                "title":           title,
                "company":         company,
                "jd_text":         jd_text or "(no JD available)",
                "profile_summary": summary,
            })
            system = self._pm.load_system()
            text, provider = self._llm.complete(
                prompt, system=system,
                capability=self.capability,
                provider_name=self._provider_name,
            )
        except Exception as exc:
            return ToolResult(ok=False, error=f"LLM call failed: {exc}")

        try:
            parsed = safe_parse_json(text, required_fields={"dimensions": dict})
        except LLMParseError as exc:
            return ToolResult(ok=False, error=f"JSON parse failed: {exc}")

        dims_raw = parsed.get("dimensions") or {}
        dim_scores: dict[str, int] = {}
        for key in WEIGHTS:
            raw = dims_raw.get(key) or {}
            s = raw.get("score", 50) if isinstance(raw, dict) else 50
            dim_scores[key] = max(0, min(100, int(s)))

        score = int(sum(dim_scores[k] * w for k, w in WEIGHTS.items()))
        reason = str(parsed.get("overall_reason") or "")

        return ToolResult(ok=True, data={
            "score":        score,
            "dimensions":   dim_scores,
            "reason":       reason,
            "provider_used": provider,
        })
