from tools.base import BaseTool, ToolResult
from tools.browser.helpers import _human_pause

# JS string literals for card type prefixes.
# Double-backslash produces \uXXXX JS escape sequences; no CJK bytes in this source file.
_JS_CARD_PFX = "'[\\u5361\\u7247] '"
_JS_PLACE_PFX = "'[\\u5730\\u70b9] '"

# Boss platform nudges carry the item-friend (HR) DOM class but are NOT HR chat --
# e.g. the injected "excellent competitors are applying, message them sooner" tip.
# Left as sender='hr' they pollute intent analysis and W3 reply drafts
# (analyze_hr_intent reads messages[-5:] verbatim and treats the tip as the HR's
# latest message), and render as an HR bubble instead of a centered system notice.
# Reclassify them to 'system' by text prefix (Boss truncates the rendered text, so
# match the stable leading phrase). CJK as \uXXXX escapes -- repo convention; GBK
# toolchain corrupts raw CJK bytes.
_PLATFORM_TIP_PREFIXES = (
    "\u4f18\u79c0\u7ade\u4e89\u8005\u4f1a",  # "excellent competitors..." nudge
)


def _reclassify_platform_tips(messages):
    """Retag Boss platform-nudge bubbles (mislabeled 'hr' by DOM class) as 'system'.

    Pure, in-place reclassification keyed on a known-tip text prefix. Only touches
    sender=='hr' bubbles; genuine HR cards (resume/wechat request cards) and real HR
    text are untouched.
    """
    for msg in messages:
        if msg.get("sender") != "hr":
            continue
        text = msg.get("text", "")
        if any(text.startswith(pfx) for pfx in _PLATFORM_TIP_PREFIXES):
            msg["sender"] = "system"
    return messages


class ReadMessages(BaseTool):
    name = "read_messages"
    description = "Read all message bubbles from the currently open Boss Zhipin conversation"
    input_schema = {"type": "object", "properties": {}}

    def __init__(self, browser=None):
        self._browser = browser

    def execute(self) -> ToolResult:
        if self._browser is None:
            return ToolResult(ok=False, data={"message_count": 0, "messages": []}, error="browser not initialized")
        page = self._browser
        try:
            # Boss SPA renders messages asynchronously -- poll until items appear
            _MAX_POLL = 20
            count = 0
            for _ in range(_MAX_POLL):
                _human_pause(0.5, 0.5)
                count = page.run_js("return document.querySelectorAll('.message-item').length") or 0
                if count:
                    break

            if not count:
                # An open conversation with zero message bubbles is an invalid state,
                # not a valid "empty" read: it means navigation/render failed (the click
                # never actually opened the conversation, or the SPA did not render in
                # time). Fail fast so this conversation's ReadStep is marked FAILED and
                # the W2 loop isolates the fault and moves to the next conversation,
                # instead of feeding an empty thread into intent analysis.
                return ToolResult(
                    ok=False,
                    data={"message_count": 0, "messages": []},
                    error="no message bubbles rendered after navigating into conversation",
                )

            page.run_js("var c=document.querySelector('.chat-message'); if(c) c.scrollTop=0;")
            _human_pause(0.8, 1.2)

            js = (
                "var CARD_PFX=" + _JS_CARD_PFX + ";"
                "var PLACE_PFX=" + _JS_PLACE_PFX + ";"
                "var items=document.querySelectorAll('.message-item');"
                "var result=[];"
                "items.forEach(function(el){"
                "  var cls=el.className||'';"
                "  var sender;"
                "  if(cls.indexOf('item-friend')!==-1){sender='hr';}"
                "  else if(cls.indexOf('item-myself')!==-1){sender='me';}"
                "  else if(cls.indexOf('item-system')!==-1){sender='system';}"
                "  else{return;}"
                "  var timeEl=el.querySelector('.time');"
                "  var timeStr=timeEl?timeEl.innerText.trim():'';"
                "  var text='';"
                "  var msgType='text';"
                "  var pEl=el.querySelector('p span');"
                "  if(pEl){text=pEl.innerText.trim();}"
                "  if(!text){"
                "    var ct=el.querySelector('.message-card-top-title');"
                "    if(ct){text=CARD_PFX+ct.innerText.trim();msgType='card';}"
                "  }"
                "  if(!text){"
                "    var dt=el.querySelector('.msg-dialog-title');"
                "    var dd=el.querySelector('.msg-dialog-desc');"
                "    if(dt||dd){"
                "      var p2=[];"
                "      if(dt)p2.push(dt.innerText.trim());"
                "      if(dd)p2.push(dd.innerText.trim());"
                "      text=PLACE_PFX+p2.join(' ');msgType='card';"
                "    }"
                "  }"
                "  if(!text){"
                "    var tx=el.querySelector('.text')||el.querySelector('.hyper-link');"
                "    if(tx){text=tx.innerText.trim();}"
                "  }"
                "  if(!text){return;}"
                # No timestamp filter: Boss only renders a .time on SOME bubbles (the
                # first of a time-group), so dropping HR text bubbles without a .time
                # silently loses real messages -- verified 2026-06-02 that a real
                # conversation dropped 2 of its 3 HR messages this way. Presence of
                # text (checked above) is the correct keep signal, not the timestamp.
                "  result.push({sender:sender,text:text,time:timeStr});"
                "});"
                "return result;"
            )
            raw = page.run_js(js)

            messages = raw if (raw and isinstance(raw, list)) else []
            if not messages:
                # Bubbles exist in the DOM but none parsed into a message -> also an
                # invalid state (a parser/selector mismatch, or every bubble was
                # filtered out). Treat as a failure for the same reason as above.
                return ToolResult(
                    ok=False,
                    data={"message_count": 0, "messages": []},
                    error=f"0 messages extracted from {count} message bubble(s)",
                )
            _reclassify_platform_tips(messages)
            return ToolResult(ok=True, data={"message_count": len(messages), "messages": messages})
        except Exception as exc:
            return ToolResult(ok=False, data={"message_count": 0, "messages": []}, error=str(exc))
