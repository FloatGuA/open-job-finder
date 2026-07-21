from tools.base import BaseTool, ToolResult
from tools.biz_logic.decode_salary import decode_boss_numbers
from tools.biz_logic.url_parsers import extract_job_id, extract_city, extract_company_id

_BASE_URL = "https://www.zhipin.com"


class ExtractCardList(BaseTool):
    name = "extract_card_list"
    description = "Extract all visible job cards from the current search page without clicking"
    input_schema = {"type": "object", "properties": {}}

    def __init__(self, browser=None):
        self._browser = browser

    def execute(self) -> ToolResult:
        if self._browser is None:
            return ToolResult(ok=False, data={}, error="browser not initialized")
        page = self._browser
        try:
            raw = page.run_js("""
                return Array.from(document.querySelectorAll('.job-card-wrap')).map(function(c, idx) {
                    var a = c.querySelector('a.job-name') || c.querySelector('a[href*="/job_detail/"]');
                    var sal = c.querySelector('.job-salary');
                    // 注意 Boss 坑：搜索卡里 .boss-name 是【公司名】（在 a.boss-info 内），不是 HR 名
                    var comp = c.querySelector('.boss-name') || c.querySelector('a.boss-info');
                    // a.boss-info 的 href = /gongsi/{公司加密id}.html，公司加密id 稳定，用于内容去重
                    var compLink = c.querySelector('a.boss-info');
                    var loc = c.querySelector('.company-location') || c.querySelector('.job-area');
                    // 搜索列表卡不含 HR 名（HR 在详情面板），故 hr 留空，不要误用 .boss-name(=公司)
                    var hr = c.querySelector('.recruit-info .name') || c.querySelector('.info-public .name') || null;
                    return {
                        href: a ? (a.getAttribute('href') || '') : '',
                        title: a ? (a.textContent || '').trim() : '',
                        salary: sal ? (sal.textContent || '').trim() : '',
                        company: comp ? (comp.textContent || '').trim() : '',
                        company_href: compLink ? (compLink.getAttribute('href') || '') : '',
                        location: loc ? (loc.textContent || '').trim() : '',
                        hr_name: hr ? (hr.textContent || '').trim() : '',
                        card_dom_index: idx,
                    };
                });
            """)
            raw_cards = raw if isinstance(raw, list) else []
            cards = []
            for card_data in raw_cards:
                href = card_data.get("href", "")
                if href and href.startswith("/"):
                    href = f"{_BASE_URL}{href}"
                job_id = extract_job_id(href)
                if not job_id:
                    continue
                city_text = card_data.get("location", "")
                cards.append({
                    "job_id": job_id,
                    "company_id": extract_company_id(card_data.get("company_href", "")),
                    "title": card_data.get("title", ""),
                    "company": card_data.get("company", ""),
                    "salary": decode_boss_numbers(card_data.get("salary", "")),
                    "city": extract_city(city_text),
                    "hr_name": card_data.get("hr_name", ""),
                    "card_dom_index": card_data.get("card_dom_index", 0),
                    "href": href,
                })
            return ToolResult(ok=True, data={"card_count": len(cards), "cards": cards})
        except Exception as exc:
            return ToolResult(ok=False, data={}, error=str(exc))
