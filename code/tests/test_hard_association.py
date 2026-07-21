"""Tests for the W1↔W2 hard-association upgrade (job_id as the shared key).

Covers: derive_conv_id identity rule, upsert persisting job_id/last_msg_ts,
the conv_id re-key migration (+ hr_messages cascade), sync joining on job_id
(with hr_name+company soft fallback), filter dirty-detection by lastTS, and the
W2→W1 backfill of missing applications.
"""
import pytest

from services.tracker import ApplicationTracker
from tools.biz_logic.conv_id import derive_conv_id
from tools.biz_logic.filter_conversations import FilterConversations
from tools.db.w2.upsert_hr_conversation import UpsertHRConversation
from tools.db.w2.sync_application_status import SyncApplicationStatusFromConversations
from tools.db.w2.backfill_application_from_conversation import BackfillApplicationFromConversation


@pytest.fixture
def tracker(tmp_path):
    t = ApplicationTracker(str(tmp_path / "test.db"))
    yield t
    t.close()


def _seed_app(tracker, job_id, *, hr_name="", company="C", status="APPLIED"):
    with tracker.conn:
        tracker.conn.execute(
            "INSERT INTO applications (job_id, title, company, hr_name, url, status, created_at) "
            "VALUES (?, '', ?, ?, '', ?, '2026-01-01')",
            (job_id, company, hr_name, status),
        )


def _seed_conv(tracker, conv_id, *, job_id=None, hr_name="王女士", company="C",
               stage="new", intent=None):
    with tracker.conn:
        tracker.conn.execute(
            "INSERT INTO hr_conversations (conv_id, hr_name, company, job_id, stage, intent, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, '2026-01-01')",
            (conv_id, hr_name, company, job_id, stage, intent),
        )


# ── derive_conv_id ───────────────────────────────────────────────────────────

def test_derive_conv_id_prefers_job_id():
    assert derive_conv_id("ab5cd168dcb8e1631Xx609-8EFRT", "王女士", "公司") == "ab5cd168dcb8e1631Xx609-8EFRT"


def test_derive_conv_id_falls_back_to_sha256():
    cid = derive_conv_id("", "王女士", "公司")
    assert len(cid) == 12
    assert cid == derive_conv_id("", "王女士", "公司")  # stable
    assert cid != derive_conv_id("", "李先生", "公司")  # distinct


# ── upsert persists job_id + last_msg_ts ─────────────────────────────────────

def test_upsert_persists_job_id_and_ts(tracker):
    res = UpsertHRConversation(db=tracker).execute(
        conv_id="JOBX", hr_name="王女士", company="C",
        job_id="JOBX", last_msg_ts=1783261490633,
    )
    assert res.ok, res.error
    conv = tracker.get_hr_conversation("JOBX")
    assert conv.job_id == "JOBX"
    row = tracker.conn.execute("SELECT last_msg_ts FROM hr_conversations WHERE conv_id='JOBX'").fetchone()
    assert row[0] == 1783261490633


def test_upsert_empty_job_id_and_zero_ts_do_not_wipe(tracker):
    UpsertHRConversation(db=tracker).execute(
        conv_id="c1", hr_name="王女士", company="C", job_id="JOBX", last_msg_ts=100)
    UpsertHRConversation(db=tracker).execute(
        conv_id="c1", hr_name="王女士", company="C", job_id="", last_msg_ts=0)
    row = tracker.conn.execute("SELECT job_id, last_msg_ts FROM hr_conversations WHERE conv_id='c1'").fetchone()
    assert row[0] == "JOBX"
    assert row[1] == 100


# ── conv_id re-key migration ─────────────────────────────────────────────────

def test_rekey_migration_moves_conv_id_to_job_id_and_cascades(tmp_path):
    db = str(tmp_path / "rekey.db")
    t1 = ApplicationTracker(db)
    _seed_conv(t1, "old_sha_key", job_id="JOBX", stage="active")
    with t1.conn:
        t1.conn.execute(
            "INSERT INTO hr_messages (conv_id, sender, text, created_at) "
            "VALUES ('old_sha_key', 'hr', 'hello', '2026-01-01')"
        )
    t1.close()

    # Re-opening re-runs _init_db -> the re-key migration.
    t2 = ApplicationTracker(db)
    assert t2.get_hr_conversation("JOBX") is not None
    assert t2.get_hr_conversation("old_sha_key") is None
    msg = t2.conn.execute("SELECT conv_id FROM hr_messages WHERE text='hello'").fetchone()
    assert msg[0] == "JOBX"
    t2.close()


