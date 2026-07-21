"""W1 content-fingerprint dedup (rotated encryptJobId).

Same posting re-encountered under a different job_id must be detected via the content
hash; genuinely different same-title roles (different JD) must NOT; REJECTED priors are
excluded (user wants rejected jobs re-appliable).
"""
from datetime import datetime, timezone

from services.tracker import ApplicationTracker
from tools.biz_logic.content_fingerprint import compute_content_hash, normalize_text
from tools.biz_logic.url_parsers import extract_company_id
from tools.db.w1.check_content_duplicate import CheckContentDuplicate
from tools.db.w1.upsert_application import UpsertApplication


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


def _apply(tracker, job_id, title, cid, jd, status):
    UpsertApplication(db=tracker).execute(
        job_id=job_id, title=title, company="C", status=status,
        applied_at=datetime.now(timezone.utc).isoformat(),
        content_hash=compute_content_hash(title, cid, jd),
    )


def test_rotated_id_same_content_is_duplicate(tmp_path):
    tracker = ApplicationTracker(str(tmp_path / "jobs.db"))
    _apply(tracker, "encid_OLD", "AI工程师", "huawei", "做大模型训练", "APPLIED")

    tool = CheckContentDuplicate(db=tracker)
    # same posting, rotated job_id -> same content -> duplicate
    r = tool.execute(title="AI工程师", company_id="huawei", jd_text="做大模型训练")
    assert r.data["is_duplicate"] is True
    assert r.data["prior_status"] == "APPLIED"

    # same title+company but a genuinely different role (different JD) -> NOT duplicate
    r2 = tool.execute(title="AI工程师", company_id="huawei", jd_text="做推荐系统")
    assert r2.data["is_duplicate"] is False


def test_rejected_prior_is_not_a_duplicate(tmp_path):
    """REJECTED priors are excluded so rejected/timeout jobs stay re-appliable."""
    tracker = ApplicationTracker(str(tmp_path / "jobs.db"))
    _apply(tracker, "encid_OLD", "后端开发", "cid", "写后端", "REJECTED")
    r = CheckContentDuplicate(db=tracker).execute(title="后端开发", company_id="cid", jd_text="写后端")
    assert r.data["is_duplicate"] is False
