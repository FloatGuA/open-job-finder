"""
Migration: rebuild hr_messages with UNIQUE(conv_id, sender, text) instead of
UNIQUE(conv_id, sender, text, msg_time).

Run once against an existing jobs.db:
    python scripts/migrate_hr_messages_dedup.py [path/to/jobs.db]
"""
import sqlite3
import sys
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "jobs.db"


def migrate(db_path: Path) -> None:
    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript("""
            BEGIN;

            CREATE TABLE IF NOT EXISTS hr_messages_new (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                conv_id    TEXT NOT NULL,
                sender     TEXT NOT NULL,
                text       TEXT NOT NULL,
                msg_time   TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(conv_id, sender, text)
            );

            INSERT OR IGNORE INTO hr_messages_new
                (id, conv_id, sender, text, msg_time, created_at)
            SELECT id, conv_id, sender, text, msg_time, created_at
            FROM hr_messages;

            DROP TABLE hr_messages;
            ALTER TABLE hr_messages_new RENAME TO hr_messages;

            CREATE INDEX IF NOT EXISTS idx_hr_messages_conv
                ON hr_messages(conv_id);

            COMMIT;
        """)
        print(f"Migration complete: {db_path}")
    except Exception as exc:
        conn.rollback()
        print(f"Migration failed: {exc}")
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DB_PATH
    if not path.exists():
        print(f"DB not found: {path}")
        sys.exit(1)
    migrate(path)