# ── sync joins on job_id, with soft fallback ─────────────────────────────────

def test_rekey_migration_merges_preupgrade_duplicate(tmp_path):
    # Legacy data: the SAME conversation exists twice — a hard-keyed row
    # (conv_id==job_id) AND a redundant soft-keyed row that also carries the job_id
    # (from the old onboarding flow). The re-key migration must merge the duplicate
    # (move messages, drop the soft row), not skip it and leave a duplicate.
    db = str(tmp_path / "dup.db")
    t1 = ApplicationTracker(db)
    _seed_conv(t1, "JOBX", job_id="JOBX", hr_name="王女士", company="Anker", stage="active")
    _seed_conv(t1, "sha_dup", job_id="JOBX", hr_name="王女士", company="Anker", stage="closed")
    with t1.conn:
        t1.conn.execute("INSERT INTO hr_messages (conv_id, sender, text, created_at) "
                        "VALUES ('sha_dup', 'hr', '重复行消息', '2026-01-01')")
    t1.close()

    t2 = ApplicationTracker(db)
    assert t2.get_hr_conversation("sha_dup") is None       # duplicate removed
    assert t2.get_hr_conversation("JOBX") is not None       # hard row kept
    msg = t2.conn.execute("SELECT conv_id FROM hr_messages WHERE text='重复行消息'").fetchone()
    assert msg[0] == "JOBX"                                  # message merged onto hard key
    t2.close()


def test_sync_hard_join_on_job_id(tracker):
    # hr_name empty on the application (the historical death-link case) — the
    # job_id join must still connect them.
    _seed_app(tracker, "JOBX", hr_name="", company="C", status="APPLIED")
    _seed_conv(tracker, "JOBX", job_id="JOBX", stage="interview")
    SyncApplicationStatusFromConversations(db=tracker).execute()
    app = tracker.get_application("JOBX")
    assert app.status == "INTERVIEWING"


def test_sync_soft_fallback_when_conv_has_no_job_id(tracker):
    _seed_app(tracker, "JOBY", hr_name="王女士", company="顺丰", status="APPLIED")
    _seed_conv(tracker, "sha_key", job_id=None, hr_name="王女士", company="顺丰", stage="offer")
    SyncApplicationStatusFromConversations(db=tracker).execute()
    app = tracker.get_application("JOBY")
    assert app.status == "OFFER"


# ── filter dirty detection by lastTS ─────────────────────────────────────────

def test_filter_newer_ts_triggers_process():
    """A message newer than the analyzed watermark (last_analyzed_ts) is processed."""
    res = FilterConversations().execute(
        current_convs=[{"conv_id": "JOBX", "last_msg_ts": 200, "last_msg_preview": "same"}],
        stored_states={"JOBX": {"last_msg_ts": 100, "last_msg_preview": "same", "stage": "active",
                                "intent": "general", "last_analyzed_ts": 100}},
        approved_reply_ids=[],
    )
    decisions = {d["conv_id"]: d for d in res.data["decisions"]}
    assert decisions["JOBX"]["action"] == "process"
    assert decisions["JOBX"]["reason"] == "unanalyzed"


def test_update_hr_analysis_advances_last_analyzed_ts(tracker):
    """The tool advances last_analyzed_ts on success (MAX-guarded, NULL = untouched)."""
    from tools.db.w2.update_hr_analysis import UpdateHRAnalysis
    _seed_conv(tracker, "c1", stage="active")
    tool = UpdateHRAnalysis(db=tracker)

    tool.execute(conv_id="c1", intent="general", last_analyzed_ts=500)
    assert tracker.conn.execute("SELECT last_analyzed_ts FROM hr_conversations WHERE conv_id='c1'").fetchone()[0] == 500
    # MAX guard: a lower ts must not regress the watermark
    tool.execute(conv_id="c1", intent="general", last_analyzed_ts=300)
    assert tracker.conn.execute("SELECT last_analyzed_ts FROM hr_conversations WHERE conv_id='c1'").fetchone()[0] == 500
    # None leaves the watermark untouched (still updates intent)
    tool.execute(conv_id="c1", intent="rejection")
    row = tracker.conn.execute("SELECT last_analyzed_ts, intent FROM hr_conversations WHERE conv_id='c1'").fetchone()
    assert row[0] == 500 and row[1] == "rejection"


