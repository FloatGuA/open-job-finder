import time

from tools.base import BaseTool, ToolResult
from tools.biz_logic.decode_salary import decode_boss_numbers
from tools.browser.helpers import _ele_any

_JD_SELECTORS = [
    ".job-detail-section",
    ".job-sec-text",
    ".job-sec-inner",
    ".job-sec",
    ".detail-content",
    ".job-detail-content",
    ".job-detail-box",
    ".desc-content",
    ".text-desc",
    ".job-description",
    "[class*='job-sec']",
    "[class*='job-detail']",
    "[class*='detail-content']",
    "[class*='job-desc']",
]

_SALARY_SELECTORS = [".job-salary", ".salary", ".red", '[class*="salary"]']

# HR name lives in the detail panel's boss card: div.job-boss-info h2.name (verified
# 2026-07-05 against the live W1 panel). The h2.name innerText also contains an
# activity suffix ("刚刚活跃" / "N天前活跃"), so a plain read yields "王美雪 刚刚活跃".
# The suffix sits in a child span whose class varies across panel variants (the old
# code only stripped span.boss-active-time by name, so a different variant leaked
# "王女士\n刚刚活跃" into applications.hr_name — 2026-07-06). Robust strip: drop ALL
# child spans (the bare name is a direct text node, never in a span) AND take the
# first line — either mechanism alone handles a variant; together they cover both.
# Result matches W2's bare 2-3 char conversation hr_name format.
_HR_NAME_JS = """
return (function(){
  var h = document.querySelector('.job-boss-info h2.name')
       || document.querySelector('.job-boss-info .name')
       || document.querySelector('.boss-info .name');
  if(!h) return '';
  var clone = h.cloneNode(true);
  var spans = clone.querySelectorAll('span');
  for(var i=0;i<spans.length;i++){ if(spans[i].parentNode) spans[i].parentNode.removeChild(spans[i]); }
  var name = (clone.innerText || clone.textContent || '').trim();
  return name.split('\\n')[0].trim();
})();
"""

# JS fallback: try known selectors then viewport-right scan for the largest text block.
_JD_FALLBACK_JS = """
(function() {
    var known = [
        '.job-detail-section', '.job-sec-text', '.job-sec-inner', '.job-sec',
        '.detail-content', '.job-detail-content', '.job-detail-box',
        '.desc-content', '.text-desc',
        '[class*="job-sec"]', '[class*="job-detail"]',
        '[class*="detail-content"]', '[class*="job-desc"]', '[class*="desc"]'
    ];
    for (var i = 0; i < known.length; i++) {
        var el = document.querySelector(known[i]);
        if (el && el.innerText && el.innerText.trim().length > 50)
            return {found: known[i], text: el.innerText.trim()};
    }
    var half = window.innerWidth * 0.45;
    var best = {len: 0, text: ''};
    var els = document.querySelectorAll('div, section, article, p');
    for (var j = 0; j < els.length; j++) {
        var el = els[j];
        var r = el.getBoundingClientRect();
        if (r.left < half) continue;
        if (r.width < 100 || r.height < 30) continue;
        var t = el.innerText ? el.innerText.trim() : '';
        if (t.length > best.len && t.length > 50 && t.length < 50000) {
            best = {len: t.length, text: t};
        }
    }
    if (best.text) return {found: 'viewport-right', text: best.text};
    return {found: null, text: ''};
})()
"""


_JD_MIN_CONTENT_LEN = 20


class ReadPanelJD(BaseTool):
    name = "read_panel_jd"
    description = "Read JD text and raw salary string from the currently open job detail panel"
    input_schema = {
        "type": "object",
        "properties": {
            "matched_selector": {"type": ["string", "null"]},
        },
    }

    def __init__(self, browser=None):
        self._browser = browser

    def execute(self, matched_selector: str = None) -> ToolResult:
        if self._browser is None:
            return ToolResult(ok=False, data={}, error="browser not initialized")
        page = self._browser
        try:
            jd_text = ""

            # Try the previously matched selector first to avoid re-scanning the full list
            if matched_selector:
                try:
                    el = page.ele(matched_selector, timeout=3)
                    if el:
                        jd_text = (el.text or "").strip()
                except Exception:
                    pass

            if not jd_text:
                jd_el = _ele_any(page, _JD_SELECTORS, timeout=3)
                if jd_el:
                    jd_text = jd_el.text.strip()

            if not jd_text:
                js_result = page.run_js(_JD_FALLBACK_JS)
                if isinstance(js_result, dict):
                    jd_text = (js_result.get("text") or "").strip()

            if len(jd_text) < _JD_MIN_CONTENT_LEN:
                return ToolResult(ok=False, data={}, error="jd_empty")

            salary_raw = ""
            sal_el = _ele_any(page, _SALARY_SELECTORS, timeout=0)
            if sal_el:
                salary_raw = decode_boss_numbers(sal_el.text.strip())

            # The boss card (job-boss-info) renders async, LATER than the JD body — a
            # timeout=0 read caught an empty node (2026-07-04 bug: 1116 reads all "").
            # Poll via run_js: document.querySelector reliably matches the compound
            # '.job-boss-info h2.name', whereas DrissionPage .ele() with that selector
            # did NOT — so the earlier _ele_any wait-gate never fired and hr_name stayed
            # "" even in real runs. _HR_NAME_JS strips the boss-active-time span for the
            # bare name (matches W2's conversation hr_name format).
            hr_name = ""
            for _ in range(5):
                try:
                    hr_name = (page.run_js(_HR_NAME_JS) or "").strip()
                except Exception:
                    hr_name = ""
                if hr_name:
                    break
                time.sleep(0.4)

            # jd_text excluded from data (too large); salary_raw and hr_name recorded for tracing
            return ToolResult(ok=True, data={
                "salary_raw": salary_raw,
                "hr_name": hr_name,
                "jd_text": jd_text,
            })
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=str(exc))
