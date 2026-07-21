"""Unit tests for DetectResumeRequest (W2 resume-request detection, pure logic).

Key regression: a resume delivered via the card-accept flow is confirmed by a
SYSTEM notification (not a "me" text message), so already_sent must account for
system messages -- otherwise needs_resume stays True and the resume is sent a
second time. Verified against a real conversation on 2026-06-02.
"""
from tools.biz_logic.detect_resume import DetectResumeRequest


def _run(messages):
    return DetectResumeRequest().execute(messages=messages).data


def test_hr_card_request_not_yet_sent():
    d = _run([{"sender": "hr", "text": "[卡片] 我想要一份您的附件简历，您是否同意"}])
    assert d["request_type"] == "hr_card"
    assert d["already_sent"] is False
    assert d["needs_resume"] is True


def test_system_notification_marks_already_sent():
    d = _run([
        {"sender": "hr", "text": "[卡片] 我想要一份您的附件简历，您是否同意"},
        {"sender": "system", "text": "您的附件简历 余佩其_Fl... 已发送给Boss"},
    ])
    assert d["already_sent"] is True
    assert d["needs_resume"] is False  # already delivered -> do NOT re-send


def test_system_viewed_also_marks_already_sent():
    d = _run([
        {"sender": "hr", "text": "[卡片] 我想要一份您的附件简历"},
        {"sender": "system", "text": "对方已查看了您的附件简历"},
    ])
    assert d["already_sent"] is True
    assert d["needs_resume"] is False


def test_me_text_alone_does_not_mark_sent():
    # "me" claiming to have a resume is NOT proof of an attachment delivery -- only the
    # system bubble (含"附件简历") is. Without a system confirmation the HR request
    # stays actionable, so the resume can actually be sent.
    d = _run([
        {"sender": "hr", "text": "方便发个简历吗"},
        {"sender": "me", "text": "好的，这是我的简历"},
    ])
    assert d["request_type"] == "hr_text"
    assert d["already_sent"] is False
    assert d["needs_resume"] is True


def test_no_resume_request():
    d = _run([
        {"sender": "hr", "text": "你好啊，可以聊一聊"},
        {"sender": "me", "text": "好的"},
    ])
    assert d["request_type"] is None
    assert d["needs_resume"] is False
