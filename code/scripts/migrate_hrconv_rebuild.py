"""
重建 hr_conversations 表到 tracker.py 当前 schema。
旧库的 hr_conversations 停留在 T030 前 schema（有 messages/last_msg_text/last_synced/
status/suggested_reply/needs_reply/reply_draft 等旧字段，缺 reply_text/created_at），
跑 W2 会踩"列不存在/写失败"坑。本脚本重建表并迁移数据（与 migrate_030 的
migrate_hr_conversations 逻辑一致）。只动 hr_conversations，hr_messages 已是新 schema。
自带备份 + 失败回滚。用法（code/ 下）：python scripts/migrate_hrconv_rebuild.py
"""
import os
import shutil
import sqlite3
import sys
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent
DB = CODE / "data" / "jobs.db"

STAGE_MAP = {
    "general": "new", "new": "new", "active": "active", "resume_sent": "resume_sent",
    "interview": "interview", "offer": "offer", "closed": "closed", "rejected": "closed",
}
REPLY_STATUS_MAP = {
    "approved": "approved", "pending": "pending", "revision": "approved",
    "dismissed": None, "sent": None,
}

_NEW_SCHEMA = """
CREATE TABLE hr_conversations_new (
    conv_id          TEXT PRIMARY KEY,
    hr_name          TEXT NOT NULL,
    company          TEXT NOT NULL,
    job_id           TEXT,
    stage            TEXT NOT NULL DEFAULT 'new',
    boss_conv_id     TEXT DEFAULT '',
    intent           TEXT,
    reply_status     TEXT,
    reply_text       TEXT,
    last_msg_preview TEXT DEFAULT '',
    created_at       TEXT NOT NULL
)
"""


def main() -> int:
    if not DB.exists():
        print("DB not found:", DB)
        return 1
    bak = str(DB) + ".bak_hrconv"
    shutil.copy2(DB, bak)
    print("backup created:", os.path.basename(bak))

    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    try:
        rows = [dict(r) for r in conn.execute("SELECT * FROM hr_conversations").fetchall()]
        print("rows to migrate:", len(rows))
        with conn:
            conn.execute("DROP TABLE IF EXISTS hr_conversations_new")
            conn.execute(_NEW_SCHEMA)
            for r in rows:
                stage = STAGE_MAP.get(r.get("stage") or "general", "new")
                rs_raw = r.get("reply_status")
                new_rs = REPLY_STATUS_MAP.get(rs_raw, rs_raw) if rs_raw else None
                reply_text = None if new_rs is None else (r.get("reply_draft") or r.get("suggested_reply") or None)
                created_at = r.get("created_at") or r.get("last_synced") or "1970-01-01T00:00:00"
                conn.execute(
                    """INSERT OR IGNORE INTO hr_conversations_new
                       (conv_id,hr_name,company,job_id,stage,boss_conv_id,intent,reply_status,reply_text,last_msg_preview,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        r["conv_id"], r.get("hr_name") or "", r.get("company") or "", r.get("job_id"),
                        stage, r.get("boss_conv_id") or "", r.get("intent"), new_rs, reply_text,
                        r.get("last_msg_preview") or "", created_at,
                    ),
                )
            conn.execute("DROP TABLE hr_conversations")
            conn.execute("ALTER TABLE hr_conversations_new RENAME TO hr_conversations")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hr_conversations_stage ON hr_conversations(stage)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_hr_conversations_boss_conv_id ON hr_conversations(boss_conv_id)")
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        n = conn.execute("SELECT count(*) FROM hr_conversations").fetchone()[0]
        print(f"done. rows now in hr_conversations: {n}")
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
