"""score_job: the CODE half of "models judge, code decides".

The LLM returns five independent dimension scores; Python does the weighting and
produces the number that gates every apply decision. That arithmetic had no tests
at all, so a wrong weight, a typo'd dimension key (silently defaulting to 50) or a
broken clamp would have shipped unnoticed.

The LLM itself is stubbed -- what is under test is what we do with its answer.
"""
import pytest

from tools.llm.score_job import WEIGHTS, ScoreJob


class _PM:
    def render(self, name, ctx):
        return "prompt"

    def load_system(self):
        return "system"


class _LLM:
    def __init__(self, payload):
        self._payload = payload

    def complete(self, prompt, system=None, capability=None, provider_name=None):
        return self._payload, "stub_provider"


def _run(payload, profile=None):
    tool = ScoreJob(llm_client=_LLM(payload), prompt_manager=_PM())
    return tool.execute(job_id="j1", title="T", company="C", jd_text="jd",
                        profile=profile or {"keywords": ["python"]})


def _dims(**scores):
    import json
    return json.dumps({
        "dimensions": {k: {"score": v} for k, v in scores.items()},
        "overall_reason": "reason text",
    })


# ---- the weighting itself -----------------------------------------------------


def test_weights_sum_to_one():
    """A drifting total silently rescales every score in the system."""
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_all_dimensions_full_marks_is_100():
    res = _run(_dims(**{k: 100 for k in WEIGHTS}))
    assert res.ok
    assert res.data["score"] == 100


def test_all_dimensions_zero_is_0():
    res = _run(_dims(**{k: 0 for k in WEIGHTS}))
    assert res.data["score"] == 0


def test_weighted_sum_is_computed_per_dimension():
    """Skill 100 with everything else 0 must yield exactly the skill weight (40),
    which pins both the weight value and the fact that it is a weighted sum rather
    than an average."""
    scores = {k: 0 for k in WEIGHTS}
    scores["skill_match"] = 100
    res = _run(_dims(**scores))
    assert res.data["score"] == int(100 * WEIGHTS["skill_match"])


def test_mixed_scores_match_manual_calculation():
    scores = {"skill_match": 80, "experience_match": 60, "city_match": 100,
              "salary_match": 40, "growth_potential": 20}
    expected = int(sum(scores[k] * WEIGHTS[k] for k in WEIGHTS))
    res = _run(_dims(**scores))
    assert res.data["score"] == expected


# ---- defensive handling of what the model returns -----------------------------


def test_missing_dimension_defaults_to_50():
    """A model that omits a dimension must not crash or score it 0 -- the neutral
    default is deliberate. This also catches a renamed/typo'd key in WEIGHTS."""
    res = _run(_dims(skill_match=100))  # the other four are absent
    assert res.ok
    assert res.data["dimensions"]["city_match"] == 50


def test_out_of_range_scores_are_clamped():
    scores = {k: 50 for k in WEIGHTS}
    scores["skill_match"] = 999
    scores["salary_match"] = -50
    res = _run(_dims(**scores))
    assert res.data["dimensions"]["skill_match"] == 100
    assert res.data["dimensions"]["salary_match"] == 0


def test_non_dict_dimension_entry_falls_back_to_50():
    """Models sometimes return `"skill_match": 80` instead of `{"score": 80}`."""
    import json
    payload = json.dumps({"dimensions": {"skill_match": 80}, "overall_reason": "r"})
    res = _run(payload)
    assert res.ok
    assert res.data["dimensions"]["skill_match"] == 50


def test_float_scores_are_accepted():
    res = _run(_dims(**{k: 77.6 for k in WEIGHTS}))
    assert res.ok
    assert res.data["dimensions"]["skill_match"] == 77


# ---- failure paths ------------------------------------------------------------


def test_unparseable_response_fails_loudly():
    res = _run("not json at all")
    assert not res.ok
    assert "parse" in (res.error or "").lower()


def test_llm_exception_is_reported_not_swallowed():
    class _Boom:
        def complete(self, *a, **kw):
            raise RuntimeError("connection refused")

    tool = ScoreJob(llm_client=_Boom(), prompt_manager=_PM())
    res = tool.execute(job_id="j1", title="T", company="C", jd_text="jd",
                       profile={"keywords": []})
    assert not res.ok
    assert "connection refused" in (res.error or "")


def test_provider_used_is_reported():
    """provider_used is what makes a degraded run traceable to its fallback."""
    res = _run(_dims(**{k: 50 for k in WEIGHTS}))
    assert res.data["provider_used"] == "stub_provider"
