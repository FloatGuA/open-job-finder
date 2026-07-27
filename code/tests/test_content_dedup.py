"""W1 content-fingerprint helpers.

The content hash + company-id extraction still exist (the hash is recorded on the
application row), but W1 no longer SKIPS on them: as of 2026-07-28 the DB-based dedup
was removed because it dropped real opportunities (see pipeline/w1/card_pipeline.py).
These tests cover only the pure helpers that remain.
"""
from tools.biz_logic.content_fingerprint import compute_content_hash
from tools.biz_logic.url_parsers import extract_company_id


def test_normalize_and_hash_stable_under_whitespace_and_case():
    h1 = compute_content_hash("AI Engineer", "cid1", "Build  models\n  train")
    h2 = compute_content_hash("ai engineer", "cid1", "buildmodelstrain")
    assert h1 == h2
    # different JD -> different hash (distinct same-title roles stay separate)
    assert h1 != compute_content_hash("AI Engineer", "cid1", "totally different jd")
    # different company -> different hash
    assert h1 != compute_content_hash("AI Engineer", "cid2", "Build models train")


def test_extract_company_id_strips_query_and_padding():
    assert extract_company_id("/gongsi/f409f37f83a6135b0nV_2d25EA~~.html?from=top-card") == "f409f37f83a6135b0nV_2d25EA"
    assert extract_company_id("") == ""
