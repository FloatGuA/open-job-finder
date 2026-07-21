"""
完整重建 applications 表到 tracker.py 当前 schema（url 可空、去掉所有旧字段）。
migrate_030.py 用 ALTER DROP COLUMN 删不掉 url 的 NOT NULL 约束，故单独重建。
只动 applications，不碰 hr_conversations / hr_messages。自带备份 + 失败回滚。

用法（在 code/ 下）：python scripts/migrate_app_rebuild.py
"""
import os
import shutil
import sqlite3
import sys
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
DB = CODE / "data" / "jobs.db"

# 旧状态值 → 新枚举（与 migrate_030.STATUS_MAP 一致）
STATUS_MAP = {
    "DISCOVERED": "FOUND", "SCANNED": "FOUND", "SCORED": "SCORED", "APPLIED": "APPLIED",
    "RESPONDED": "CHATTING", "RESUME_REQUESTED": "CHATTING", "INTERVIEW": "INTERVIEWING",
    "OFFER": "OFFER", "REJECTED": "REJECTED", "AD_PUSH": "FOUND", "ERROR": "FOUND",
}

# 与 tracker.py _create_tables 的 applications 完全一致
_NEW_SCHEMA = """
CREATE TABLE applications_new (
    job_id      TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    company     TEXT NOT NULL,
    hr_name     TEXT,
    url         TEXT,
    status      TEXT NOT NULL DEFAULT 'FOUND',
    city        TEXT,
    salary      TEXT,
    score       INTEGER,
    applied_at  TEXT,
    created_at  TEXT NOT NULL
)
"""


def main() -> int:
    if not DB.exists():
        print("DB not found:", DB)
        return 1
    bak = str(DB) + ".bak_appmig"
    shutil.copy2(DB, bak)
    print("backup created:", os.path.basename(bak))

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    try:
        old_cols = [r[1] for r in conn.execute("PRAGMA table_info(applications)").fetchall()]
        print("old columns:", old_cols)
        rows = [dict(r) for r in conn.execute("SELECT * FROM applications").fetchall()]
        print("rows to migrate:", len(rows))

        remapped = 0
        with conn:
            conn.execute("DROP TABLE IF EXISTS applications_new")
            conn.execute(_NEW_SCHEMA)
            for r in rows:
                old_status = r.get("status") or "FOUND"
                new_status = STATUS_MAP.get(old_status, old_status)
                if new_status != old_status:
                    remapped += 1
                conn.execute(
                    """INSERT OR IGNORE INTO applications_new
                       (job_id,title,company,hr_name,url,status,city,salary,score,applied_at,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        r["job_id"], r.get("title") or "", r.get("company") or "",
                        r.get("hr_name"), r.get("url"), new_status,
                        r.get("city"), r.get("salary"), r.get("score"),
                        r.get("applied_at"),
                        r.get("created_at") or r.get("applied_at") or "1970-01-01T00:00:00",
                    ),
                )
            conn.execute("DROP TABLE applications")
            conn.execute("ALTER TABLE applications_new RENAME TO applications")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status)")
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass

        n = conn.execute("SELECT count(*) FROM applications").fetchone()[0]
        print(f"done. status remapped: {remapped}, rows now in applications: {n}")
        print("new schema:")
        print(conn.execute("SELECT sql FROM sqlite_master WHERE name='applications'").fetchone()[0])
        return 0
    except Exception as exc:
        conn.close()
        print("MIGRATION FAILED:", exc, "— restoring backup")
        shutil.copy2(bak, DB)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