def test_migration_backfills_last_analyzed_ts(tmp_path):
    """Adding last_analyzed_ts backfills already-analyzed rows (non-empty intent) to
    last_msg_ts; empty-intent rows stay 0 so they are (re)analyzed, not masked."""
    import sqlite3
    db = str(tmp_path / "old.db")
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE hr_conversations (conv_id TEXT PRIMARY KEY, hr_name TEXT NOT NULL, "
        "company TEXT NOT NULL, job_id TEXT, stage TEXT NOT NULL DEFAULT 'new', "
        "boss_conv_id TEXT DEFAULT '', intent TEXT, reply_status TEXT, reply_text TEXT, "
        "last_msg_preview TEXT DEFAULT '', hr_title TEXT DEFAULT '', wechat_dismissed INTEGER DEFAULT 0, "
        "last_msg_ts INTEGER DEFAULT 0, locate_fail_count INTEGER DEFAULT 0, created_at TEXT NOT NULL)"
    )
    con.execute("INSERT INTO hr_conversations (conv_id,hr_name,company,intent,last_msg_ts,created_at) "
                "VALUES ('a','H','C','general',500,'2026-01-01')")
    con.execute("INSERT INTO hr_conversations (conv_id,hr_name,company,intent,last_msg_ts,created_at) "
                "VALUES ('b','H','C','',700,'2026-01-01')")
    con.commit(); con.close()

    t = ApplicationTracker(db)
    rows = {r[0]: r[1] for r in t.conn.execute("SELECT conv_id, last_analyzed_ts FROM hr_conversations")}
    t.close()
    assert rows["a"] == 500   # analyzed -> watermark backfilled to last_msg_ts
    assert rows["b"] == 0     # empty intent -> stays 0 (genuinely needs analysis)


def test_filter_same_ts_no_change():
    """conv_ts == last_analyzed_ts (already analyzed up to this message) -> skip."""
    res = FilterConversations().execute(
        current_convs=[{"conv_id": "JOBX", "last_msg_ts": 100, "last_msg_preview": "same"}],
        stored_states={"JOBX": {"last_msg_ts": 100, "last_msg_preview": "same", "stage": "active",
                                "intent": "general", "last_analyzed_ts": 100}},
        approved_reply_ids=[],
    )
    decisions = {d["conv_id"]: d for d in res.data["decisions"]}
    assert decisions["JOBX"]["action"] == "skip"


def test_filter_read_ok_analyze_failed_is_retried():
    """The decoupling fix: a round where read advanced last_msg_ts but analyze failed
    (last_analyzed_ts stayed behind) must be retried -- conv_ts > last_analyzed_ts even
    though last_msg_ts already equals conv_ts."""
    res = FilterConversations().execute(
        current_convs=[{"conv_id": "JOBX", "last_msg_ts": 200, "last_msg_preview": "same"}],
        stored_states={"JOBX": {"last_msg_ts": 200, "last_msg_preview": "same", "stage": "active",
                                "intent": "general", "last_analyzed_ts": 100}},
        approved_reply_ids=[],
    )
    decisions = {d["conv_id"]: d for d in res.data["decisions"]}
    assert decisions["JOBX"]["action"] == "process"
    assert decisions["JOBX"]["reason"] == "unanalyzed"


# ── W2→W1 backfill ───────────────────────────────────────────────────────────

def test_backfill_creates_application_for_orphan_conversation(tracker):
    _seed_conv(tracker, "JOBX", job_id="JOBX", hr_name="金伟", company="亿检生物", stage="active")
    res = BackfillApplicationFromConversation(db=tracker).execute()
    assert res.ok, res.error
    assert res.data["backfilled_count"] == 1
    app = tracker.get_application("JOBX")
    assert app is not None
    assert app.status == "APPLIED"
    assert app.company == "亿检生物"
    assert app.url == "https://www.zhipin.com/job_detail/JOBX.html"


