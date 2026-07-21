"""Unit tests for record_locate_attempt (W3 give-up-after-N-locate-misses)."""
from services.tracker import ApplicationTracker
from tools.db.w2.record_locate_attempt import RecordLocateAttempt


def _tracker(tmp_path):
    return ApplicationTracker(db_path=str(tmp_path / "jobs.db"))


def _add_conv(t, conv_id, reply_status="approved"):
    with t.conn:
        t.conn.execute(
            "INSERT INTO hr_conversations (conv_id, hr_name, company, reply_status, reply_text, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (conv_id, "HR", "Co", reply_status, "hello", "2026-01-01T00:00:00Z"),
        )


def test_reset_on_locate_success(tmp_path):
    t = _tracker(tmp_path)
    _add_conv(t, "c1")
    tool = RecordLocateAttempt(db=t)
    assert tool.execute(conv_id="c1", located=False).data["count"] == 1
    assert tool.execute(conv_id="c1", located=False).data["count"] == 2
    r = tool.execute(conv_id="c1", located=True)
    assert r.data == {"count": 0, "given_up": False}
    row = t.conn.execute("SELECT reply_status FROM hr_conversations WHERE conv_id='c1'").fetchone()
    assert row[0] == "approved"  # still queued
    t.close()


def test_gives_up_at_threshold(tmp_path):
    t = _tracker(tmp_path)
    _add_conv(t, "c1")
    tool = RecordLocateAttempt(db=t)
    assert tool.execute(conv_id="c1", located=False).data["given_up"] is False  # 1
    assert tool.execute(conv_id="c1", located=False).data["given_up"] is False  # 2
    r = tool.execute(conv_id="c1", located=False)  # 3 -> give up
    assert r.data["count"] == 3 and r.data["given_up"] is True
    row = t.conn.execute("SELECT reply_status, reply_text FROM hr_conversations WHERE conv_id='c1'").fetchone()
    assert row[0] == "dismissed" and row[1] == ""
    t.close()


def test_custom_threshold(tmp_path):
    t = _tracker(tmp_path)
    _add_conv(t, "c1")
    tool = RecordLocateAttempt(db=t)
    assert tool.execute(conv_id="c1", located=False, threshold=2).data["given_up"] is False  # 1
    assert tool.execute(conv_id="c1", located=False, threshold=2).data["given_up"] is True   # 2
    assert t.conn.execute("SELECT reply_status FROM hr_conversations WHERE conv_id='c1'").fetchone()[0] == "dismissed"
    t.close()


def test_terminal_reply_status_untouched(tmp_path):
    # A 'sent' reply must not be flipped to 'dismissed' even past the threshold.
    t = _tracker(tmp_path)
    _add_conv(t, "c1", reply_status="sent")
    tool = RecordLocateAttempt(db=t)
    for _ in range(4):
        tool.execute(conv_id="c1", located=False)
    assert t.conn.execute("SELECT reply_status FROM hr_conversations WHERE conv_id='c1'").fetchone()[0] == "sent"
    t.close()
