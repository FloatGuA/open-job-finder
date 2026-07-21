"""Migration: rebuild an old 4-column UNIQUE(conv_id,sender,text,msg_time) hr_messages
table to the 3-column UNIQUE(conv_id,sender,text), deduping content-duplicates that the
old constraint let accumulate (Boss's msg_time is an unstable relative-display string)."""
import sqlite3

from services.tracker import ApplicationTracker


def _old_schema_db(path):
    raw = sqlite3.connect(path)
    raw.executescript(
        """
        CREATE TABLE hr_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conv_id TEXT NOT NULL, sender TEXT NOT NULL, text TEXT NOT NULL,
            msg_time TEXT, created_at TEXT NOT NULL,
            UNIQUE(conv_id, sender, text, msg_time)
        );
        INSERT INTO hr_messages (conv_id, sender, text, msg_time, created_at) VALUES
            ('c1','hr','hello','06-10 09:55','2026-06-10'),
            ('c1','hr','hello','刚刚 09:55','2026-06-11'),
            ('c1','hr','world','10:00','2026-06-10');
        """
    )
    raw.commit()
    raw.close()


def test_hr_messages_unique_migration_dedups(tmp_path):
    db = str(tmp_path / "jobs.db")
    _old_schema_db(db)

    t = ApplicationTracker(db_path=db)  # opening triggers _init_db migration
    try:
        counts = dict(t.conn.execute("SELECT text, COUNT(*) FROM hr_messages GROUP BY text").fetchall())
        assert counts == {"hello": 1, "world": 1}  # 'hello' collapsed from 2 -> 1
        sql = t.conn.execute("SELECT sql FROM sqlite_master WHERE name='hr_messages'").fetchone()[0]
        assert "text,msg_time)" not in sql.replace(" ", "")  # now 3-column UNIQUE
        # earliest id kept -> the first msg_time survives
        mt = t.conn.execute("SELECT msg_time FROM hr_messages WHERE text='hello'").fetchone()[0]
        assert mt == "06-10 09:55"
    finally:
        t.close()


def test_migration_idempotent_on_new_schema(tmp_path):
    # A DB already on the 3-column schema must not be rebuilt / must accept content dedup.
    db = str(tmp_path / "jobs.db")
    t1 = ApplicationTracker(db_path=db)
    with t1.conn:
        t1.conn.execute("INSERT INTO hr_messages (conv_id, sender, text, msg_time, created_at) "
                        "VALUES ('c1','hr','x','t1','2026-01-01')")
    t1.close()
    # reopen — migration detector must not fire (already 3-col)
    t2 = ApplicationTracker(db_path=db)
    try:
        sql = t2.conn.execute("SELECT sql FROM sqlite_master WHERE name='hr_messages'").fetchone()[0]
        assert "text,msg_time)" not in sql.replace(" ", "")
        assert t2.conn.execute("SELECT COUNT(*) FROM hr_messages").fetchone()[0] == 1
    finally:
        t2.close()
