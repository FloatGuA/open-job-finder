"""
Shared Boss直聘 search URL builder.

Used by both the Dashboard (server.py) and the Orchestrator so that the
automated search always navigates to the same URL the user previews in the UI.
"""
import json
from pathlib import Path
from urllib.parse import urlencode

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
BOSS_DISTRICTS_PATH  = _DATA_DIR / "boss_districts.json"
BOSS_POSITIONS_PATH  = _DATA_DIR / "boss_positions.json"
BOSS_INDUSTRIES_PATH = _DATA_DIR / "boss_industries.json"

BOSS_BASE_URL = "https://www.zhipin.com"

CITY_CODES = {
    "\u5168\u56fd": "100010000",
    "\u5317\u4eac": "101010100", "\u4e0a\u6d77": "101020100",
    "\u5e7f\u5dde": "101280100", "\u6df1\u5733": "101280600",
    "\u676d\u5dde": "101210100", "\u6210\u90fd": "101270100",
    "\u6e56\u5357\u957f\u6c99": "101250100", "\u5357\u4eac": "101190100",
    "\u6b66\u6c49": "101200100", "\u897f\u5b89": "101110100",
    "\u91cd\u5e86": "101040100", "\u5929\u6d25": "101030100",
    "\u82cf\u5dde": "101190400", "\u5408\u80a5": "101220100",
    "\u90d1\u5dde": "101180100", "\u957f\u6c99": "101250100",
    "\u6d4e\u5357": "101120100", "\u9752\u5c9b": "101120200",
    "\u53a6\u95e8": "101230200", "\u5b81\u6ce2": "101210400",
    "\u65e0\u9521": "101190200",
}

EXPERIENCE_CODES = {
    "\u7ecf\u9a8c\u4e0d\u9650": "101",
    "\u5728\u6821\u751f": "108",
    "\u5e94\u5c4a\u751f": "102",
    "1\u5e74\u4ee5\u5185": "103",
    "1-3\u5e74": "104",
    "3-5\u5e74": "105",
    "5-10\u5e74": "106",
    "10\u5e74\u4ee5\u4e0a": "107",
}

DEGREE_CODES = {
    "\u521d\u4e2d\u53ca\u4ee5\u4e0b": "209",
    "\u4e2d\u4e13/\u4e2d\u6280": "208",
    "\u9ad8\u4e2d": "206",
    "\u5927\u4e13": "202",
    "\u672c\u79d1": "203",
    "\u7855\u58eb": "204",
    "\u535a\u58eb": "205",
}

SALARY_CODES = {
    "3K\u4ee5\u4e0b": "402", "3-5K": "403", "5-10K": "404",
    "10-20K": "405", "20-50K": "406", "50K\u4ee5\u4e0a": "407",
}

JOB_TYPE_CODES = {
    "\u5168\u8109": "1901", "\u5b9e\u4e60": "1902", "\u517c\u804c": "1903",
}

FINANCING_CODES = {
    "\u672a\u878d\u8d44": "801", "\u5929\u4f7f\u8f6e": "802",
    "A\u8f6e": "803", "B\u8f6e": "804", "C\u8f6e": "805",
    "D\u8f6e\u53ca\u4ee5\u4e0a": "806",
    "\u5df2\u4e0a\u5e02": "807", "\u4e0d\u9700\u8981\u878d\u8d44": "808",
}


def _load_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default


def _flatten_filter_labels(items: list, parent: str = "") -> dict:
    """Recursively flatten a filter tree into {label: code} dict."""
    result: dict = {}
    for item in (items or []):
        label = item.get("label", "")
        code = str(item.get("code", ""))
        full_label = f"{parent}/{label}" if parent else label
        if code:
            result[full_label] = code
            result[label] = code
        result.update(_flatten_filter_labels(item.get("children") or [], full_label))
    return result


def build_search_url(profile: dict, keyword: str = None, city: str = None) -> str:
    """Build a Boss直聘 job search URL from profile preferences.

    Args:
        profile: dict loaded from data/profile.yaml
        keyword: override profile keywords (use for per-keyword iteration)
        city:    override profile cities   (use for per-city iteration)

    Returns:
        Full URL string, e.g. https://www.zhipin.com/web/geek/jobs?query=...
    """
    kw       = keyword or (profile.get("keywords") or [""])[0]
    city_name = city   or (profile.get("cities")   or ["\u5168\u56fd"])[0]

    exp_list       = profile.get("experience")     or []
    deg_list       = profile.get("degree")         or []
    sal_val        = profile.get("salary")         or ""
    job_types      = profile.get("job_types")      or []
    financing      = profile.get("financing")      or []
    districts      = profile.get("districts")      or []
    position_types = profile.get("position_types") or []
    industries     = profile.get("industries")     or []
    boss_online    = bool(profile.get("boss_online", False))

    params: list = [("city", CITY_CODES.get(city_name, "100010000"))]
    if kw:
        params.append(("query", kw))

    exp_codes = [EXPERIENCE_CODES[e] for e in exp_list if e in EXPERIENCE_CODES]
    if exp_codes:
        params.append(("experience", ",".join(exp_codes)))

    deg_codes = [DEGREE_CODES[d] for d in deg_list if d in DEGREE_CODES]
    if deg_codes:
        params.append(("degree", ",".join(deg_codes)))

    sal_code = SALARY_CODES.get(sal_val) if sal_val else None
    if sal_code:
        params.append(("salary", sal_code))

    jt_codes = [JOB_TYPE_CODES[j] for j in job_types if j in JOB_TYPE_CODES]
    if jt_codes:
        params.append(("jobType", ",".join(jt_codes)))

    fn_codes = [FINANCING_CODES[f] for f in financing if f in FINANCING_CODES]
    if fn_codes:
        params.append(("financing", ",".join(fn_codes)))

    if districts:
        dist_data = _load_json(BOSS_DISTRICTS_PATH, {})
        dist_map = {d["label"]: str(d["code"]) for d in dist_data.get(city_name, [])}
        dist_code = dist_map.get(districts[0], districts[0])
        params.append(("district", dist_code))

    if position_types:
        pos_map = _flatten_filter_labels(_load_json(BOSS_POSITIONS_PATH, []))
        pos_codes = [pos_map.get(p, p) for p in position_types]
        params.append(("position", ",".join(pos_codes)))

    if industries:
        ind_map = _flatten_filter_labels(_load_json(BOSS_INDUSTRIES_PATH, []))
        ind_codes = [ind_map.get(i, i) for i in industries]
        params.append(("industry", ",".join(ind_codes)))

    if boss_online:
        params.append(("bossOnline", "1"))

    return f"{BOSS_BASE_URL}/web/geek/jobs?{urlencode(params)}"
