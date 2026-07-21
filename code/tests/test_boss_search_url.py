"""Tests for boss_search_url.build_search_url().

Verifies that profile fields are correctly translated to Boss直聘 URL parameters.
No network calls or file I/O needed for the core code-map tests.
"""
from urllib.parse import urlparse, parse_qs

import pytest

from services.boss_search_url import build_search_url, CITY_CODES, SALARY_CODES


def _parse(url: str) -> dict:
    """Return query params as {key: [value, ...]} dict."""
    return parse_qs(urlparse(url).query)


def _single(params: dict, key: str) -> str:
    """Return the single value for a query key (asserts exactly one)."""
    assert key in params, f"param '{key}' not found in URL"
    assert len(params[key]) == 1, f"expected single value for '{key}'"
    return params[key][0]


# ── Base URL structure ────────────────────────────────────────────────────────

class TestBaseUrl:
    def test_starts_with_zhipin(self):
        url = build_search_url({})
        assert url.startswith("https://www.zhipin.com/web/geek/jobs?")

    def test_default_city_is_quanguo(self):
        url = build_search_url({})
        params = _parse(url)
        assert _single(params, "city") == CITY_CODES["全国"]

    def test_no_query_param_when_empty_keyword(self):
        url = build_search_url({"keywords": []})
        assert "query=" not in url


# ── City mapping ──────────────────────────────────────────────────────────────

class TestCityMapping:
    def test_beijing_code(self):
        url = build_search_url({"cities": ["北京"]})
        assert _single(_parse(url), "city") == CITY_CODES["北京"]

    def test_shanghai_code(self):
        url = build_search_url({"cities": ["上海"]})
        assert _single(_parse(url), "city") == CITY_CODES["上海"]

    def test_override_city_kwarg(self):
        url = build_search_url({"cities": ["北京"]}, city="上海")
        assert _single(_parse(url), "city") == CITY_CODES["上海"]

    def test_unknown_city_falls_back_to_quanguo(self):
        url = build_search_url({"cities": ["火星"]})
        assert _single(_parse(url), "city") == CITY_CODES["全国"]


# ── Keyword ───────────────────────────────────────────────────────────────────

class TestKeyword:
    def test_keyword_in_query_param(self):
        url = build_search_url({"keywords": ["Python"]})
        assert _single(_parse(url), "query") == "Python"

    def test_override_keyword_kwarg(self):
        url = build_search_url({"keywords": ["Java"]}, keyword="Go")
        assert _single(_parse(url), "query") == "Go"

    def test_no_query_param_when_keyword_is_empty_string(self):
        url = build_search_url({}, keyword="")
        assert "query=" not in url


# ── Experience ────────────────────────────────────────────────────────────────

class TestExperience:
    def test_single_experience(self):
        url = build_search_url({"experience": ["1-3年"]})
        params = _parse(url)
        assert "experience" in params

    def test_multiple_experience_joined(self):
        url = build_search_url({"experience": ["1-3年", "3-5年"]})
        exp = _single(_parse(url), "experience")
        assert "," in exp

    def test_unknown_experience_ignored(self):
        url = build_search_url({"experience": ["火星年"]})
        assert "experience=" not in url


# ── Degree ────────────────────────────────────────────────────────────────────

class TestDegree:
    def test_degree_code_appended(self):
        url = build_search_url({"degree": ["本科"]})
        assert "degree" in _parse(url)

    def test_unknown_degree_ignored(self):
        url = build_search_url({"degree": ["玄学"]})
        assert "degree=" not in url


# ── Salary ────────────────────────────────────────────────────────────────────

class TestSalary:
    def test_salary_code_appended(self):
        url = build_search_url({"salary": "10-20K"})
        assert "salary" in _parse(url)

    def test_salary_code_value_correct(self):
        url = build_search_url({"salary": "10-20K"})
        assert _single(_parse(url), "salary") == SALARY_CODES["10-20K"]

    def test_unknown_salary_omitted(self):
        url = build_search_url({"salary": "无敌薪资"})
        assert "salary=" not in url

    def test_empty_salary_omitted(self):
        url = build_search_url({"salary": ""})
        assert "salary=" not in url


# ── Job type ──────────────────────────────────────────────────────────────────

class TestJobType:
    def test_known_job_type_produces_code(self):
        from services.boss_search_url import JOB_TYPE_CODES
        first_key = next(iter(JOB_TYPE_CODES))
        url = build_search_url({"job_types": [first_key]})
        assert "jobType" in _parse(url)

    def test_multiple_job_types_joined(self):
        from services.boss_search_url import JOB_TYPE_CODES
        keys = list(JOB_TYPE_CODES.keys())[:2]
        if len(keys) < 2:
            pytest.skip("not enough job type keys")
        url = build_search_url({"job_types": keys})
        jt = _single(_parse(url), "jobType")
        assert "," in jt

    def test_unknown_job_type_ignored(self):
        url = build_search_url({"job_types": ["外星人岗位_unknown"]})
        assert "jobType=" not in url


# ── Financing ─────────────────────────────────────────────────────────────────

class TestFinancing:
    def test_financing_code(self):
        url = build_search_url({"financing": ["A轮"]})
        assert "financing" in _parse(url)

    def test_multiple_financing_joined(self):
        url = build_search_url({"financing": ["A轮", "B轮"]})
        fn = _single(_parse(url), "financing")
        assert "," in fn


# ── boss_online ───────────────────────────────────────────────────────────────

class TestBossOnline:
    def test_boss_online_true_appends_param(self):
        url = build_search_url({"boss_online": True})
        assert "bossOnline=1" in url

    def test_boss_online_false_omits_param(self):
        url = build_search_url({"boss_online": False})
        assert "bossOnline" not in url

    def test_boss_online_default_omits_param(self):
        url = build_search_url({})
        assert "bossOnline" not in url


# ── Combined profile ──────────────────────────────────────────────────────────

class TestCombinedProfile:
    def test_full_profile_all_params_present(self):
        from services.boss_search_url import (
            JOB_TYPE_CODES, EXPERIENCE_CODES, DEGREE_CODES,
            SALARY_CODES, FINANCING_CODES,
        )
        profile = {
            "keywords": ["Python"],
            "cities": ["北京"],
            "experience": [next(iter(EXPERIENCE_CODES))],
            "degree": [next(iter(DEGREE_CODES))],
            "salary": next(iter(SALARY_CODES)),
            "job_types": [next(iter(JOB_TYPE_CODES))],
            "financing": [next(iter(FINANCING_CODES))],
        }
        url = build_search_url(profile)
        params = _parse(url)
        assert "query" in params
        assert "city" in params
        assert "experience" in params
        assert "degree" in params
        assert "salary" in params
        assert "jobType" in params
        assert "financing" in params
