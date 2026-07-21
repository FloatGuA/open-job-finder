from tools.base import BaseTool, ToolResult
from tools.browser.helpers import _human_pause


class AcceptWechatCard(BaseTool):
    """Click the Agree button on a Boss Zhipin 'exchange WeChat' card.

    Mirrors AcceptResumeCard but targets the WeChat-exchange card, whose DOM is:
        <div class="message-dialog-both message-card-wrap green">
          <span class="dialog-icon weixin"></span>
          <h3 class="message-card-top-title ...">我想要和您交换微信，您是否同意</h3>
          <span class="card-btn">拒绝</span><span class="card-btn">同意</span>

    Idempotent by construction: it only clicks a NON-disabled 同意 button on a
    `.dialog-icon.weixin` card. Once agreed, Boss removes/disables the buttons, so a
    re-run finds no active button and is a no-op (clicked=False). There is no
    resume-style delivered-marker to confirm on, so success = the click landed;
    the outcome (HR sending their WeChat) surfaces on the next scan.
    """

    name = "accept_wechat_card"
    description = "Click the Agree button on a Boss Zhipin exchange-WeChat card"
    input_schema = {"type": "object", "properties": {}}

    def __init__(self, browser=None):
        self._browser = browser

    def execute(self) -> ToolResult:
        if self._browser is None:
            return ToolResult(
                ok=False,
                data={"card_found": False, "clicked": False},
                error="browser not initialized",
            )
        page = self._browser
        try:
            # JS \\uXXXX in the Python literal -> \uXXXX in JS -> the 同意 button text.
            # Scan from the newest card backward: the actionable request is the latest.
            clicked = page.run_js(
                "var cards=document.querySelectorAll('.message-card-wrap');"
                "for(var i=cards.length-1;i>=0;i--){"
                "  var c=cards[i];"
                "  if(!c.querySelector('.dialog-icon.weixin'))continue;"
                "  var btns=c.querySelectorAll('.card-btn:not(.disabled)');"
                "  for(var b of btns){"
                "    if(b.textContent.trim()==='\\u540c\\u610f'){b.click();return true;}"
                "  }"
                "  return false;"  # weixin card present but no active 同意 -> already handled
                "}"
                "return false;"
            )

            if not clicked:
                return ToolResult(ok=True, data={"card_found": False, "clicked": False})

            _human_pause(1.0, 1.5)
            return ToolResult(ok=True, data={"card_found": True, "clicked": True})
        except Exception as exc:
            return ToolResult(
                ok=False,
                data={"card_found": False, "clicked": False},
                error=str(exc),
            )
