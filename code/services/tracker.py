import json
import sqlite3
import os
import threading
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Union

from multisite.site_manual import SiteManual
from schemas import (
    AppStatus, ApplicationRecord, HRConversation, PendingApplication, PendingJob,
    SiteBrief, SiteLimit,
)
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
            # pending_applications: Layer 2 (人工审批) queue for the multi-site apply
            # architecture (docs/multi-site-expansion-design.md). Layer 1 does not exist
            # yet -- rows are seeded manually (scripts/seed_pending_application.py) until
            # it does. `fields` is a JSON array of {field_id, label, kind, candidate_value};
            # government_id fields never carry a candidate_value, the reviewer fills them.
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_applications (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_name    TEXT NOT NULL,
                    job_title    TEXT NOT NULL,
                    company      TEXT DEFAULT '',
                    job_url      TEXT DEFAULT '',
                    fields       TEXT NOT NULL,
                    status       TEXT NOT NULL DEFAULT 'pending',
                    reason       TEXT,
                    created_at   TEXT NOT NULL,
                    decided_at   TEXT
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pending_applications_status ON pending_applications(status)"
            )
            # Migration: link a field-approval record back to the job-selection record
            # it came from (Checkpoint 1 -> Checkpoint 2 is 1:N). NULL on legacy rows
            # and on any run that skipped job selection (--job-url debugging path).
            pa_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(pending_applications)")}
            if "source_job_id" not in pa_cols:
                self.conn.execute("ALTER TABLE pending_applications ADD COLUMN source_job_id INTEGER")
            # Migration: a full-page screenshot of the form, taken by CODE (not the
            # agent -- DeepSeek has no vision and take_screenshot is not in its
            # allowlist). It exists so the reviewer can see WHERE a field sits: the
            # label alone is often not enough to decide ("学校名称" -- 本科 or 硕士?).
            if "screenshot" not in pa_cols:
                self.conn.execute("ALTER TABLE pending_applications ADD COLUMN screenshot TEXT")

            # pending_jobs: Checkpoint 1 -- candidates the selection agent found,
            # awaiting human approval before anything touches an application form.
            # `url` is UNIQUE so re-running selection can't queue the same job twice
            # (the agent has no memory across runs; dedup has to live here).
            # category vs category_agent: see schemas.PendingJob -- two columns on
            # purpose, the diff between them is the human-correction signal.
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_jobs (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    site_name      TEXT NOT NULL,
                    url            TEXT NOT NULL UNIQUE,
                    title          TEXT DEFAULT '',
                    company        TEXT DEFAULT '',
                    category       TEXT DEFAULT '',
                    category_agent TEXT DEFAULT '',
                    why            TEXT DEFAULT '',
                    status         TEXT NOT NULL DEFAULT 'pending',
                    reason         TEXT,
                    found_at       TEXT NOT NULL,
                    decided_at     TEXT
                )
                """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pending_jobs_status ON pending_jobs(status)"
            )
            # Migration: is_golden marks a human category correction the reviewer
            # explicitly confirmed as a teaching example, fed back into the selection
            # agent's prompt (see multisite.preferences.render_golden_examples).
            # Separate from "the reviewer changed the category": a casual edit is not
            # necessarily a canonical case, and only confirmed ones belong in a prompt.
            pj_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(pending_jobs)")}
            if "is_golden" not in pj_cols:
                self.conn.execute("ALTER TABLE pending_jobs ADD COLUMN is_golden INTEGER NOT NULL DEFAULT 0")
            # Migration: which recruitment project (bucket) the job was found in.
            # Existing rows stay '' -- they were recorded before the agent reported it,
            # and guessing would corrupt the per-bucket quota maths this column exists for.
            if "bucket" not in pj_cols:
                self.conn.execute("ALTER TABLE pending_jobs ADD COLUMN bucket TEXT NOT NULL DEFAULT ''")

            # site_limits: how many positions one person may apply to, discovered
            # opportunistically by the selection agent. `status` is THREE-way
            # (unknown / no_limit / limited) and `scope` is THREE-way too
            # (site / bucket / unclear) -- see schemas.SiteLimit for why neither can be
            # collapsed into a nullable number.
            #
            # PK is (site_name, scope_name), not site_name: the very first real evidence
            # was scoped to one recruitment project ("在'27届秋招（研发类）'招聘项目中
            # ……最多可以投递 2 次"), so one site can carry several independent limits.
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS site_limits (
                    site_name        TEXT NOT NULL,
                    scope            TEXT NOT NULL DEFAULT 'unclear',
                    scope_name       TEXT NOT NULL DEFAULT '',
                    status           TEXT NOT NULL DEFAULT 'unknown',
                    max_applications INTEGER,
                    applied_count    INTEGER NOT NULL DEFAULT -1,
                    evidence         TEXT DEFAULT '',
                    seen_at          TEXT NOT NULL,
                    PRIMARY KEY (site_name, scope_name)
                )
                """
            )
            # Migration: the first cut keyed on site_name alone. SQLite cannot alter a
            # primary key, so rebuild. Old rows carry scope='unclear' -- they were
            # recorded before the agent was asked to judge scope, and calling them
            # site-wide would be inventing a fact we never had.
            sl_cols = {r[1] for r in self.conn.execute("PRAGMA table_info(site_limits)")}
            if "scope" not in sl_cols:
                self.conn.execute("ALTER TABLE site_limits RENAME TO site_limits_old")
                self.conn.execute(
                    """
                    CREATE TABLE site_limits (
                        site_name        TEXT NOT NULL,
                        scope            TEXT NOT NULL DEFAULT 'unclear',
                        scope_name       TEXT NOT NULL DEFAULT '',
                        status           TEXT NOT NULL DEFAULT 'unknown',
                        max_applications INTEGER,
                        applied_count    INTEGER NOT NULL DEFAULT -1,
                        evidence         TEXT DEFAULT '',
                        seen_at          TEXT NOT NULL,
                        PRIMARY KEY (site_name, scope_name)
                    )
                    """
                )
                self.conn.execute(
                    """
                    INSERT INTO site_limits
                        (site_name, scope, scope_name, status, max_applications,
                         applied_count, evidence, seen_at)
                    SELECT site_name, 'unclear', '', status, max_applications,
                           applied_count, evidence, seen_at
                    FROM site_limits_old
                    """
                )
                self.conn.execute("DROP TABLE site_limits_old")

            # site_briefs: 选岗 agent 看完一个站之后写的现场笔记，喂回下次的 prompt。
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS site_briefs (
                    site_name  TEXT PRIMARY KEY,
                    brief      TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL
                )
                """
            )

            # site_manuals: survey_structure 产出的站点操作手册，本轮可执行的结构化事实，
            # 代码消费（match manual.job_url_source）。与 site_briefs 并存、职责分开，
            # 不是同一转换的第二份 SQL。
            self.conn.execute(
                """
                CREATE TABLE IF NOT EXISTS site_manuals (
                    site_name  TEXT PRIMARY KEY,
                    manual     TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

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

    def get_many(self, job_ids: list[str]) -> Dict[str, ApplicationRecord]:
        """Batch variant of get() — one query for N ids instead of N queries.
        Used by /api/conversations, which needs the job title/url for every distinct
        job_id among the returned conversations."""
        if not job_ids:
            return {}
        placeholders = ",".join("?" * len(job_ids))
        rows = self.conn.execute(
            f"SELECT * FROM applications WHERE job_id IN ({placeholders})", job_ids
        ).fetchall()
        return {row["job_id"]: self._row_to_record(row) for row in rows}

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

    def get_hr_messages_bulk(self, conv_ids: List[str]) -> Dict[str, List[dict]]:
        """Batch variant of get_hr_messages() — one query for N conversations instead
        of N queries. /api/conversations serializes every conversation's full message
        list; at 900+ rows the per-conversation N+1 was the dominant cost."""
        result: Dict[str, List[dict]] = {cid: [] for cid in conv_ids}
        if not conv_ids:
            return result
        placeholders = ",".join("?" * len(conv_ids))
        rows = self.conn.execute(
            f"SELECT conv_id, sender, text, msg_time, created_at FROM hr_messages "
            f"WHERE conv_id IN ({placeholders}) ORDER BY conv_id, id",
            conv_ids,
        ).fetchall()
        for row in rows:
            d = dict(row)
            result[d.pop("conv_id")].append(d)
        return result

    # ── Pending Applications (Layer 2 审批队列) ─────────────────────────────────

    def _row_to_pending_application(self, row: sqlite3.Row) -> PendingApplication:
        return PendingApplication(
            id=row["id"],
            site_name=row["site_name"],
            job_title=row["job_title"],
            company=row["company"] or "",
            job_url=row["job_url"] or "",
            fields=json.loads(row["fields"]),
            status=row["status"],
            reason=row["reason"],
            created_at=row["created_at"],
            decided_at=row["decided_at"],
            screenshot=row["screenshot"] or "",
            source_job_id=row["source_job_id"],
        )

    def add_pending_application(
        self,
        site_name: str,
        job_title: str,
        fields: list,
        company: str = "",
        job_url: str = "",
        source_job_id: Optional[int] = None,
        screenshot: str = "",
    ) -> int:
        """Insert a new Layer 1 candidate awaiting Layer 2 approval. Returns the new id."""
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO pending_applications
                    (site_name, job_title, company, job_url, fields, status, created_at,
                     source_job_id, screenshot)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                """,
                (site_name, job_title, company, job_url, json.dumps(fields, ensure_ascii=False),
                 self._utcnow_iso(), source_job_id, screenshot),
            )
            return cur.lastrowid

    # -- Checkpoint 1: pending_jobs (job selection approval) --------------------

    @staticmethod
    def _row_to_pending_job(row) -> PendingJob:
        return PendingJob(
            id=row["id"],
            site_name=row["site_name"],
            url=row["url"],
            title=row["title"] or "",
            company=row["company"] or "",
            category=row["category"] or "",
            category_agent=row["category_agent"] or "",
            why=row["why"] or "",
            bucket=row["bucket"] or "",
            status=row["status"],
            reason=row["reason"],
            found_at=row["found_at"],
            decided_at=row["decided_at"],
            is_golden=bool(row["is_golden"]),
        )

    def add_pending_job(
        self,
        site_name: str,
        url: str,
        title: str = "",
        company: str = "",
        category: str = "",
        why: str = "",
        bucket: str = "",
    ) -> Optional[int]:
        """Record one candidate job for Checkpoint 1. Returns the new id, or None if
        this url is already in the table.

        `category_agent` is seeded from the same value as `category` and never written
        again -- the pair is what makes a later human correction visible (see
        schemas.PendingJob).

        Returning None (rather than raising) on a duplicate url is deliberate: the
        selection agent has no memory across runs, so re-running selection on the same
        site WILL re-find jobs already awaiting approval. That is normal, not an error.
        """
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT OR IGNORE INTO pending_jobs
                    (site_name, url, title, company, category, category_agent, why,
                     bucket, status, found_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
                """,
                (site_name, url, title, company, category, category, why, bucket,
                 self._utcnow_iso()),
            )
            return cur.lastrowid if cur.rowcount else None

    def get_pending_jobs(self, status: Optional[str] = None) -> List[PendingJob]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM pending_jobs WHERE status = ? ORDER BY found_at DESC", (status,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM pending_jobs ORDER BY found_at DESC",
            ).fetchall()
        return [self._row_to_pending_job(row) for row in rows]

    def get_pending_job(self, job_id: int) -> Optional[PendingJob]:
        row = self.conn.execute("SELECT * FROM pending_jobs WHERE id = ?", (job_id,)).fetchone()
        return self._row_to_pending_job(row) if row else None

    def decide_pending_job(self, job_id: int, decision: str, reason: Optional[str] = None) -> int:
        """Record the Checkpoint 1 approve/reject -- the only writer of status/reason/
        decided_at on this table.

        **Deliberately does NOT write `category`.** Category (and is_golden) belong to
        `set_pending_job_review`, so each column has exactly one writer. An earlier
        version took a `category` here too; that is the same shape as the four
        same-column-two-writers drifts this project already got bitten by (see
        docs/audit-remediation-log.md), so it was split before it could rot.

        `WHERE status = 'pending'` makes a double-decide a no-op returning 0 rather than
        re-deciding a job that already went to the fill stage.
        """
        assert decision in ("approved", "rejected"), f"invalid decision: {decision!r}"
        with self.conn:
            cur = self.conn.execute(
                """
                UPDATE pending_jobs SET status = ?, reason = ?, decided_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (decision, reason, self._utcnow_iso(), job_id),
            )
            return cur.rowcount

    def set_pending_job_review(
        self,
        job_id: int,
        category: Optional[str] = None,
        is_golden: Optional[bool] = None,
    ) -> int:
        """The only writer of `category` and `is_golden` on pending_jobs.

        Both args are tri-state: None = leave that column alone. This lets the UI
        confirm a golden without re-sending the category, and vice versa.

        `category_agent` is never touched here (or anywhere after insert) -- the
        difference between the two columns IS the correction signal.

        Deliberately **not** gated on `status = 'pending'`, unlike decide_pending_job:
        noticing a misclassification after approving is normal, and curating the golden
        set is independent of the approval lifecycle.
        """
        sets, params = [], []
        if category is not None:
            sets.append("category = ?")
            params.append(category)
        if is_golden is not None:
            sets.append("is_golden = ?")
            params.append(1 if is_golden else 0)
        if not sets:
            return 0
        params.append(job_id)
        with self.conn:
            cur = self.conn.execute(
                f"UPDATE pending_jobs SET {', '.join(sets)} WHERE id = ?", params,
            )
            return cur.rowcount

    # -- site application limits ----------------------------------------------

    _SITE_LIMIT_STATUSES = ("unknown", "no_limit", "limited")

    _SITE_LIMIT_SCOPES = ("site", "bucket", "unclear")

    def upsert_site_limit(
        self,
        site_name: str,
        status: str,
        scope: str = "unclear",
        scope_name: str = "",
        max_applications: Optional[int] = None,
        applied_count: int = -1,
        evidence: str = "",
    ) -> None:
        """记下一条投递数量限制。同一 (站点, 范围) 后来居上。

        `scope_name` 是主键的一部分：一个站可以同时有好几条互不相干的上限
        （拓竹的研发类和非研发类各算各的）。scope='site'/'unclear' 时它是空串。

        **`status='unknown'` 不会覆盖已知结果**：agent 每次跑都可能没看到那段说明
        （它是机会性发现的），如果"这次没看见"能把上次真读到的 `limited(2)` 冲掉，
        那这张表就永远停在 unknown——已知信息被无知覆盖是净损失。
        """
        assert status in self._SITE_LIMIT_STATUSES, f"invalid status: {status!r}"
        assert scope in self._SITE_LIMIT_SCOPES, f"invalid scope: {scope!r}"
        scope_name = scope_name if scope == "bucket" else ""
        if status == "unknown":
            existing = self.get_site_limit(site_name, scope_name)
            if existing is not None and existing.status != "unknown":
                return
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO site_limits
                    (site_name, scope, scope_name, status, max_applications,
                     applied_count, evidence, seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(site_name, scope_name) DO UPDATE SET
                    scope = excluded.scope,
                    status = excluded.status,
                    max_applications = excluded.max_applications,
                    applied_count = excluded.applied_count,
                    evidence = excluded.evidence,
                    seen_at = excluded.seen_at
                """,
                (site_name, scope, scope_name, status, max_applications, applied_count,
                 evidence, self._utcnow_iso()),
            )

    def clear_site_limit(self, site_name: str, scope_name: str = "") -> int:
        """人工把一条上限退回「未知」。返回删掉的行数。

        **单独一个方法而不是让端点自己 DELETE**：删除是这张表的第三种写操作，
        端点里内联 SQL 就是"同一张表的写入散在两个层"——本项目连抓四例的正是这个
        形状（见 CLAUDE.md 第二条铁律）。

        为什么是删而不是 upsert 成 `unknown`：`upsert_site_limit` 刻意让 unknown
        不覆盖已知（防 agent 用无知冲掉真读到的数字），人工重置要的正是绕过那条
        保护。删掉行 = 回到"什么都没记到"，跟从没跑过这个站是同一个状态。
        """
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM site_limits WHERE site_name = ? AND scope_name = ?",
                (site_name, scope_name),
            )
            return cur.rowcount

    @staticmethod
    def _row_to_site_limit(row) -> SiteLimit:
        return SiteLimit(
            site_name=row["site_name"],
            status=row["status"],
            scope=row["scope"],
            scope_name=row["scope_name"] or "",
            max_applications=row["max_applications"],
            applied_count=row["applied_count"],
            evidence=row["evidence"] or "",
            seen_at=row["seen_at"],
        )

    def get_site_limit(self, site_name: str, scope_name: str = "") -> Optional[SiteLimit]:
        row = self.conn.execute(
            "SELECT * FROM site_limits WHERE site_name = ? AND scope_name = ?",
            (site_name, scope_name),
        ).fetchone()
        return self._row_to_site_limit(row) if row else None

    def get_site_limits(self, site_name: str) -> List[SiteLimit]:
        """这个站的**所有**上限记录（可能一条全站的、也可能几条按招聘项目分的）。"""
        rows = self.conn.execute(
            "SELECT * FROM site_limits WHERE site_name = ? ORDER BY scope_name", (site_name,),
        ).fetchall()
        return [self._row_to_site_limit(r) for r in rows]

    # -- site briefs -----------------------------------------------------------

    def upsert_site_brief(self, site_name: str, brief: str) -> None:
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO site_briefs (site_name, brief, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(site_name) DO UPDATE SET
                    brief = excluded.brief, updated_at = excluded.updated_at
                """,
                (site_name, brief, self._utcnow_iso()),
            )

    def get_site_brief(self, site_name: str) -> Optional[SiteBrief]:
        row = self.conn.execute(
            "SELECT * FROM site_briefs WHERE site_name = ?", (site_name,)
        ).fetchone()
        if row is None:
            return None
        return SiteBrief(site_name=row["site_name"], brief=row["brief"] or "",
                         updated_at=row["updated_at"])

    # -- site manuals ------------------------------------------------------------

    def upsert_site_manual(self, site_name: str, manual: SiteManual) -> None:
        """站点操作手册。与 `site_briefs` **并存、职责分开**——手册是本轮可执行的
        结构化事实（代码消费），brief 是跨轮经验笔记（喂 prompt 给模型看）。
        列集不同、消费方不同，不是分叉。"""
        with self.conn:
            self.conn.execute(
                """
                INSERT INTO site_manuals (site_name, manual, updated_at) VALUES (?, ?, ?)
                ON CONFLICT(site_name) DO UPDATE SET
                    manual = excluded.manual, updated_at = excluded.updated_at
                """,
                (site_name, json.dumps(manual.to_dict(), ensure_ascii=False), self._utcnow_iso()),
            )

    def get_site_manual(self, site_name: str) -> Optional[tuple[SiteManual, str]]:
        """返回 `(SiteManual, updated_at)`；没有则 None。"""
        row = self.conn.execute(
            "SELECT manual, updated_at FROM site_manuals WHERE site_name = ?", (site_name,)
        ).fetchone()
        if row is None:
            return None
        return SiteManual.from_dict(json.loads(row["manual"])), row["updated_at"]

    def get_golden_category_examples(self, limit: int = 20) -> List[PendingJob]:
        """人工确认过的归类纠正，喂回选岗 agent 的 prompt。

        只取 `category != category_agent` 的：确认了但类别没变的行是"agent 判对了"，
        当正例塞进 prompt 只是占上下文。倒序取最近的——归类口径会随用户偏好漂移，
        新的纠正比旧的更能代表当前标准。
        """
        rows = self.conn.execute(
            """
            SELECT * FROM pending_jobs
            WHERE is_golden = 1 AND category_agent != '' AND category != category_agent
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._row_to_pending_job(row) for row in rows]

    def get_pending_applications(self, status: Optional[str] = None) -> List[PendingApplication]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM pending_applications WHERE status = ? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM pending_applications ORDER BY created_at DESC",
            ).fetchall()
        return [self._row_to_pending_application(row) for row in rows]

    def get_pending_application(self, application_id: int) -> Optional[PendingApplication]:
        row = self.conn.execute(
            "SELECT * FROM pending_applications WHERE id = ?",
            (application_id,),
        ).fetchone()
        return self._row_to_pending_application(row) if row else None

    def decide_pending_application(
        self,
        application_id: int,
        decision: str,
        fields: Optional[list] = None,
        reason: Optional[str] = None,
    ) -> int:
        """Record the reviewer's decision -- the only place the Layer 2 go-signal is
        written. decision='approved' expects the reviewer-edited `fields` (with any
        government_id values filled in by hand) as the final values that Layer 3 will
        act on; decision='rejected' expects an optional `reason`. Returns rows updated."""
        assert decision in ("approved", "rejected"), f"invalid decision: {decision!r}"
        with self.conn:
            if fields is not None:
                cur = self.conn.execute(
                    """
                    UPDATE pending_applications
                    SET status = ?, fields = ?, reason = ?, decided_at = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (decision, json.dumps(fields, ensure_ascii=False), reason,
                     self._utcnow_iso(), application_id),
                )
            else:
                cur = self.conn.execute(
                    """
                    UPDATE pending_applications
                    SET status = ?, reason = ?, decided_at = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (decision, reason, self._utcnow_iso(), application_id),
                )
            return cur.rowcount

    def close(self) -> None:
        self.conn.close()
