"""WeChat-id extraction: only the real number CARD counts.

Lived inline in dashboard/server.py with a comment saying it "mirrors Chat.tsx" --
two copies, no tests. Now one implementation (tools/biz_logic/wechat_id.py) that
the API computes and the frontend consumes.

The precision cases matter: a loose "any message containing 微信号" match used to
treat an HR's decline message as if it carried a WeChat id.
"""
from tools.biz_logic.wechat_id import wechat_id_from


def _hr(text):
    return {"sender": "hr", "text": text}


def test_extracts_id_from_number_card():
    assert wechat_id_from([_hr("[卡片] 王女士的微信号\nzhang_hr2024")]) == "zhang_hr2024"


def test_extracts_when_id_follows_a_colon():
    assert wechat_id_from([_hr("[卡片] 微信号：hr_abc123")]) == "hr_abc123"


def test_sentence_merely_mentioning_wechat_is_not_an_id():
    """An HR decline that happens to say 微信号 must not be read as contact details."""
    assert wechat_id_from([_hr("[卡片] 我不方便给微信号，抱歉")]) is None


def test_plain_message_without_card_prefix_is_ignored():
    """Only the actual card counts -- ordinary chat text is not a card."""
    assert wechat_id_from([_hr("我的微信号 zhang_hr2024")]) is None


def test_our_own_messages_are_ignored():
    assert wechat_id_from([{"sender": "me", "text": "[卡片] 微信号 my_own_id"}]) is None


def test_returns_the_first_card_when_several_exist():
    msgs = [
        _hr("[卡片] 微信号 first_id_here"),
        _hr("[卡片] 微信号 second_id_x"),
    ]
    assert wechat_id_from(msgs) == "first_id_here"


def test_rejects_tokens_that_do_not_look_like_ids():
    # too short, and CJK is never part of a WeChat id
    assert wechat_id_from([_hr("[卡片] 微信号 ab")]) is None
    assert wechat_id_from([_hr("[卡片] 微信号 微信")]) is None


def test_empty_and_missing_inputs():
    assert wechat_id_from([]) is None
    assert wechat_id_from(None) is None
    assert wechat_id_from([{"sender": "hr"}]) is None
