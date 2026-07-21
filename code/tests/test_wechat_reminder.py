"""Tests for the go-add-WeChat reminder backend (Dashboard card + 待加微信 filter).

Covers: extracting HR's WeChat id from the number card, the wechat_pending flag in
the serialized conversation, and that dismiss_wechat persists + flips it off.
"""
import pytest

from dashboard.server import _serialize_conversation, _wechat_id_from
from services.tracker import ApplicationTracker

# `[卡片] 余英奇的微信号\nASDQWERPP` -- the number card read_messages captures.
_NUMBER_CARD = "[卡片] 余英奇的微信号\nASDQWERPP"
_REQUEST_CARD = "[卡片] 我想要和您交换微信，您是否同意"


@pytest.fixture
def tracker(tmp_path):
    t = ApplicationTracker(str(tmp_path / "test.db"))
    yield t
    t.close()


def test_extract_wechat_id_from_number_card():
    assert _wechat_id_from([{"sender": "hr", "text": _NUMBER_CARD}]) == "ASDQWERPP"


def test_no_wechat_id_from_request_card_only():
    # The exchange-request card carries no id; only the number card does.
    assert _wechat_id_from([{"sender": "hr", "text": _REQUEST_CARD}]) is None


def test_my_own_wechat_text_is_not_hr_id():
    # A 'me' bubble mentioning 微信号 must not be mistaken for HR's id.
    assert _wechat_id_from([{"sender": "me", "text": "我的微信号 xyz"}]) is None


def test_plain_hr_text_mentioning_wechat_is_not_an_id():
    # Real false positive seen live: an HR decline sentence containing 微信号 but
    # NOT a card (no [卡片] prefix) -> must not be treated as an id.
    decline = "微信号不用了，我发您详细情况，您了解完再决定是否参与"
    assert _wechat_id_from([{"sender": "hr", "text": decline}]) is None


def test_card_with_sentence_id_is_rejected():
    # Even inside a card, a non-id-looking token (CJK sentence) is not an id.
    assert _wechat_id_from([{"sender": "hr", "text": "[卡片] 某某的微信号\n你好呀"}]) is None


def _make_conv(tracker):
    from tools.db.w2.upsert_hr_conversation import UpsertHRConversation
    UpsertHRConversation(db=tracker).execute(
        conv_id="c1", hr_name="余英奇", company="深圳", stage="active",
    )


def test_wechat_pending_true_then_dismiss(tracker):
    _make_conv(tracker)
    tracker.insert_hr_messages("c1", [{"sender": "hr", "text": _NUMBER_CARD}])
    conv = tracker.get_hr_conversation("c1")
    msgs = tracker.get_hr_messages("c1")

    ser = _serialize_conversation(conv, msgs, "")
    assert ser["wechat_pending"] is True
    assert ser["wechat_id"] == "ASDQWERPP"
    assert ser["wechat_dismissed"] is False

    # Dismiss -> persisted -> pending flips off, id still available for reference.
    tracker.dismiss_wechat("c1")
    conv2 = tracker.get_hr_conversation("c1")
    assert conv2.wechat_dismissed is True
    ser2 = _serialize_conversation(conv2, msgs, "")
    assert ser2["wechat_pending"] is False
    assert ser2["wechat_dismissed"] is True
