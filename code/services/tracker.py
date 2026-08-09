import json
import sqlite3
import os
import threading
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Union

from schemas import AppStatus, ApplicationRecord, HRConversation
from services.logger import get_orchestrator_logger


# Persisted application lifecycle. ADVISORY ONLY: this drives a single warning log in
# upsert()/update_status(); the real transitions run through raw SQL in
# sync_application_status / purge and BYPASS this table. It is kept aligned with the
# actual transitions so the warning does not fire on legitimate moves.
#   FOUND  → APPLIED                              (投递成功；FOUND 仅内存入口态)
#   APPLIED→ INTERVIEWING / OFFER / REJECTED      (sync: 会话 stage / intent=rejection)
#   INTERVIEWING → OFFER / REJECTED
#   OFFER  → REJECTED                             (offer 后被拒/取消，罕见)
#   REJECTED → APPLIED                            (复活：会话再活跃 / 重投)
VALID_TRANSITIONS = {
    AppStatus.FOUND.value:        {AppStatus.APPLIED.value},
    AppStatus.APPLIED.value:      {AppStatus.INTERVIEWING.value, AppStatus.OFFER.value, AppStatus.REJECTED.value},
    AppStatus.INTERVIEWING.value: {AppStatus.OFFER.value, AppStatus.REJECTED.value},
    AppStatus.OFFER.value:        {AppStatus.REJECTED.value},
    AppStatus.REJECTED.value:     {AppStatus.APPLIED.value},
}

# Reply statuses that reflect a user/system DECISION and must never be clobbered
# when W2 re-analyzes a conversation: 'approved' (user OK'd it), 'revision' (user
# edited it), 'dismissed' (user declined), 'sent' (already delivered to the HR).
# Only null / 'pending' are freely refreshed. Both reply_text AND reply_status are
# protected -- an earlier version omitted 'approved' and left reply_text open, so
# re-analysis could downgrade approved→pending and overwrite a user-revised draft.
PROTECTED_REPLY_STATUSES = frozenset({"approved", "sent", "dismissed", "revision"})

# What a caller may ASK for. The protected ones above are reached through their own
# explicit transitions (approve / dismiss / mark_reply_sent), never via re-analysis.
ALLOWED_REPLY_STATUSES = frozenset({None, "pending", "sent"})