def test_upsert_absorbs_legacy_soft_keyed_row(tracker):
    # A conversation first seen pre-upgrade under the sha256 soft key (job_id NULL,
    # closed, with a historical message). Re-scanning it WITH a job_id must absorb
    # that row (re-key + cascade messages + revive), not create a duplicate.
    _seed_conv(tracker, "sha_old", job_id=None, hr_name="王女士", company="华为", stage="closed")
    with tracker.conn:
        tracker.conn.execute(
            "INSERT INTO hr_messages (conv_id, sender, text, created_at) "
            "VALUES ('sha_old', 'hr', '历史消息', '2026-01-01')"
        )
    before = tracker.conn.execute("SELECT COUNT(*) FROM hr_conversations").fetchone()[0]

    UpsertHRConversation(db=tracker).execute(
        conv_id="JOBX", hr_name="王女士", company="华为",
        job_id="JOBX", stage="active", last_msg_ts=500,
    )

    after = tracker.conn.execute("SELECT COUNT(*) FROM hr_conversations").fetchone()[0]
    assert after == before  # absorbed, not duplicated
    assert tracker.get_hr_conversation("sha_old") is None
    conv = tracker.get_hr_conversation("JOBX")
    assert conv is not None and conv.job_id == "JOBX"
    assert conv.stage == "active"  # revived from closed on re-engagement
    msg = tracker.conn.execute("SELECT conv_id FROM hr_messages WHERE text='历史消息'").fetchone()
    assert msg[0] == "JOBX"  # history cascaded onto the hard key


def test_upsert_absorb_merges_when_both_rows_exist(tracker):
    # Legacy soft row AND a hard-keyed row both exist (e.g. the duplicate already got
    # created once). Absorbing drops the orphan and merges its messages.
    _seed_conv(tracker, "sha_old", job_id=None, hr_name="王女士", company="华为", stage="closed")
    _seed_conv(tracker, "JOBX", job_id="JOBX", hr_name="王女士", company="华为", stage="active")
    with tracker.conn:
        tracker.conn.execute("INSERT INTO hr_messages (conv_id, sender, text, created_at) "
                             "VALUES ('sha_old', 'hr', '旧消息', '2026-01-01')")

    UpsertHRConversation(db=tracker).execute(
        conv_id="JOBX", hr_name="王女士", company="华为", job_id="JOBX", stage="active")

    assert tracker.get_hr_conversation("sha_old") is None
    assert tracker.get_hr_conversation("JOBX") is not None
    msg = tracker.conn.execute("SELECT conv_id FROM hr_messages WHERE text='旧消息'").fetchone()
    assert msg[0] == "JOBX"


def test_upsert_absorb_idempotent_when_target_message_already_present(tracker):
    # Regression (W2 "一直报错" at upsert_hr_conversation): else branch (no hard-keyed
    # conv row yet) but THIS run's write_hr_messages already wrote the message under
    # conv_id=job_id. The legacy-message move used a plain UPDATE that hit
    # UNIQUE(conv_id,sender,text[,msg_time]), rolled back the whole upsert, and left
    # the legacy row to re-collide on every subsequent W2 run.
    _seed_conv(tracker, "sha_old", job_id=None, hr_name="王女士", company="华为", stage="closed")
    with tracker.conn:
        tracker.conn.execute("INSERT INTO hr_messages (conv_id, sender, text, created_at) "
                             "VALUES ('sha_old', 'hr', 'dup', '2026-01-01')")
        # same message already at the hard key (write_hr_messages ran first this run)
        tracker.conn.execute("INSERT INTO hr_messages (conv_id, sender, text, created_at) "
                             "VALUES ('JOBX', 'hr', 'dup', '2026-01-01')")

    res = UpsertHRConversation(db=tracker).execute(
        conv_id="JOBX", hr_name="王女士", company="华为", job_id="JOBX", stage="active")

    assert res.ok is True  # no UNIQUE-constraint failure / rollback
    assert tracker.get_hr_conversation("sha_old") is None  # legacy absorbed, not stuck
    assert tracker.get_hr_conversation("JOBX") is not None
    rows = tracker.conn.execute("SELECT conv_id FROM hr_messages WHERE text='dup'").fetchall()
    assert [r[0] for r in rows] == ["JOBX"]  # single copy under the hard key


def test_backfill_skips_existing_and_jobless(tracker):
    _seed_app(tracker, "JOBX", company="亿检生物")
    _seed_conv(tracker, "JOBX", job_id="JOBX", company="亿检生物")      # already has app
    _seed_conv(tracker, "sha_key", job_id=None, company="无job")        # no job_id
    res = BackfillApplicationFromConversation(db=tracker).execute()
    assert res.data["backfilled_count"] == 0
