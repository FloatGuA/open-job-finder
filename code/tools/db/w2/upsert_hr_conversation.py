from datetime import datetime, timezone
from typing import Optional

from tools.base import BaseTool, ToolResult


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# This tool is the CANONICAL live write path for a conversation's identity/stage:
# every W2 scan and the W1 apply-time stub go through it. It deliberately does NOT
# touch intent/reply_status/reply_text — those belong to update_hr_analysis. The
# separate tracker.upsert_hr_conversation() method DOES write those and exists
# only for onboarding seeding; the two are not duplicates (different column sets,
# different callers) and are intentionally kept apart rather than merged.
#
# NOTE: hr_title, job_id and last_msg_ts ARE real columns (migrations in
# tracker._init_db). job_id is the hard-association key (== Boss encryptJobId ==
# applications.job_id); last_msg_ts is the millisecond timestamp used by
# filter_conversations for dirty detection. job_title/updated_at remain
# NON-columns -- accepted for caller compatibility but not persisted (an earlier
# version INSERTed them and raised "no such column"). created_at is insert-only.
class UpsertHRConversation(BaseTool):
    name = "upsert_hr_conversation"
    description = "Insert or update an HR conversation row; stage only moves forward."
    input_schema = {
        "type": "object",
        "properties": {
            "conv_id":          {"type": "string"},
            "hr_name":          {"type": "string"},
            "company":          {"type": "string"},
            "boss_conv_id":     {"type": "string"},
            "stage":            {"type": "string"},
            "last_msg_preview": {"type": "string"},
            "hr_title":         {"type": "string"},
            "job_title":        {"type": "string"},
            "job_id":           {"type": "string"},
            "last_msg_ts":      {"type": "integer"},
        },
        "required": ["conv_id", "hr_name", "company"],
    }

    def __init__(self, db) -> None:
        self._db = db

    def execute(
        self,
        *,
        conv_id: str,
        hr_name: str,
        company: str,
        boss_conv_id: str = "",
        stage: str = "new",
        last_msg_preview: str = "",
        hr_title: str = "",
        # 接受但不落库（调用方兼容，见文件顶部注释）。2026-08-22 查证：
        # Boss 会话列表的 API 和 DOM 都**不带岗位名**，所以这里也没有值可存
        # ——实测记录在 extract_conversation_list 的诊断字段那段。
        job_title: str = "",
        job_id: str = "",
        last_msg_ts: int = 0,
    ) -> ToolResult:
        now = _utcnow_iso()

        try:
            # Hard-key absorption at scan time. Conversations first seen BEFORE this
            # upgrade were keyed by the sha256(hr_name|company) soft key with job_id
            # NULL; the one-shot re-key migration could only fix rows that already
            # had a job_id. So the first time such a conversation is re-scanned WITH
            # a job_id (conv_id == job_id), absorb its legacy soft-keyed row into the
            # hard key — re-key conv_id + cascade hr_messages — instead of inserting a
            # duplicate that orphans the old row's history. Matches on hr_name+company
            # (best-effort; a mismatch just falls through to a fresh row, no worse than
            # before). This converges the 606 legacy rows as they resurface.
            if job_id and conv_id == job_id:
                legacy = self._db.conn.execute(
                    "SELECT conv_id FROM hr_conversations "
                    "WHERE hr_name = ? AND company = ? "
                    "AND (job_id IS NULL OR job_id = '') AND conv_id != ?",
                    (hr_name, company, conv_id),
                ).fetchone()
                if legacy:
                    legacy_id = legacy[0]
                    target_exists = self._db.conn.execute(
                        "SELECT 1 FROM hr_conversations WHERE conv_id = ?", (conv_id,)
                    ).fetchone()
                    with self._db.conn:
                        if target_exists:
                            # Both rows exist: move the legacy row's messages onto the
                            # hard-keyed row (UNIQUE(conv_id,sender,text) dedups via
                            # IGNORE) and drop the orphan.
                            self._db.conn.execute(
                                "UPDATE OR IGNORE hr_messages SET conv_id = ? WHERE conv_id = ?",
                                (conv_id, legacy_id),
                            )
                            self._db.conn.execute(
                                "DELETE FROM hr_messages WHERE conv_id = ?", (legacy_id,)
                            )
                            self._db.conn.execute(
                                "DELETE FROM hr_conversations WHERE conv_id = ?", (legacy_id,)
                            )
                        else:
                            # Target conv row doesn't exist yet -> re-key the legacy row
                            # onto the hard key. Messages may STILL exist under conv_id
                            # (this run's write_hr_messages already wrote them, or an
                            # earlier partial state), so the move must be idempotent:
                            # OR IGNORE skips messages already present at the target, then
                            # drop the un-moved legacy duplicates. A plain UPDATE here hit
                            # UNIQUE(conv_id,sender,text,msg_time), rolled back the whole
                            # upsert, and left the legacy row to re-collide every run.
                            self._db.conn.execute(
                                "UPDATE hr_conversations SET conv_id = ?, job_id = ? WHERE conv_id = ?",
                                (conv_id, job_id, legacy_id),
                            )
                            self._db.conn.execute(
                                "UPDATE OR IGNORE hr_messages SET conv_id = ? WHERE conv_id = ?",
                                (conv_id, legacy_id),
                            )
                            self._db.conn.execute(
                                "DELETE FROM hr_messages WHERE conv_id = ?", (legacy_id,)
                            )

            row = self._db.conn.execute(
                "SELECT stage FROM hr_conversations WHERE conv_id = ?",
                (conv_id,),
            ).fetchone()
            prev_stage: Optional[str] = row[0] if row else None

            with self._db.conn:
                self._db.conn.execute(
                    """
                    INSERT INTO hr_conversations
                        (conv_id, hr_name, company, boss_conv_id, stage,
                         last_msg_preview, hr_title, job_id, last_msg_ts, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(conv_id) DO UPDATE SET
                        hr_name          = excluded.hr_name,
                        company          = excluded.company,
                        boss_conv_id     = CASE WHEN excluded.boss_conv_id != ''
                                               THEN excluded.boss_conv_id
                                               ELSE boss_conv_id END,
                        hr_title         = CASE WHEN excluded.hr_title != ''
                                               THEN excluded.hr_title
                                               ELSE hr_title END,
                        job_id           = CASE WHEN excluded.job_id != ''
                                               THEN excluded.job_id
                                               ELSE job_id END,
                        last_msg_ts      = CASE WHEN excluded.last_msg_ts > 0
                                               THEN excluded.last_msg_ts
                                               ELSE last_msg_ts END,
                        stage            = CASE
                            -- Revive a stale-closed conversation on genuine new
                            -- activity. We only reach upsert for a 'closed' row when
                            -- filter_conversations decided to PROCESS it, which for a
                            -- terminal stage means there IS new activity (unread /
                            -- changed preview / approved reply). So let the freshly
                            -- computed stage win instead of staying stuck 'closed' --
                            -- this is the "HR (or we) re-engaged -> conversation
                            -- revives" behavior. It re-closes naturally if it goes
                            -- stale (14d no activity) again.
                            WHEN stage = 'closed' AND excluded.stage != 'closed'
                                 THEN excluded.stage
                            WHEN excluded.stage = 'closed' THEN 'closed'
                            WHEN excluded.stage = 'offer'
                                 AND stage NOT IN ('closed') THEN 'offer'
                            WHEN excluded.stage = 'interview'
                                 AND stage NOT IN ('closed', 'offer') THEN 'interview'
                            WHEN excluded.stage = 'resume_sent'
                                 AND stage NOT IN ('closed', 'offer', 'interview') THEN 'resume_sent'
                            WHEN excluded.stage = 'active'
                                 AND stage IN ('new') THEN 'active'
                            ELSE stage
                        END,
                        last_msg_preview = excluded.last_msg_preview
                    """,
                    (
                        conv_id, hr_name, company, boss_conv_id, stage,
                        last_msg_preview, hr_title, job_id, last_msg_ts, now,
                    ),
                )

            new_row = self._db.conn.execute(
                "SELECT stage FROM hr_conversations WHERE conv_id = ?",
                (conv_id,),
            ).fetchone()
            new_stage: str = new_row[0] if new_row else stage
            stage_changed = prev_stage != new_stage

            return ToolResult(ok=True, data={
                "stage": new_stage,
                "prev_stage": prev_stage or "new",
                "stage_changed": stage_changed,
            })
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=str(exc))