class ApplicationTracker:
    def __init__(self, db_path: Optional[str] = None):
        # 绝对路径默认，避免 cwd 漂移连到不同的 jobs.db（项目根曾有空库）
        if db_path is None:
            db_path = str(Path(__file__).resolve().parent.parent / "data" / "jobs.db")
        db_dir = os.path.dirname(db_path) or "data"
        os.makedirs(db_dir, exist_ok=True)

        self.logger = get_orchestrator_logger()
        self._db_path = db_path
        # One SQLite connection PER THREAD. The dashboard runs W2 in a worker
        # thread while API handlers (approve/cancel/...) run on the event-loop
        # thread; a single shared connection used from both concurrently locks or
        # corrupts (transactions interleave -> "database is locked" / nested
        # transaction). Thread-local connections + WAL + busy_timeout let SQLite
        # serialize writes safely: a write issued during a W2 run waits for the
        # lock (up to busy_timeout) instead of failing immediately.
        self._local = threading.local()
        self._create_tables()

    @property
    def conn(self) -> sqlite3.Connection:
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self._db_path, check_same_thread=False, timeout=30)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA journal_mode=WAL")
            c.execute("PRAGMA busy_timeout=30000")
            self._local.conn = c
        return c

    def _create_tables(self) -> None:
        with self.conn:
            self.conn.execute("DROP TABLE IF EXISTS actions")

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
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
                    content_hash TEXT,
                    created_at  TEXT NOT NULL
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status)"
            )
            # Migration: content_hash for content-fingerprint dedup (rotated encryptJobId).
            # CREATE TABLE IF NOT EXISTS won't add a column to a pre-existing table, so
            # ALTER when missing. Existing rows stay NULL (no backfill — would need re-reading
            # every JD); the fingerprint dedup applies to jobs processed from here on.
            existing_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(applications)")}
            if "content_hash" not in existing_cols:
                self.conn.execute("ALTER TABLE applications ADD COLUMN content_hash TEXT")
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_applications_content_hash ON applications(content_hash)"
            )
            # Migration: retire the removed AppStatus values on legacy rows so stats /
            # the Jobs filter don't surface dead buckets. CHATTING ("was in conversation")
            # is a genuine post-apply state -> collapses to APPLIED. FOUND / SCORED are
            # pre-apply states that must NEVER persist in this table (FOUND is the in-memory
            # Job/ApplicationRecord default; SCORED was a legacy pre-apply bucket) -> deleted.
            # Enforcing it here (not just at write sites) makes the invariant self-healing:
            # the vestigial `DEFAULT 'FOUND'` column default can no longer leave stale rows.
            # Idempotent (no-ops once no such rows remain).
            self.conn.execute("UPDATE applications SET status = 'APPLIED' WHERE status = 'CHATTING'")
            self.conn.execute("DELETE FROM applications WHERE status IN ('SCORED', 'FOUND')")

            # scored_jobs: eval-collection table. Every real W1 scoring (applied AND
            # skipped) is appended here so a re-scorable golden accrues for score-quality
            # eval (stage 2). Deliberately NOT part of applications -- that table means
            # "jobs we applied to" and many queries depend on it; the skipped side would
            # break it. JD text (PII) stays in the already-gitignored jobs.db rather than
            # bloating run logs. Rolling-capped by record_scored_job.
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scored_jobs (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id          TEXT,
                    title           TEXT,
                    company         TEXT,
                    jd_text         TEXT,
                    score           INTEGER,
                    dimensions      TEXT,
                    reason          TEXT,
                    provider_used   TEXT,
                    threshold       INTEGER,
                    above_threshold INTEGER,
                    created_at      TEXT NOT NULL
                )
                """
            )

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS hr_conversations (
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
                    hr_title         TEXT DEFAULT '',
                    wechat_dismissed INTEGER DEFAULT 0,
                    last_msg_ts      INTEGER DEFAULT 0,
                    last_analyzed_ts INTEGER DEFAULT 0,
                    locate_fail_count INTEGER DEFAULT 0,
                    resume_status    TEXT,
                    created_at       TEXT NOT NULL
                )
                """
            )
            # Migration: hr_title (HR's own job title, e.g. "人力资源岗"). Captured by
            # extract_conversation_list but historically dropped at upsert (no column).
            # ALTER when missing; existing rows stay '' until re-scanned.
            hr_conv_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(hr_conversations)")}
            if "hr_title" not in hr_conv_cols:
                self.conn.execute("ALTER TABLE hr_conversations ADD COLUMN hr_title TEXT DEFAULT ''")
            # Migration: wechat_dismissed — user clicked "已添加/点掉" on the go-add-WeChat
            # reminder; persisted so the reminder (Chat banner / Dashboard card / filter)
            # stays dismissed across reloads.
            if "wechat_dismissed" not in hr_conv_cols:
                self.conn.execute("ALTER TABLE hr_conversations ADD COLUMN wechat_dismissed INTEGER DEFAULT 0")
            # Migration: last_msg_ts — millisecond timestamp of the conversation's
            # last message (Boss getGeekFriendList.lastTS). filter_conversations
            # diffs it for dirty detection; existing rows stay 0 until re-scanned.
            if "last_msg_ts" not in hr_conv_cols:
                self.conn.execute("ALTER TABLE hr_conversations ADD COLUMN last_msg_ts INTEGER DEFAULT 0")
            # Migration: locate_fail_count — consecutive W3 search-locate misses. After 3
            # the reply is auto-dismissed: the conversation is gone from Boss (e.g. the
            # user rejected it manually), so W3 stops retrying it forever.
            if "locate_fail_count" not in hr_conv_cols:
                self.conn.execute("ALTER TABLE hr_conversations ADD COLUMN locate_fail_count INTEGER DEFAULT 0")
            # Migration: last_analyzed_ts — the last message ts we SUCCESSFULLY analyzed
            # up to. filter_conversations' dirty check now compares conv_ts against THIS
            # (not the "last seen" last_msg_ts), so a read that succeeded but whose analyze
            # failed leaves this watermark behind and is retried next run (decouples read
            # from analyze). BACKFILL: existing already-analyzed rows (non-empty intent)
            # get last_analyzed_ts = last_msg_ts, otherwise every scanned row would look
            # unanalyzed and re-fire once on the next W2. Empty-intent rows stay 0 (they
            # genuinely need (re)analysis).
            if "last_analyzed_ts" not in hr_conv_cols:
                self.conn.execute("ALTER TABLE hr_conversations ADD COLUMN last_analyzed_ts INTEGER DEFAULT 0")
                self.conn.execute(
                    "UPDATE hr_conversations SET last_analyzed_ts = last_msg_ts "
                    "WHERE intent IS NOT NULL AND intent != ''"
                )
            # Migration: resume_status — the user's manual "queue a resume for this
            # conversation" intent (NULL | 'queued'). Mirrors reply_status for text
            # replies: 'queued' means the user staged a resume send (DB-only, browser
            # untouched, so it is fully cancellable) and W3 will deliver it on its next
            # run, then clear this back to NULL and advance stage=resume_sent. Existing
            # rows stay NULL. "Already sent" stays expressed by stage=resume_sent +
            # detect_resume_request.already_sent (system bubble), NOT duplicated here.
            if "resume_status" not in hr_conv_cols:
                self.conn.execute("ALTER TABLE hr_conversations ADD COLUMN resume_status TEXT")
            # Migration (v2.18): matched_resume / matched_resume_reason — W2 在检测到 HR
            # 索要简历时，按岗位从用户已存的几份简历里**选出该发哪一份**并记下来（只选
            # 不写：Agent 不生成简历内容）。默认行为仍是发 Boss 站内简历，这两列先服务
            # 于"给用户看建议 + 事后可追溯选得准不准"；开了 w2.auto_send_adapted_resume
            # 才真按它发本地 PDF。reason 存人类可读的选中理由，便于判断路由是否合理。
            if "matched_resume" not in hr_conv_cols:
                self.conn.execute("ALTER TABLE hr_conversations ADD COLUMN matched_resume TEXT DEFAULT ''")
            if "matched_resume_reason" not in hr_conv_cols:
                self.conn.execute("ALTER TABLE hr_conversations ADD COLUMN matched_resume_reason TEXT DEFAULT ''")
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_hr_conversations_stage ON hr_conversations(stage)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_hr_conversations_boss_conv_id ON hr_conversations(boss_conv_id)"
            )

            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS hr_messages (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    conv_id    TEXT    NOT NULL,
                    sender     TEXT    NOT NULL,
                    text       TEXT    NOT NULL,
                    msg_time   TEXT,
                    created_at TEXT    NOT NULL,
                    UNIQUE(conv_id, sender, text)
                )
                """
            )
            # Migration: hr_messages UNIQUE drifted. Older DBs were created with a
            # 4-column UNIQUE(conv_id, sender, text, msg_time). Boss stores msg_time as
            # an unstable relative-display string ("刚刚 09:55" vs "06-10 09:55" for the
            # same message re-scanned later), so that constraint let the same message
            # accumulate as duplicates (~380 rows / 10% on the live DB). The code now
            # dedups by content with a 3-column UNIQUE(conv_id, sender, text); rebuild
            # old tables to match, collapsing duplicates (INSERT OR IGNORE keeps the
            # earliest id). CREATE TABLE IF NOT EXISTS above is a no-op on such a DB.
            hm_row = self.conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='hr_messages'"
            ).fetchone()
            if hm_row and "text,msg_time)" in hm_row[0].replace(" ", "").replace("\n", ""):
                self.conn.execute(
                    """
                    CREATE TABLE hr_messages_new (
                        id         INTEGER PRIMARY KEY AUTOINCREMENT,
                        conv_id    TEXT    NOT NULL,
                        sender     TEXT    NOT NULL,
                        text       TEXT    NOT NULL,
                        msg_time   TEXT,
                        created_at TEXT    NOT NULL,
                        UNIQUE(conv_id, sender, text)
                    )
                    """
                )
                self.conn.execute(
                    """
                    INSERT OR IGNORE INTO hr_messages_new
                        (id, conv_id, sender, text, msg_time, created_at)
                    SELECT id, conv_id, sender, text, msg_time, created_at
                    FROM hr_messages ORDER BY id
                    """
                )
                self.conn.execute("DROP TABLE hr_messages")
                self.conn.execute("ALTER TABLE hr_messages_new RENAME TO hr_messages")
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_hr_messages_conv ON hr_messages(conv_id)"
            )

            # Migration: re-key conversations onto the hard-association identity.
            # derive_conv_id now returns job_id when present (else the legacy
            # sha256(hr_name|company)). Existing rows were keyed on the sha256 soft
            # key; move any row that has a job_id to conv_id = job_id and cascade the
            # foreign reference in hr_messages, so a W1 application and its W2
            # conversation finally share one identity. Idempotent: after the first
            # run every job_id-bearing row already has conv_id == job_id, so the
            # SELECT returns nothing. Skips a re-key that would collide with an
            # existing row (leave the stale duplicate; next scan supersedes it).
            rekey_rows = self.conn.execute(
                "SELECT conv_id, job_id FROM hr_conversations "
                "WHERE job_id IS NOT NULL AND job_id != '' AND conv_id != job_id"
            ).fetchall()
            if rekey_rows:
                existing = {
                    r[0] for r in self.conn.execute("SELECT conv_id FROM hr_conversations")
                }
                for old_conv_id, job_id in rekey_rows:
                    if job_id in existing:
                        # A hard-keyed row for this job already exists -> the old
                        # soft-keyed row is a duplicate of the same conversation
                        # (one job == one conversation). These are pre-upgrade
                        # duplicates from the legacy onboarding/tracker flow that
                        # created both a sha256 row and a job_id row. Merge the soft
                        # row's messages onto the hard row (UNIQUE dedups via IGNORE)
                        # and drop it, rather than skipping and leaving a duplicate.
                        # The hard row is refreshed on the next scan.
                        self.conn.execute(
                            "UPDATE OR IGNORE hr_messages SET conv_id = ? WHERE conv_id = ?",
                            (job_id, old_conv_id),
                        )
                        self.conn.execute(
                            "DELETE FROM hr_messages WHERE conv_id = ?", (old_conv_id,)
                        )
                        self.conn.execute(
                            "DELETE FROM hr_conversations WHERE conv_id = ?", (old_conv_id,)
                        )
                        continue
                    self.conn.execute(
                        "UPDATE hr_conversations SET conv_id = ? WHERE conv_id = ?",
                        (job_id, old_conv_id),
                    )
                    self.conn.execute(
                        "UPDATE hr_messages SET conv_id = ? WHERE conv_id = ?",
                        (job_id, old_conv_id),
                    )
                    existing.add(job_id)

    def _utcnow_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _row_to_record(self, row: sqlite3.Row) -> ApplicationRecord:
        return ApplicationRecord(
            job_id=row["job_id"],
            title=row["title"],
            company=row["company"],
            url=row["url"] or "",
            status=row["status"],
            hr_name=row["hr_name"],
            city=row["city"],
            salary=row["salary"],
            score=row["score"],
            applied_at=row["applied_at"],
            created_at=row["created_at"],
        )

    def _row_to_hr_conv(self, row: sqlite3.Row) -> HRConversation:
        return HRConversation(
            conv_id=row["conv_id"],
            hr_name=row["hr_name"],
            company=row["company"],
            stage=row["stage"],
            job_id=row["job_id"],
            boss_conv_id=row["boss_conv_id"] or "",
            intent=row["intent"],
            reply_status=row["reply_status"],
            reply_text=row["reply_text"],
            last_msg_preview=row["last_msg_preview"] or "",
            hr_title=(row["hr_title"] if "hr_title" in row.keys() else "") or "",
            wechat_dismissed=bool(row["wechat_dismissed"]) if "wechat_dismissed" in row.keys() else False,
            last_msg_ts=(row["last_msg_ts"] if "last_msg_ts" in row.keys() else 0) or 0,
            last_analyzed_ts=(row["last_analyzed_ts"] if "last_analyzed_ts" in row.keys() else 0) or 0,
            resume_status=(row["resume_status"] if "resume_status" in row.keys() else None),
            matched_resume=(row["matched_resume"] if "matched_resume" in row.keys() else "") or "",
            matched_resume_reason=(row["matched_resume_reason"] if "matched_resume_reason" in row.keys() else "") or "",
            created_at=row["created_at"],
        )

    def _validate_transition(self, old_status: str, new_status: str) -> bool:
        if old_status == new_status:
            return True
        allowed = VALID_TRANSITIONS.get(old_status, set())
        if new_status not in allowed:
            self.logger.warning(
                "Invalid state transition for job application: %s -> %s (allowed: %s)",
                old_status,
                new_status,
                sorted(allowed),
            )
            return False
        return True

    def _upsert_application_row(
        self, record: ApplicationRecord, created_at: str
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO applications (
                job_id, title, company, hr_name, url, status,
                city, salary, score, applied_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                title      = excluded.title,
                company    = excluded.company,
                hr_name    = CASE WHEN excluded.hr_name IS NOT NULL THEN excluded.hr_name ELSE hr_name END,
                url        = excluded.url,
                status     = excluded.status,
                city       = CASE WHEN excluded.city IS NOT NULL AND excluded.city != '' THEN excluded.city ELSE city END,
                salary     = CASE WHEN excluded.salary IS NOT NULL AND excluded.salary != '' THEN excluded.salary ELSE salary END,
                score      = excluded.score,
                applied_at = excluded.applied_at
            """,
            (
                record.job_id,
                record.title,
                record.company,
                record.hr_name,
                record.url,
                record.status,
                record.city,
                record.salary,
                record.score,
                record.applied_at,
                created_at,
            ),
        )

    # ── Applications CRUD ─────────────────────────────────────────────────────

    def exists(self, job_id: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()
        return row is not None

    def upsert(self, record: ApplicationRecord) -> None:
        """Insert or update an application row.

        NOTE: W1's real apply path goes through the `upsert_application` tool
        (tools/db/w1/upsert_application.py), which has NULL-safe CASE guards on
        score/url/applied_at and also writes content_hash -- a column this method
        never touches. This method has no production caller (grep-confirmed: only
        tests/test_tracker.py, test_server.py, test_finalize_w2_tools.py use it). It
        is fixed rather than deleted because a plausible-looking helper with weaker
        NULL semantics is exactly what gets wired up later by mistake -- same
        reasoning as dismiss_reply() below.
        """
        existing = self.conn.execute(
            "SELECT status, created_at FROM applications WHERE job_id = ?",
            (record.job_id,),
        ).fetchone()

        created_at = existing["created_at"] if existing else (record.created_at or self._utcnow_iso())
        if existing and existing["status"] != record.status:
            self._validate_transition(existing["status"], record.status)
            self.logger.info(
                "Status transition [%s]: %s -> %s",
                record.job_id,
                existing["status"],
                record.status,
            )

        with self.conn:
            self._upsert_application_row(record, created_at=created_at)

    def get(self, job_id: str) -> Optional[ApplicationRecord]:
        row = self.conn.execute(
            "SELECT * FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()
        return self._row_to_record(row) if row else None

    def get_application(self, job_id: str) -> Optional[ApplicationRecord]:
        return self.get(job_id)

    def count_today(self) -> int:
        # "Applied today" = real greetings W1 actually sent today. Exclude backfill
        # reconstructions: backfill_application_from_conversation materialises
        # historical applies (HR contacted first / lost / purged) with score NULL and
        # applied_at = now(), which otherwise inflates the counter (e.g. one W2 run
        # backfilled 96 rows -> 147 vs the real ~51). A genuine W1 apply always has a
        # score (a real number, or 0 when score_threshold<=0), so score IS NOT NULL
        # cleanly separates the two.
        today_utc = datetime.now(timezone.utc).date().isoformat()
        row = self.conn.execute(
            """
            SELECT COUNT(*)
            FROM applications
            WHERE status = ? AND applied_at IS NOT NULL
              AND substr(applied_at, 1, 10) = ? AND score IS NOT NULL
            """,
            (AppStatus.APPLIED.value, today_utc),
        ).fetchone()
        return int(row[0]) if row else 0

    def get_all(self) -> List[ApplicationRecord]:
        rows = self.conn.execute(
            "SELECT * FROM applications ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def get_by_status(self, status: Union[AppStatus, str]) -> List[ApplicationRecord]:
        status_value = status.value if isinstance(status, AppStatus) else status
        rows = self.conn.execute(
            "SELECT * FROM applications WHERE status = ? ORDER BY created_at DESC",
            (status_value,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def update_status(self, job_id: str, new_status: AppStatus, **extra_fields) -> None:
        """Update status and optional extra fields in a single SQL UPDATE.

        Accepted extra_fields: score, applied_at, hr_name.

        NOTE: post-apply status moves (REJECTED/INTERVIEWING/OFFER, timeouts, purge)
        run through tools/db/w2/sync_application_status.py, mark_timeout_statuses.py
        and purge_stale_applications.py, which hold their own SQL (see the
        VALID_TRANSITIONS comment above). This method has no production caller
        (grep-confirmed: test-only, same as upsert() above).
        """
        _ALLOWED = {"score", "applied_at", "hr_name"}

        row = self.conn.execute(
            "SELECT status FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row is None:
            self.logger.warning("update_status skipped: job_id %s not found", job_id)
            return

        current_status = row["status"]
        self._validate_transition(current_status, new_status.value)
        self.logger.info(
            "Status transition [%s]: %s -> %s", job_id, current_status, new_status.value
        )

        sets = ["status = ?"]
        params: list = [new_status.value]

        for field_name, value in extra_fields.items():
            if field_name in _ALLOWED:
                sets.append(f"{field_name} = ?")
                params.append(value)

        params.append(job_id)
        with self.conn:
            self.conn.execute(
                f"UPDATE applications SET {', '.join(sets)} WHERE job_id = ?",
                params,
            )

    def get_stats(self) -> Dict[str, object]:
        status_rows = self.conn.execute(
            "SELECT status, COUNT(*) AS count FROM applications GROUP BY status",
        ).fetchall()
        by_status = {status.value: 0 for status in AppStatus}
        for row in status_rows:
            by_status[row["status"]] = int(row["count"])
        total = sum(by_status.values())

        return {
            "total": total,
            "by_status": by_status,
            "applied_today": self.count_today(),
            "interviews": by_status.get(AppStatus.INTERVIEWING.value, 0),
            "offers": by_status.get(AppStatus.OFFER.value, 0),
        }

    def get_lifecycle_counts(self) -> Dict[str, object]:
        """Live overlay for the architecture navigator: table row counts plus the
        current distribution across the two persisted state machines (application
        status, conversation stage). intent lives on hr_conversations too, but the
        architecture page overlays it via stage/status so we keep this query lean.
        """
        stats = self.get_stats()

        stage_rows = self.conn.execute(
            "SELECT stage, COUNT(*) AS count FROM hr_conversations GROUP BY stage",
        ).fetchall()
        by_stage = {row["stage"]: int(row["count"]) for row in stage_rows}

        conv_total = sum(by_stage.values())
        msg_total = int(
            self.conn.execute("SELECT COUNT(*) AS count FROM hr_messages").fetchone()["count"]
        )

        return {
            "tables": {
                "applications": int(stats["total"]),
                "hr_conversations": conv_total,
                "hr_messages": msg_total,
            },
            "by_status": stats["by_status"],
            "by_stage": by_stage,
        }

    def get_data_health(self) -> Dict[str, int]:
        """Aggregates for the regression layer-2 invariants that the dataclass
        getters can't compute (they need EXISTS / anti-joins over hr_messages).

        Each counter is the signature of a bug class we have actually hit, so a
        non-zero value is a regression, not a curiosity:
          - convs_hr_no_intent: read succeeded but analyze never persisted a verdict
            (the #52/#53 "in DB but never analyzed -> invisible forever" bug; 106 rows
            in production on 2026-07-13).
          - orphan_messages: messages whose conversation row is gone -- the analyze
            step reads messages by conv_id, so an orphan means unreachable history.
        """
        convs_hr_no_intent = int(
            self.conn.execute(
                """
                SELECT COUNT(*) AS count FROM hr_conversations c
                WHERE (c.intent IS NULL OR c.intent = '')
                  AND EXISTS (
                      SELECT 1 FROM hr_messages m
                      WHERE m.conv_id = c.conv_id AND m.sender = 'hr'
                  )
                """
            ).fetchone()["count"]
        )
        orphan_messages = int(
            self.conn.execute(
                """
                SELECT COUNT(*) AS count FROM hr_messages m
                WHERE NOT EXISTS (
                    SELECT 1 FROM hr_conversations c WHERE c.conv_id = m.conv_id
                )
                """
            ).fetchone()["count"]
        )
        return {
            "convs_hr_no_intent": convs_hr_no_intent,
            "orphan_messages": orphan_messages,
        }

    def find_application_by_company(self, company: str) -> Optional[ApplicationRecord]:
        row = self.conn.execute(
            """
            SELECT * FROM applications
            WHERE company = ? AND status != ?
            ORDER BY applied_at DESC LIMIT 1
            """,
            (company, AppStatus.FOUND.value),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def delete_non_applied(self) -> int:
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM applications WHERE status != ?",
                (AppStatus.APPLIED.value,),
            )
            return cur.rowcount

    def delete_by_status(self, status: str) -> int:
        with self.conn:
            cur = self.conn.execute("DELETE FROM applications WHERE status = ?", (status,))
            return cur.rowcount

    # ── Scored-jobs eval collection ───────────────────────────────────────────

    def record_scored_job(
        self,
        *,
        job_id: str,
        title: str,
        company: str,
        jd_text: str,
        score: int,
        dimensions: Optional[dict] = None,
        reason: str = "",
        provider_used: str = "",
        threshold: int = 0,
        above_threshold: bool = False,
        cap: int = 2000,
    ) -> None:
        """Append one W1 scoring event (applied or skipped), then trim to the newest
        `cap` rows. Single SQL for this write (tools/db is a thin shell over it)."""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO scored_jobs
                    (job_id, title, company, jd_text, score, dimensions,
                     reason, provider_used, threshold, above_threshold, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id, title, company, jd_text, score,
                    json.dumps(dimensions or {}, ensure_ascii=False),
                    reason, provider_used, threshold,
                    1 if above_threshold else 0, self._utcnow_iso(),
                ),
            )
            self.conn.execute(
                "DELETE FROM scored_jobs WHERE id NOT IN "
                "(SELECT id FROM scored_jobs ORDER BY id DESC LIMIT ?)",
                (cap,),
            )

    def get_scored_jobs(self, limit: Optional[int] = None) -> List[dict]:
        """All recorded scoring events, newest first, for the score-eval exporter.
        `dimensions` is parsed back to a dict."""
        sql = "SELECT * FROM scored_jobs ORDER BY id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        out = []
        for row in self.conn.execute(sql).fetchall():
            d = dict(row)
            try:
                d["dimensions"] = json.loads(d.get("dimensions") or "{}")
            except Exception:
                d["dimensions"] = {}
            out.append(d)
        return out

    # ── HR Conversations ──────────────────────────────────────────────────────

    def upsert_hr_conversation(self, conv: HRConversation, boss_conv_id: str = "") -> None:
        stored_boss_conv_id = boss_conv_id or conv.boss_conv_id or ""
        now = self._utcnow_iso()
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO hr_conversations
                    (conv_id, hr_name, company, job_id, stage, boss_conv_id,
                     intent, reply_status, reply_text, last_msg_preview, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(conv_id) DO UPDATE SET
                    hr_name          = excluded.hr_name,
                    company          = excluded.company,
                    job_id           = CASE WHEN excluded.job_id IS NOT NULL THEN excluded.job_id
                                            ELSE hr_conversations.job_id END,
                    stage            = excluded.stage,
                    boss_conv_id     = CASE WHEN excluded.boss_conv_id != '' THEN excluded.boss_conv_id
                                            ELSE hr_conversations.boss_conv_id END,
                    last_msg_preview = excluded.last_msg_preview
                """,
                (
                    conv.conv_id,
                    conv.hr_name,
                    conv.company,
                    conv.job_id,
                    conv.stage,
                    stored_boss_conv_id,
                    conv.intent,
                    conv.reply_status,
                    conv.reply_text,
                    conv.last_msg_preview,
                    conv.created_at or now,
                ),
            )

    def get_hr_conversation(self, conv_id: str) -> Optional[HRConversation]:
        row = self.conn.execute(
            "SELECT * FROM hr_conversations WHERE conv_id = ?", (conv_id,)
        ).fetchone()
        return self._row_to_hr_conv(row) if row else None

    def get_hr_conversations(
        self,
        stage: Optional[str] = None,
    ) -> List[HRConversation]:
        clauses, params = [], []
        if stage:
            clauses.append("stage = ?")
            params.append(stage)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = self.conn.execute(
            f"SELECT * FROM hr_conversations {where} ORDER BY created_at DESC",
            params,
        ).fetchall()
        return [self._row_to_hr_conv(row) for row in rows]

    def update_hr_analysis(
        self,
        conv_id: str,
        intent: str,
        reply_text: Optional[str] = None,
        reply_status: Optional[str] = None,
        last_analyzed_ts: Optional[int] = None,
    ) -> None:
        """Store LLM analysis results. Single implementation of this transition.

        Does NOT overwrite a reply the user has acted on -- approved / revision /
        sent / dismissed are all preserved (PROTECTED_REPLY_STATUSES). Only null or
        'pending' is freely refreshed, so re-analysis can never clobber a user's
        edit, approval, send, or dismissal.

        Passing None for reply_text/reply_status leaves the stored value alone; it
        does NOT blank it. (An earlier copy of this method in tracker wrote the NULL
        through, wiping drafts -- the tool layer had the correct behaviour and this
        is now the only version.)

        last_analyzed_ts is the dirty-check watermark, advanced ONLY here, i.e. only
        when analyze actually concluded. A DEGRADED analyze never reaches this call,
        so the watermark stays behind and filter_conversations re-selects the
        conversation next run (#53). MAX guards against out-of-order regress; None
        leaves it untouched.
        """
        # No reply_status whitelist here on purpose: this is the storage layer, and
        # legitimate callers (approve/dismiss flows, tests building fixtures) need to
        # set decided statuses directly. The restriction that RE-ANALYSIS may only
        # ask for null/pending/sent belongs to the pipeline's entry point, so it is
        # enforced in the update_hr_analysis tool instead. Constrain at the door,
        # not in the vault.
        protected_sql = ", ".join(f"'{s}'" for s in sorted(PROTECTED_REPLY_STATUSES))

        # Make sure the row exists before UPDATE-ing it. W2 analyses a conversation
        # BEFORE the pipeline upserts it (stage depends on the intent we are about
        # to compute), so for a conversation W1 never applied to -- an HR who
        # messaged first, or a legacy row being re-keyed -- the UPDATE matched zero
        # rows and silently dropped the intent, the draft AND the watermark. The
        # later upsert then wrote stage/preview only, leaving rows whose stage had
        # advanced while intent stayed empty (4 such rows found in production).
        # Identity columns are left blank here; the upsert that follows fills them.
        with self.conn:
            self.conn.execute(
                """
                INSERT OR IGNORE INTO hr_conversations (conv_id, hr_name, company, stage, created_at)
                VALUES (?, '', '', 'new', ?)
                """,
                (conv_id, self._utcnow_iso()),
            )
        # NOTE: hr_conversations has no `updated_at` column (T030 keeps only
        # created_at). An earlier version wrote it here and every call raised
        # "no such column", so analysis was never persisted. Don't re-add it
        # without adding the column.
        with self.conn:
            self.conn.execute(
                f"""
                UPDATE hr_conversations SET
                    intent       = ?,
                    reply_text   = CASE
                        WHEN reply_status IN ({protected_sql}) THEN reply_text
                        WHEN ? IS NOT NULL THEN ?
                        ELSE reply_text
                    END,
                    reply_status = CASE
                        WHEN reply_status IN ({protected_sql}) THEN reply_status
                        WHEN ? IS NOT NULL THEN ?
                        ELSE reply_status
                    END,
                    last_analyzed_ts = CASE
                        WHEN ? IS NULL THEN last_analyzed_ts
                        ELSE MAX(last_analyzed_ts, ?)
                    END
                WHERE conv_id = ?
                """,
                (intent, reply_text, reply_text, reply_status, reply_status,
                 last_analyzed_ts, last_analyzed_ts, conv_id),
            )

    def dismiss_wechat(self, conv_id: str) -> None:
        """Mark the go-add-WeChat reminder for a conversation as dismissed (已添加)."""
        with self.conn:
            self.conn.execute(
                "UPDATE hr_conversations SET wechat_dismissed = 1 WHERE conv_id = ?",
                (conv_id,),
            )

    def update_reply_approval(
        self,
        conv_id: str,
        reply_status: str,
        reply_text: Optional[str] = None,
    ) -> None:
        """Change a reply's approval status.

        reply_text is written ONLY when explicitly provided (revise). For
        status-only transitions (approve / cancel / dismiss) the existing draft
        is preserved. Passing it implicitly as "" previously wiped the suggested
        reply, so approved replies were sent empty.
        """
        with self.conn:
            if reply_text is None:
                self.conn.execute(
                    "UPDATE hr_conversations SET reply_status = ? WHERE conv_id = ?",
                    (reply_status, conv_id),
                )
            else:
                self.conn.execute(
                    "UPDATE hr_conversations SET reply_status = ?, reply_text = ? WHERE conv_id = ?",
                    (reply_status, reply_text or None, conv_id),
                )

    def invalidate_reply_for_reanalysis(self, conv_id: str) -> int:
        """Void a stale approved/revision reply and reset it to 'unanalyzed'.

        Called when W3 detects, at send time, that the conversation advanced since
        the reply was approved (someone spoke after the HR message the draft
        answered -- the user replied by hand, a resume card went out, or a prior
        send landed unmarked). Sending the draft would double-message or answer an
        already-handled turn, so instead of sending we:
          - drop the draft (reply_text='') and its approval (reply_status=NULL) so
            it leaves the send queue AND is no longer PROTECTED from re-analysis;
          - clear intent and knock last_analyzed_ts back to 0, which makes
            filter_conversations re-select the conversation on the next W2 run so
            AnalyzeStep re-decides intent and re-drafts into the approval queue iff
            a reply is still due.
        Only touches a reply still queued to send (approved/revision); a status that
        already moved on is left alone. Single implementation of this transition
        (see CLAUDE.md "一个状态转换只能有一份 SQL"). Returns rows updated.
        """
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE hr_conversations
                SET reply_status     = NULL,
                    reply_text       = '',
                    intent           = '',
                    last_analyzed_ts = 0
                WHERE conv_id = ? AND reply_status IN ('approved', 'revision')
                """,
                (conv_id,),
            )
            return cur.rowcount

    def dismiss_all_pending_replies(self) -> int:
        """Bulk-dismiss every reply still awaiting approval (reply_status='pending').
        Approved/revision/sent replies are left untouched -- the user has already
        acted on those; only un-triaged drafts (which pile up from stale/ancient
        conversations) get cleared. Returns the number of replies dismissed."""
        with self.conn:
            cur = self.conn.execute(
                "UPDATE hr_conversations SET reply_status = 'dismissed' WHERE reply_status = 'pending'",
            )
            return cur.rowcount

    def get_pending_replies(self) -> List[HRConversation]:
        rows = self.conn.execute(
            """
            SELECT * FROM hr_conversations
            WHERE reply_status IN ('pending', 'approved')
            ORDER BY created_at DESC
            """,
        ).fetchall()
        return [self._row_to_hr_conv(row) for row in rows]

    def get_approved_replies(self) -> List[HRConversation]:
        rows = self.conn.execute(
            "SELECT * FROM hr_conversations WHERE reply_status IN ('approved', 'revision')"
        ).fetchall()
        return [self._row_to_hr_conv(row) for row in rows]

    # -- manual resume-send queue (W2 detection-miss fallback) -------------------
    # resume_status mirrors reply_status for the resume side: the user stages a send
    # (DB-only, browser untouched -> fully cancellable), and W3 delivers it. NULL is
    # the correct neutral BOTH before queueing AND after a send completes (the fact
    # that a resume WAS sent is recorded by stage=resume_sent, not here) -- so a
    # single set_resume_status transition covers queue / cancel / post-send clear.

    def set_resume_status(self, conv_id: str, status: Optional[str]) -> int:
        """Set the manual resume-queue intent. status='queued' stages a send; None
        clears it (user cancelled, or W3 finished delivering). Single SQL for this
        transition. Returns rows updated so callers distinguish a missing conv."""
        assert status in (None, "queued"), f"invalid resume_status: {status!r}"
        with self.conn:
            cur = self.conn.execute(
                "UPDATE hr_conversations SET resume_status = ? WHERE conv_id = ?",
                (status, conv_id),
            )
            return cur.rowcount

    def set_matched_resume(self, conv_id: str, name: str, reason: str) -> int:
        """记录「这个岗位该发哪一份简历」（W2 路由决策，只选不写）。

        唯一一份 SQL。存名字而非 slug：简历可能被删，事后追溯时名字仍可读；
        真要发送时按名字回查 index，查不到就退回当前激活份。
        """
        with self.conn:
            cur = self.conn.execute(
                "UPDATE hr_conversations SET matched_resume = ?, matched_resume_reason = ? WHERE conv_id = ?",
                (name or "", reason or "", conv_id),
            )
            return cur.rowcount

    def get_queued_resumes(self) -> List[HRConversation]:
        """Conversations the user manually staged for a resume send (W3 delivers)."""
        rows = self.conn.execute(
            "SELECT * FROM hr_conversations WHERE resume_status = 'queued'"
        ).fetchall()
        return [self._row_to_hr_conv(row) for row in rows]

    def mark_reply_sent(self, conv_id: str) -> int:
        """Authoritative transition after a reply was actually sent to the HR.

        Sets reply_status='sent' and clears the working draft. 'sent' is one of the
        PROTECTED statuses in update_hr_analysis, so a later re-analysis will not
        revive the reply.

        This used to write NULL/NULL, which is NOT protected: a conversation marked
        that way looked "never processed" to the next re-analysis, which could draft
        and send a second reply to the same HR. The same transition existed in three
        places with two different meanings (this method, the mark_reply_sent tool,
        and the mark-sent endpoint's inline SQL); they now all route here so the SQL
        lives in exactly one place.

        Returns the number of rows updated, so callers can tell a missing
        conversation from a successful transition.
        """
        with self.conn:
            cur = self.conn.execute(
                "UPDATE hr_conversations SET reply_status = 'sent', reply_text = '' WHERE conv_id = ?",
                (conv_id,),
            )
            return cur.rowcount

    def dismiss_reply(self, conv_id: str) -> bool:
        """Dismiss a drafted reply the user does not want sent.

        Writes 'dismissed', which is one of PROTECTED_REPLY_STATUSES, so the next
        re-analysis leaves it alone. It used to write NULL -- and NULL is NOT
        protected, so the conversation looked "never processed" to the next W2 scan,
        which would draft a fresh reply and put it back in the approval queue. Same
        mistake mark_reply_sent once made: a user decision must not be recorded as a
        neutral state, or the automation treats it as unfinished work.

        NOTE: the dashboard's dismiss endpoint goes through update_reply_approval()
        and already wrote 'dismissed' correctly; this method has no production
        caller. It is fixed rather than deleted because a plausible-looking helper
        with the wrong semantics is exactly what gets wired up later by mistake.
        """
        with self.conn:
            cur = self.conn.execute(
                "UPDATE hr_conversations SET reply_status = 'dismissed' WHERE conv_id = ?",
                (conv_id,),
            )
        return cur.rowcount > 0

    def reset_hr_conversation_stage(self, conv_id: str, stage: str = "new") -> None:
        with self.conn:
            self.conn.execute(
                "UPDATE hr_conversations SET stage = ? WHERE conv_id = ?",
                (stage, conv_id),
            )

    def get_hr_names_by_job_ids(self, job_ids: list) -> dict:
        if not job_ids:
            return {}
        placeholders = ",".join("?" * len(job_ids))
        rows = self.conn.execute(
            f"SELECT job_id, hr_name FROM hr_conversations WHERE job_id IN ({placeholders})",
            job_ids,
        ).fetchall()
        return {row["job_id"]: row["hr_name"] for row in rows if row["hr_name"]}

    # ── HR Messages ───────────────────────────────────────────────────────────

    def insert_hr_messages(self, conv_id: str, messages: List[dict]) -> int:
        """Batch-insert messages, skipping UNIQUE conflicts. Returns count inserted."""
        now = self._utcnow_iso()
        inserted = 0
        with self.conn:
            for msg in messages:
                cur = self.conn.execute(
                    """
                    INSERT OR IGNORE INTO hr_messages (conv_id, sender, text, msg_time, created_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        conv_id,
                        msg.get("sender", ""),
                        msg.get("text", ""),
                        msg.get("msg_time") or msg.get("time"),
                        now,
                    ),
                )
                inserted += cur.rowcount
        return inserted

    def get_hr_messages(self, conv_id: str) -> List[dict]:
        """Return all messages for a conversation ordered by insertion id."""
        rows = self.conn.execute(
            "SELECT sender, text, msg_time, created_at FROM hr_messages WHERE conv_id = ? ORDER BY id",
            (conv_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self.conn.close()
