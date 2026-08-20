"""手册过期比没有手册更糟，所以每轮都要轻校验。

- `job_url_source` 变了 → harvest 抓回一堆空 URL → 表现是"这个站突然没岗位了"
- `filter_interaction` 变了 → 筛选点不动 → 回到 2026-08-19 那个死循环

但"校验"如果做成重新探一遍就没有意义（成本一样），所以只验最要命的三条，约 3–5 步。
**任一条不过整份作废**——不做部分沿用：手册字段之间有耦合，逐格判断"哪格还能用"
的成本接近重探，而判错的产物是半对的手册，最难查。
"""
import asyncio
from pathlib import Path

from langchain_core.tools import StructuredTool

from multisite.executors import validate_manual
from multisite.site_manual import SiteManual

SNAPSHOT = (Path(__file__).parent / "fixtures" / "joinqq_post_list.txt").read_text(encoding="utf-8")


def _manual(**over) -> SiteManual:
    d = {"job_url_source": "new_tab_on_click", "url_template": "", "pagination": "next_button",
         "filter_interaction": "expand_group_then_click", "filters_survive_reload": False,
         "total_count_locator": r"共(\d+)个岗位", "row_split": "anchor_text",
         "row_anchor": "工作地点：",
         "dimensions": [{"name": "应聘项目",
                         "options": ["应届毕业生", "2027校园招聘"], "multi_select": True}],
         "important_notes": ""}
    d.update(over)
    return SiteManual.from_dict(d)


def _tools(url="https://join.qq.com/post_detail.html?postid=999"):
    pages_one = "## Pages\n0: 列表 (https://join.qq.com/post.html) [selected]\n"
    pages_two = pages_one + f"1: 详情 ({url})\n"
    state = {"pages": pages_one}

    async def click(uid: str):
        state["pages"] = pages_two
        return "Successfully clicked on the element"

    async def list_pages():
        return state["pages"]

    async def select_page(pageId: int):
        return f"Selected page {pageId}"

    async def navigate_page(url: str):
        return "Navigated"

    async def take_snapshot():
        return "DETAIL-SNAPSHOT: 岗位详情正文"

    async def close_page(pageId: int):
        state["pages"] = pages_one
        return "closed"

    return [StructuredTool.from_function(coroutine=f, name=n, description=n)
            for f, n in ((click, "click"), (list_pages, "list_pages"),
                         (select_page, "select_page"), (navigate_page, "navigate_page"), (take_snapshot, "take_snapshot"),
                         (close_page, "close_page"))]


def _run(c):
    return asyncio.run(c)


class TestValidateManual:
    def test_an_unchanged_site_passes(self):
        ok, why = _run(validate_manual(SNAPSHOT, _tools(), _manual()))
        assert ok is True, why

    def test_missing_count_text_fails(self):
        """计数是整个试探机制的 oracle，它没了后面全塌。"""
        ok, why = _run(validate_manual(SNAPSHOT, _tools(),
                                       _manual(total_count_locator=r"共(\d+)个职位")))
        assert ok is False and "计数" in why

    def test_changed_filter_options_fail(self):
        """招聘站改版最先体现在筛选项增删上（2027校园招聘 → 2028校园招聘）。
        这条**会在每年招聘季准时触发一次重探**，那是对的。"""
        m = _manual(dimensions=[{"name": "应聘项目",
                                 "options": ["应届毕业生", "2028校园招聘"],
                                 "multi_select": True}])
        ok, why = _run(validate_manual(SNAPSHOT, _tools(), m))
        assert ok is False and "选项" in why

    def test_url_extraction_that_stops_working_fails(self):
        """job_url_source 是手册里最要命的一格，错了整轮白抓。而它**只能靠实做验**
        ——读快照看不出"点下去会不会开新标签页"。"""
        tools = _tools()

        async def click_that_opens_nothing(uid: str):
            return "Successfully clicked on the element"

        tools[0] = StructuredTool.from_function(coroutine=click_that_opens_nothing,
                                                name="click", description="click")
        ok, why = _run(validate_manual(SNAPSHOT, tools, _manual()))
        assert ok is False and "URL" in why

    def test_the_reason_is_human_readable(self):
        """失败原因要能直接进 run 日志给人看。空字符串等于"验失败了但不知道为什么"。"""
        _, why = _run(validate_manual(SNAPSHOT, _tools(),
                                      _manual(total_count_locator=r"共(\d+)个职位")))
        assert len(why) > 5


class TestSuccessReasonListsWhatWasActuallyChecked:
    """成功的 reason 以前无论如何都是「手册仍然成立」——但 `total_count_locator`
    为空会跳过判据①、`dimensions` 为空会跳过判据②，可以退化到几乎什么都没验，
    却仍然报同一句话。reason 现在要如实列出跑了哪几条、跳过了哪几条。"""

    def test_full_manual_lists_all_three_checks(self):
        ok, why = _run(validate_manual(SNAPSHOT, _tools(), _manual()))
        assert ok is True
        assert "计数文本" in why
        assert "首个维度选项" in why
        assert "取 URL" in why
        assert "跳过" not in why

    def test_manual_without_locator_or_dimensions_explains_the_skip(self):
        """两个可选判据都没配置——只有判据③真正跑了，reason 必须说清楚。"""
        m = _manual(total_count_locator="", dimensions=[])
        ok, why = _run(validate_manual(SNAPSHOT, _tools(), m))
        assert ok is True
        assert why.startswith("已验：取 URL")
        assert "跳过" in why
        assert "计数文本" in why
        assert "维度" in why
