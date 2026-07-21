"""Pre-commit guard: refuse to commit personal data from the private job database.

Why this exists: .gitignore protects by LOCATION, which works for data/ and logs/
but cannot protect PROGRESS.md -- that file must be committed, and the leak came
from writing real company names and HR names into it as examples. Location-based
rules are structurally unable to catch that, so content has to be scanned.

Two detector families:

1. Hard patterns -- things that are personal data no matter where they appear
   (Boss avatar CDN URLs, phone numbers, e-mail addresses, WeChat ids).

2. Private-database comparison -- read the real names out of jobs.db and refuse
   any commit that reproduces them. This is the strong one: it recognises
   "you copied something out of your own conversation history" without needing
   to enumerate anything in advance.

Precision matters more than recall here: a scanner that cries wolf gets bypassed
with --no-verify and then protects nothing. So short/ambiguous terms are demoted
to weak signals that only fire with corroboration (see _classify_terms).

Usage:
    python scripts/precommit_pii_scan.py            # scan staged changes
    python scripts/precommit_pii_scan.py --all      # scan the whole worktree
Exit code 1 means "found something", which is what blocks the commit.
"""
import argparse
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

# --- hard patterns: personal data regardless of context ------------------------
HARD_PATTERNS = [
    (re.compile(r"upload/avatar/[A-Za-z0-9_\-/.]+"), "Boss 头像 CDN URL（可反查到具体个人）"),
    (re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"), "手机号"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@(?!example\.|test\.|localhost)[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "邮箱地址"),
    # Chinese context only, and the value must not be a type/identifier: matching
    # `wechat_id?: string` or `WechatCard(msg:` is exactly the noise that gets a
    # hook disabled. Requires 微信/微信号 followed by a plausible account string.
    (re.compile(r"微信(?:号)?\s*[:：]\s*(?!string\b|number\b|boolean\b)"
                r"[A-Za-z][A-Za-z0-9_\-]{5,19}\b"), "微信号"),
]

# Publicly known employers. They live in jobs.db because the user applied there,
# but the name alone is common knowledge and appears legitimately in mockups and
# design docs. Only flagged when a real person's name shares the line (see
# scan_text), which is what turns it back into private information.
WELL_KNOWN_COMPANIES = {
    "字节跳动", "腾讯科技", "阿里巴巴", "百度在线", "美团点评", "京东集团",
    "小米科技", "网易有道", "华为技术", "华为云计算", "滴滴出行", "快手科技",
    "拼多多", "蚂蚁集团", "微软中国", "亚马逊", "特斯拉", "比亚迪",
}

# Generic Chinese placeholders used as test fixtures. "王女士" is the Chinese
# equivalent of "Jane Doe": a surname plus an honorific identifies nobody, and
# these appear across the test suite on purpose.
PLACEHOLDER_NAMES = {
    "王女士", "李女士", "张女士", "陈女士", "刘女士",
    "王先生", "李先生", "张先生", "陈先生", "刘先生",
}

# Files whose Chinese names are fixtures, not records. Kept deliberately small.
FIXTURE_PATH_HINTS = ("/tests/", "\\tests\\")

MIN_NAME_LEN = 3     # full names; 2-char names collide with common words
MIN_COMPANY_LEN = 4  # 2-3 char company names are ordinary vocabulary (腾讯/字节)


def load_private_terms(db_path: Path) -> dict:
    """Read real names/companies out of the private DB.

    Returns {"names": set, "companies": set}. A missing DB is not an error --
    a fresh clone has no database, and the hard patterns still apply.
    """
    empty = {"names": set(), "companies": set()}
    if not db_path.exists():
        return empty
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    except sqlite3.Error:
        return empty
    try:
        names, companies = set(), set()
        for table in ("applications", "hr_conversations"):
            for col, bucket, min_len in (("hr_name", names, MIN_NAME_LEN),
                                         ("company", companies, MIN_COMPANY_LEN)):
                try:
                    rows = conn.execute(
                        f"SELECT DISTINCT {col} FROM {table} "
                        f"WHERE {col} IS NOT NULL AND {col} != ''"
                    ).fetchall()
                except sqlite3.Error:
                    continue
                for (value,) in rows:
                    value = (value or "").strip()
                    if len(value) >= min_len and value not in PLACEHOLDER_NAMES:
                        bucket.add(value)
        return {"names": names, "companies": companies}
    finally:
        conn.close()


def scan_text(path: str, lines, terms: dict) -> list:
    """Scan (line_no, text) pairs for personal data. Returns list of findings."""
    findings = []
    is_fixture = any(h in path.replace("\\", "/") for h in FIXTURE_PATH_HINTS)
    names, companies = terms["names"], terms["companies"]

    for line_no, text in lines:
        for pattern, label in HARD_PATTERNS:
            m = pattern.search(text)
            if m:
                findings.append({
                    "file": path, "line": line_no, "kind": label,
                    "matched": m.group(0)[:60], "severity": "high",
                })

        # DB comparison only makes sense for lines containing CJK; skipping the
        # rest keeps the scan fast on a mostly-ASCII codebase.
        if not re.search(r"[一-鿿]", text):
            continue

        hit_name = next((n for n in names if n in text), None)
        hit_company = next((c for c in companies if c in text), None)

        if hit_company:
            # A household-name employer on its own is public knowledge (mockups and
            # design docs legitimately say 字节跳动). It only becomes private data
            # when tied to a specific person on the same line.
            well_known = hit_company in WELL_KNOWN_COMPANIES
            if not well_known or hit_name:
                findings.append({
                    "file": path, "line": line_no, "kind": "私有库中的真实公司名",
                    "matched": hit_company,
                    "severity": "warn" if is_fixture else "high",
                })

        if hit_name:
            # A fixture reproducing a name that also exists in the DB is far more
            # likely to be coincidence than a leak; blocking it would train people
            # to reach for --no-verify, after which the hook protects nothing.
            findings.append({
                "file": path, "line": line_no, "kind": "私有库中的真实 HR 姓名",
                "matched": hit_name, "severity": "warn" if is_fixture else "high",
            })
    return findings


def _staged_additions(repo_root: Path) -> dict:
    """{path: [(line_no, text)]} for ADDED lines in the staged diff.

    Only additions matter: deletions and context are already committed, and
    flagging them would make every later commit unpassable.
    """
    out = subprocess.run(
        ["git", "diff", "--cached", "--unified=0", "--no-color", "--diff-filter=ACMR"],
        cwd=str(repo_root), capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    ).stdout

    files, current, line_no = {}, None, 0
    for raw in out.split("\n"):
        if raw.startswith("+++ b/"):
            current = raw[6:].strip()
            files.setdefault(current, [])
        elif raw.startswith("@@"):
            m = re.search(r"\+(\d+)", raw)
            line_no = int(m.group(1)) if m else 0
        elif raw.startswith("+") and not raw.startswith("+++") and current:
            files[current].append((line_no, raw[1:]))
            line_no += 1
    return files


def _worktree_files(repo_root: Path) -> dict:
    files = {}
    out = subprocess.run(["git", "ls-files"], cwd=str(repo_root),
                         capture_output=True, text=True,
                         encoding="utf-8", errors="replace").stdout
    for rel in out.split("\n"):
        rel = rel.strip()
        if not rel:
            continue
        p = repo_root / rel
        try:
            if p.stat().st_size > 2_000_000:
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        files[rel] = list(enumerate(text.split("\n"), start=1))
    return files


def run(repo_root: Path, db_path: Path, scan_all: bool = False) -> list:
    terms = load_private_terms(db_path)
    files = _worktree_files(repo_root) if scan_all else _staged_additions(repo_root)
    findings = []
    for path, lines in files.items():
        # Never scan the scanner: its own placeholder list would self-trigger.
        if path.endswith("precommit_pii_scan.py"):
            continue
        findings.extend(scan_text(path, lines, terms))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description="扫描个人隐私数据，阻止误提交")
    ap.add_argument("--all", action="store_true", help="扫描整个工作树而非暂存区")
    ap.add_argument("--repo", default=None, help="仓库根目录")
    args = ap.parse_args()

    repo_root = Path(args.repo) if args.repo else Path(__file__).resolve().parents[2]
    db_path = repo_root / "code" / "data" / "jobs.db"

    findings = run(repo_root, db_path, scan_all=args.all)
    blocking = [f for f in findings if f["severity"] == "high"]
    warnings = [f for f in findings if f["severity"] == "warn"]

    if warnings:
        print("提示（未阻止，测试夹具中的姓名与私有库重名）：", file=sys.stderr)
        for f in warnings[:5]:
            print(f"  {f['file']}:{f['line']}  {f['kind']}", file=sys.stderr)

    if not blocking:
        return 0

    print("", file=sys.stderr)
    print("=" * 68, file=sys.stderr)
    print("提交被阻止：检测到个人隐私数据", file=sys.stderr)
    print("=" * 68, file=sys.stderr)
    seen = set()
    for f in blocking:
        key = (f["file"], f["kind"], f["matched"])
        if key in seen:
            continue
        seen.add(key)
        # The matched value is itself personal data; show only its length.
        print(f"  {f['file']}:{f['line']}", file=sys.stderr)
        print(f"      {f['kind']}（{len(f['matched'])} 字符，此处不回显）", file=sys.stderr)
    print("", file=sys.stderr)
    print("这个仓库是公开的。写文档举例时不要从 jobs.db 抄真实公司/HR/薪资，", file=sys.stderr)
    print("改用泛化描述（如「某教育机构」「大厂 OD 岗」）。", file=sys.stderr)
    print("确认是误报可用 git commit --no-verify 跳过。", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
