"""Pre-commit PII guard: must catch real leaks without crying wolf.

A scanner with false positives gets bypassed with --no-verify and then protects
nothing, so the precision cases matter as much as the detection ones.

Context: .gitignore protects by location and therefore cannot protect PROGRESS.md,
which must be committed. Both historical leaks in this repo came through content
(real company/HR names copied into docs) or through a location the blacklist had
not enumerated (logs/task_*/).
"""
import sqlite3

import pytest

from scripts import precommit_pii_scan as scan


def _lines(*texts):
    return list(enumerate(texts, start=1))


def _terms(names=(), companies=()):
    return {"names": set(names), "companies": set(companies)}


# ---- hard patterns ------------------------------------------------------------


def test_avatar_url_is_blocked():
    """The hardest PII in the 2026-07 leak: 28 avatar URLs that resolve to
    identifiable individuals."""
    found = scan.scan_text("PROGRESS.md", _lines(
        'img src="https://img.bosszhipin.com/beijin/upload/avatar/20240101/abc123.png"'
    ), _terms())
    assert len(found) == 1
    assert found[0]["severity"] == "high"
    assert "头像" in found[0]["kind"]


def test_phone_and_email_are_blocked():
    found = scan.scan_text("docs/x.md", _lines(
        "联系方式 13812345678",
        "简历发到 zhaopin@somecorp.com",
    ), _terms())
    kinds = {f["kind"] for f in found}
    assert "手机号" in kinds
    assert "邮箱地址" in kinds


def test_example_domains_are_not_flagged():
    """Docs legitimately contain example.com / test.com addresses."""
    found = scan.scan_text("README.md", _lines(
        "配置 notify@example.com 即可",
        "user@test.localhost",
    ), _terms())
    assert found == []


def test_version_strings_are_not_mistaken_for_phone_numbers():
    found = scan.scan_text("code/x.py", _lines(
        "BUILD = 13812345678901234",   # longer than a phone number
        "count = 1381234567",          # shorter
    ), _terms())
    assert found == []


# ---- private-database comparison ----------------------------------------------


def test_real_company_from_db_is_blocked():
    found = scan.scan_text("PROGRESS.md", _lines(
        "端到端验证通过：某某科技有限公司 的会话已同步"
    ), _terms(companies={"某某科技有限公司"}))
    assert len(found) == 1
    assert found[0]["severity"] == "high"
    assert "公司名" in found[0]["kind"]


def test_real_hr_name_from_db_is_blocked():
    found = scan.scan_text("PROGRESS.md", _lines(
        "fetch_jd 抓到 hr_name=张三丰，落库正确"
    ), _terms(names={"张三丰"}))
    assert len(found) == 1
    assert found[0]["severity"] == "high"


def test_ascii_only_lines_skip_db_comparison():
    """Fast path: most of the codebase is ASCII and cannot contain these names."""
    found = scan.scan_text("code/x.py", _lines(
        "def foo(): return 'bar'",
    ), _terms(names={"张三丰"}, companies={"某某科技有限公司"}))
    assert found == []


def test_fixture_files_downgrade_name_matches_to_warnings():
    """A test fixture reusing a name that happens to exist in the DB is far more
    likely to be coincidence than a leak; blocking it would train people to
    --no-verify."""
    found = scan.scan_text("code/tests/test_foo.py", _lines(
        'conv = _conv(hr_name="张三丰")'
    ), _terms(names={"张三丰"}))
    assert len(found) == 1
    assert found[0]["severity"] == "warn"


def test_fixture_downgrade_applies_to_db_terms_but_never_to_hard_patterns():
    """In a fixture file, a name/company matching the DB is probably coincidence,
    so it warns. But an avatar URL is personal data no matter where it sits --
    there is no innocent reason for one to appear in a test."""
    found = scan.scan_text("code/tests/test_foo.py", _lines(
        'URL = "https://img.bosszhipin.com/beijin/upload/avatar/x/y.png"',
        'company = "某某科技有限公司"',
    ), _terms(companies={"某某科技有限公司"}))
    by_kind = {f["kind"]: f["severity"] for f in found}
    assert by_kind["Boss 头像 CDN URL（可反查到具体个人）"] == "high"
    assert by_kind["私有库中的真实公司名"] == "warn"


# ---- precision: well-known employers ------------------------------------------


