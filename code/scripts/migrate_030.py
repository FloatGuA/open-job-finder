"""
migrate_030.py — One-shot migration for T030 schema refactor.

Run from the project root:
    python scripts/migrate_030.py [--db data/jobs.db]

Changes applied:
  - applications: drop deprecated columns, add hr_name
  - hr_conversations: rebuild with new schema
  - hr_messages: create if not exists
  - actions: drop table
  - Status values remapped to new enum (FOUND/CHATTING/INTERVIEWING/...)
"""
import argparse
import shutil
import sqlite3
import sys
from pathlib import Path

# ── Status mapping ────────────────────────────────────────────────────────────

STATUS_MAP = {
    "DISCOVERED":       "FOUND",
    "SCANNED":          "FOUND",
    "SCORED":           "SCORED",
    "APPLIED":          "APPLIED",
    "RESPONDED":        "CHATTING",
    "RESUME_REQUESTED": "CHATTING",
    "INTERVIEW":        "INTERVIEWING",
    "OFFER":            "OFFER",
    "REJECTED":         "REJECTED",
    "AD_PUSH":          "FOUND",
    "ERROR":            "FOUND",
}

# ── Stage mapping ─────────────────────────────────────────────────────────────

STAGE_MAP = {
    "general": "new",
    "new":     "new",
    "active":  "active",
    "resume_sent":  "resume_sent",
    "interview":    "interview",
    "offer":        "offer",
    "closed":       "closed",
    "rejected":     "closed",
}

# ── Reply status mapping ──────────────────────────────────────────────────────

REPLY_STATUS_MAP = {
    "approved":  "approved",
    "pending":   "pending",
    "revision":  "approved",   # user had edited → treat as approved
    "dismissed": None,
    "sent":      None,
}


def get_columns(conn: sqlite3.Connection, table: str) -> set:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _rows_as_dicts(conn: sqlite3.Connection, table: str) -> list:
    col_names = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
    return [dict(zip(col_names, r)) for r in conn.execute(f"SELECT * FROM {table}").fetchall()]


def migrate_applications(conn: sqlite3.Connection) -> dict:
    cols = get_columns(conn, "applications")
    if not cols:
        print("  [SKIP] applications table does not exist")
        return {"skipped": True}

    # Add hr_name if missing
    if "hr_name" not in cols:
        conn.execute("ALTER TABLE applications ADD COLUMN hr_name TEXT")
        print("  [ADD]  applications.hr_name")

    # Remap status values
    updated = 0
    rows = conn.execute("SELECT job_id, status FROM applications").fetchall()
    for row in rows:
        new_status = STATUS_MAP.get(row[1], row[1])
        if new_status != row[1]:
            conn.execute(
                "UPDATE applications SET status = ? WHERE job_id = ?",
                (new_status, row[0]),
            )
            updated += 1
    if updated:
        print(f"  [MAP]  {updated} application status value(s) remapped")

    # Drop deprecated columns (SQLite 3.35+ required)
    deprecated = [
        "updated_at", "responded_at", "critic_verdict",
        "resume_path", "apply_attempted", "error_msg", "decision",
    ]
    dropped = []
    for col in deprecated:
        if col in cols:
            try:
                conn.execute(f"ALTER TABLE applications DROP COLUMN {col}")
                dropped.append(col)
            except sqlite3.OperationalError as e:
                print(f"  [WARN] could not drop applications.{col}: {e}")
    if dropped:
        print(f"  [DROP] applications columns: {', '.join(dropped)}")

    return {"status_remapped": updated, "columns_dropped": dropped}


