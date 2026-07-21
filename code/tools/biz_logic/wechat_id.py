"""Extract an HR's WeChat id from the exchange CARD in a conversation.

Deterministic text parsing, so it lives here rather than inline in an endpoint:
Boss changes its card wording from time to time, and when it does there must be
exactly one place to update. This logic previously sat in dashboard/server.py with
a comment saying it "mirrors Chat.tsx" -- the frontend held a second copy and the
two could silently disagree (one side showing 待加微信, the other not). The
frontend now consumes the wechat_id the API already computes with this function.
"""
import re

CARD_PREFIX = "[卡片]"
WECHAT_NUMBER_MARKER = "微信号"

# A real WeChat id / phone: alphanumeric (+ _ / -), no CJK, no spaces. This rejects
# plain HR text that merely mentions 微信号 in a sentence (e.g. a decline message),
# which the loose "any message containing 微信号" match wrongly treated as an id.
WECHAT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{4,29}$")


def wechat_id_from(messages: list) -> str | None:
    """Return the HR's WeChat id from the number CARD, or None.

    Only the actual card counts (text starts with `[卡片]` AND contains 微信号), and
    the extracted token must look like an id/phone -- a sentence mentioning 微信号 is
    not one. Only HR-sent messages are considered.
    """
    for m in messages or []:
        if m.get("sender") != "hr":
            continue
        text = m.get("text", "") or ""
        if not text.startswith(CARD_PREFIX) or WECHAT_NUMBER_MARKER not in text:
            continue
        after = text.split(WECHAT_NUMBER_MARKER, 1)[-1].strip(" :：。\n\t")
        token = after.split()[0] if after.split() else ""
        if WECHAT_ID_RE.match(token):
            return token
    return None