def test_well_known_company_alone_is_not_flagged():
    """字节跳动 is in jobs.db because the user applied there, but the name alone
    is common knowledge and appears legitimately in mockups and design docs."""
    found = scan.scan_text("design/console-mockup.html", _lines(
        '<div class="company">字节跳动</div>'
    ), _terms(companies={"字节跳动"}))
    assert found == []


def test_well_known_company_with_a_real_person_is_flagged():
    """The pairing is what makes it private: this is a record of a specific
    person at a specific employer."""
    found = scan.scan_text("PROGRESS.md", _lines(
        "验证：字节跳动 的 HR 张三丰 已回复"
    ), _terms(names={"张三丰"}, companies={"字节跳动"}))
    kinds = {f["kind"] for f in found}
    assert "私有库中的真实公司名" in kinds
    assert "私有库中的真实 HR 姓名" in kinds


def test_wechat_field_declarations_are_not_mistaken_for_ids():
    """`wechat_id?: string` and `WechatCard(msg:` are code, not contact details.
    This noise is exactly what gets a hook disabled."""
    found = scan.scan_text("code/api.ts", _lines(
        "  wechat_id?: string",
        "  wechat_id: string",
        "function WechatCard(msg: ConversationMessage) {",
        '    "wechat_id": wechat_id,',
    ), _terms())
    assert found == []


def test_real_wechat_id_in_chinese_context_is_flagged():
    found = scan.scan_text("PROGRESS.md", _lines(
        "HR 说他的微信号：zhangsan_hr2024"
    ), _terms())
    assert len(found) == 1
    assert found[0]["kind"] == "微信号"


# ---- term loading: precision guards -------------------------------------------


def _make_db(tmp_path, rows_app=(), rows_conv=()):
    db = tmp_path / "jobs.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE applications (hr_name TEXT, company TEXT)")
    conn.execute("CREATE TABLE hr_conversations (hr_name TEXT, company TEXT)")
    conn.executemany("INSERT INTO applications VALUES (?,?)", rows_app)
    conn.executemany("INSERT INTO hr_conversations VALUES (?,?)", rows_conv)
    conn.commit()
    conn.close()
    return db


def test_short_terms_are_excluded_to_avoid_false_positives(tmp_path):
    """2-char names and 2-3 char company names are ordinary vocabulary. Loading
    them would flag normal technical prose and get the hook disabled."""
    db = _make_db(tmp_path, rows_app=[("王五", "腾讯"), ("黄国强", "某某科技公司")])
    terms = scan.load_private_terms(db)
    assert "王五" not in terms["names"]        # 2 chars -> excluded
    assert "腾讯" not in terms["companies"]     # 2 chars -> excluded
    assert "黄国强" in terms["names"]
    assert "某某科技公司" in terms["companies"]


def test_generic_placeholders_are_excluded(tmp_path):
    """王女士 is the Chinese Jane Doe and is used across the test suite."""
    db = _make_db(tmp_path, rows_app=[("王女士", "某某科技公司")])
    terms = scan.load_private_terms(db)
    assert "王女士" not in terms["names"]


def test_missing_database_is_not_an_error(tmp_path):
    """A fresh clone has no jobs.db; hard patterns must still work."""
    terms = scan.load_private_terms(tmp_path / "nope.db")
    assert terms == {"names": set(), "companies": set()}


def test_database_is_opened_read_only(tmp_path):
    """The hook must never be able to modify the user's data."""
    db = _make_db(tmp_path, rows_app=[("黄国强", "某某科技公司")])
    scan.load_private_terms(db)
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0] == 1
    conn.close()


# ---- diff parsing --------------------------------------------------------------


def test_only_added_lines_are_scanned(monkeypatch, tmp_path):
    """Deletions and context are already committed; flagging them would make
    every subsequent commit impossible."""
    diff = (
        "diff --git a/PROGRESS.md b/PROGRESS.md\n"
        "--- a/PROGRESS.md\n"
        "+++ b/PROGRESS.md\n"
        "@@ -10,2 +10,2 @@\n"
        "-旧行包含 张三丰\n"
        "+新行是干净的\n"
    )

    class _Proc:
        stdout = diff

    monkeypatch.setattr(scan.subprocess, "run", lambda *a, **k: _Proc())
    files = scan._staged_additions(tmp_path)
    assert files["PROGRESS.md"] == [(10, "新行是干净的")]