def migrate_hr_conversations(conn: sqlite3.Connection) -> dict:
    old_cols = get_columns(conn, "hr_conversations")
    if not old_cols:
        print("  [SKIP] hr_conversations table does not exist")
        return {"skipped": True}

    # Read existing rows before rebuild (ordered by PRAGMA, not arbitrary set order)
    old_data = _rows_as_dicts(conn, "hr_conversations")

    # Create new table
    conn.execute("DROP TABLE IF EXISTS hr_conversations_new")
    conn.execute(
        """
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
    )

    inserted = 0
    for row in old_data:
        stage_raw = row.get("stage") or "general"
        new_stage = STAGE_MAP.get(stage_raw, "new")

        rs_raw = row.get("reply_status")
        new_reply_status = REPLY_STATUS_MAP.get(rs_raw, rs_raw) if rs_raw else None

        # Merge reply content: prefer reply_draft over suggested_reply
        reply_draft = row.get("reply_draft") or ""
        suggested_reply = row.get("suggested_reply") or ""
        if new_reply_status in (None,):
            reply_text = None
        else:
            reply_text = reply_draft or suggested_reply or None

        last_synced = row.get("last_synced") or ""
        created_at = row.get("created_at") or last_synced or "1970-01-01T00:00:00"

        conn.execute(
            """
            INSERT OR IGNORE INTO hr_conversations_new
                (conv_id, hr_name, company, job_id, stage, boss_conv_id,
                 intent, reply_status, reply_text, last_msg_preview, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["conv_id"],
                row.get("hr_name") or "",
                row.get("company") or "",
                row.get("job_id"),
                new_stage,
                row.get("boss_conv_id") or "",
                row.get("intent"),
                new_reply_status,
                reply_text,
                row.get("last_msg_preview") or "",
                created_at,
            ),
        )
        inserted += 1

    conn.execute("DROP TABLE hr_conversations")
    conn.execute("ALTER TABLE hr_conversations_new RENAME TO hr_conversations")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_hr_conversations_stage ON hr_conversations(stage)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_hr_conversations_boss_conv_id ON hr_conversations(boss_conv_id)"
    )

    print(f"  [REBUILD] hr_conversations — {inserted} row(s) migrated")

    # conv_id hash cannot be migrated (requires hr_title which old rows don't have)
    if old_data:
        print(
            "  [WARN] conv_id hash formula changed (now includes hr_title). "
            "Existing conv_ids are preserved as-is; new conversations will use the "
            "updated sha256(hr_name|company|hr_title)[:12] formula."
        )

    return {"rows_migrated": inserted}


def create_hr_messages(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hr_messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            conv_id    TEXT    NOT NULL,
            sender     TEXT    NOT NULL,
            text       TEXT    NOT NULL,
            msg_time   TEXT,
            created_at TEXT    NOT NULL,
            UNIQUE(conv_id, sender, text, msg_time)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_hr_messages_conv ON hr_messages(conv_id)"
    )
    print("  [CREATE] hr_messages")


def drop_actions(conn: sqlite3.Connection) -> None:
    conn.execute("DROP TABLE IF EXISTS actions")
    print("  [DROP]  actions table")


def run(db_path: str) -> None:
    path = Path(db_path)
    if not path.exists():
        print(f"Database not found: {db_path}")
        sys.exit(1)

    # Backup
    bak = path.with_suffix(".db.bak")
    shutil.copy2(path, bak)
    print(f"Backup created: {bak}")

    conn = sqlite3.connect(str(path))
    conn.execute("PRAGMA journal_mode=WAL")

    try:
        with conn:
            drop_actions(conn)
            app_result = migrate_applications(conn)
            conv_result = migrate_hr_conversations(conn)
            create_hr_messages(conn)

        print("\nMigration complete.")
        print(f"  applications : {app_result}")
        print(f"  hr_conversations : {conv_result}")
    except Exception as exc:
        conn.close()
        print(f"\nMigration FAILED: {exc}")
        print(f"Restoring backup from {bak}")
        shutil.copy2(bak, path)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="T030 DB migration")
    parser.add_argument("--db", default="data/jobs.db", help="Path to jobs.db")
    args = parser.parse_args()
    run(args.db)
