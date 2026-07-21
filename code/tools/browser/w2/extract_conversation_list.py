from tools.base import BaseTool, ToolResult
from tools.biz_logic.conv_id import derive_conv_id

# Primary source: drain the getGeekFriendList responses captured by the XHR hook
# (services/browser_context._XHR_HOOK_JS). One API response carries the whole
# conversation list with the hard-association key encryptJobId, the HR name,
# company, real millisecond lastTS, and unread count — everything the DOM used to
# give plus job_id and a diff-able timestamp. Scrolling triggers more
# getGeekFriendList XHRs (pagination); we accumulate across every captured
# response and dedup by encryptBossId so a full scroll-through builds the whole
# list. Later responses win (freshest last message / unread).
_LIST_JS = r"""
return (function(){
  var log = window.__xhrLog || [];
  var byKey = {};
  for (var i = 0; i < log.length; i++){
    var e = log[i];
    if (!e || !e.url || e.url.indexOf('getGeekFriendList') === -1) continue;
    var data;
    try { data = JSON.parse(e.body); } catch(err) { continue; }
    var zp = (data && data.zpData) ? data.zpData : data;
    var result = zp && (zp.result || zp.friendList || zp.list);
    if (!result || !result.length) continue;
    for (var j = 0; j < result.length; j++){
      var it = result[j];
      if (!it) continue;
      var key = it.encryptBossId || it.encryptJobId || ((it.name || '') + '|' + (it.brandName || ''));
      byKey[key] = it;
    }
  }
  var out = [];
  for (var k in byKey){ if (byKey.hasOwnProperty(k)){
    var it = byKey[k];
    var last = it.lastMessageInfo || {};
    out.push({
      encryptJobId: it.encryptJobId || '',
      name: it.name || '',
      brandName: it.brandName || '',
      encryptBossId: it.encryptBossId || '',
      lastMsg: last.showText || it.lastMsg || '',
      lastTS: it.lastTS || last.msgTime || 0,
      unreadMsgCount: it.unreadMsgCount || 0,
      securityId: it.securityId || ''
    });
  }}
  return out;
})();
"""

# Fallback: the legacy DOM scrape. Used only when the XHR log is empty (hook
# injection failed, or we're not on the chat page yet). It cannot supply job_id
# or a real timestamp, so conversations it yields fall back to the sha256 soft
# key — a graceful degrade rather than a silent under-read.
_DOM_JS = r"""
var items = document.querySelectorAll('.friend-content-warp');
if (!items.length) items = document.querySelectorAll('li[role="listitem"]');
var result = [];
items.forEach(function(item) {
    var nameEl = item.querySelector('.name-text');
    var hr_name = nameEl ? nameEl.textContent.trim() : '';
    var company = '';
    var nameBox = item.querySelector('.name-box');
    if (nameBox) {
        var spans = nameBox.querySelectorAll('span');
        if (spans.length > 1) company = spans[1].textContent.trim();
    }
    if (!company) {
        var compEl = item.querySelector('.company-name') || item.querySelector('.name');
        if (compEl) company = compEl.textContent.trim();
    }
    var hr_title = '';
    var titleSelectors = ['.job-name', '.chat-job', '.info-tag', '.job-title', '.chat-role'];
    for (var t = 0; t < titleSelectors.length; t++) {
        var tel = item.querySelector(titleSelectors[t]);
        if (tel && tel.textContent.trim()) { hr_title = tel.textContent.trim(); break; }
    }
    if (!hr_title && nameBox) {
        var spans3 = nameBox.querySelectorAll('span');
        if (spans3.length > 2) hr_title = spans3[2].textContent.trim();
    }
    var boss_conv_id = '';
    var convEl = item.querySelector('.friend-content');
    if (convEl) boss_conv_id = convEl.getAttribute('d-c') || '';
    var msgEl = item.querySelector('.last-msg-text') || item.querySelector('.last-msg');
    var last_msg_preview = msgEl ? msgEl.textContent.trim() : '';
    var unreadSels = ['.unread-count', '.badge-num', '.num', '[class*="unread"]'];
    var has_unread = false;
    for (var u = 0; u < unreadSels.length; u++) {
        var uel = item.querySelector(unreadSels[u]);
        if (uel && uel.textContent.trim() && uel.textContent.trim() !== '0') { has_unread = true; break; }
    }
    result.push({
        name: hr_name, hr_title: hr_title, brandName: company,
        encryptBossId: boss_conv_id, lastMsg: last_msg_preview, has_unread: has_unread,
    });
});
return result;
"""


class ExtractConversationList(BaseTool):
    name = "extract_conversation_list"
    description = "Extract the visible conversation list from the Boss chat page (getGeekFriendList API, DOM fallback)"
    input_schema = {"type": "object", "properties": {}}

    def __init__(self, browser=None):
        self._browser = browser

    def execute(self) -> ToolResult:
        if self._browser is None:
            return ToolResult(ok=False, data={}, error="browser not initialized")
        page = self._browser
        try:
            items_data = page.run_js(_LIST_JS)
            if not isinstance(items_data, list):
                items_data = []

            source = "api"
            if not items_data:
                dom = page.run_js(_DOM_JS)
                items_data = dom if isinstance(dom, list) else []
                source = "dom"

            conversations = []
            for item in items_data:
                job_id = item.get("encryptJobId", "") or ""
                hr_name = item.get("name", "") or ""
                company = item.get("brandName", "") or ""
                conversations.append({
                    "conv_id": derive_conv_id(job_id, hr_name, company),
                    "job_id": job_id,
                    "hr_name": hr_name,
                    "hr_title": item.get("hr_title", ""),
                    "company": company,
                    "boss_conv_id": item.get("encryptBossId", "") or "",
                    "last_msg_preview": item.get("lastMsg", "") or "",
                    "last_msg_ts": int(item.get("lastTS", 0) or 0),
                    "has_unread": bool(item.get("unreadMsgCount") or item.get("has_unread", False)),
                })

            return ToolResult(ok=True, data={
                "item_count": len(conversations),
                "items": conversations,
                "source": source,
            })
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=str(exc))
