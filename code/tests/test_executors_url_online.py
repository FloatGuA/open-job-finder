"""点开新标签页拿 URL，拿完必须关掉。

**为什么必须关**：不关的话标签页会越积越多，而 `list_pages` 的输出里"哪个是刚开的"
就再也判不准了——第 11 个岗位会拿到第 3 个岗位的 URL，而这种错**完全不会报错**，
只会让库里躺着一批指错地方的记录。
"""
import asyncio

import pytest
from langchain_core.tools import StructuredTool

from multisite.executors import JobRow, job_url_online
from multisite.site_manual import SiteManual


def _manual() -> SiteManual:
    return SiteManual.from_dict({
        "job_url_source": "new_tab_on_click", "url_template": "", "pagination": "none",
        "filter_interaction": "direct_click", "filters_survive_reload": False,
        "total_count_locator": "", "row_split": "anchor_text", "row_anchor": "工作地点：",
        "dimensions": [], "important_notes": ""})


PAGES_TWO = ("## Pages\n"
             "0: 岗位投递 (https://join.qq.com/post.html) [selected]\n"
             "1: 岗位详情 (https://join.qq.com/post_detail.html?postid=999)\n")
PAGES_ONE = "## Pages\n0: 岗位投递 (https://join.qq.com/post.html) [selected]\n"


def _tools(pages_after_click=PAGES_TWO):
    calls = []
    state = {"pages": PAGES_ONE}

    async def click(uid: str):
        calls.append(("click", uid))
        state["pages"] = pages_after_click
        return "Successfully clicked on the element"

    async def list_pages():
        calls.append(("list_pages", None))
        return state["pages"]

    async def close_page(pageIdx: int):
        calls.append(("close_page", pageIdx))
        state["pages"] = PAGES_ONE
        return "closed"

    return [StructuredTool.from_function(coroutine=f, name=n, description=n)
            for f, n in ((click, "click"), (list_pages, "list_pages"),
                         (close_page, "close_page"))], calls


def _run(c):
    return asyncio.run(c)


class TestJobUrlOnline:
    def test_returns_the_url_of_the_newly_opened_page(self):
        tools, _ = _tools()
        url = _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        assert url == "https://join.qq.com/post_detail.html?postid=999"

    def test_clicks_the_anchor_uid(self):
        tools, calls = _tools()
        _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        assert ("click", "1_87") in calls

    def test_closes_the_tab_afterwards(self):
        tools, calls = _tools()
        _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        assert any(c[0] == "close_page" for c in calls), "开了不关，下一个岗位就会取错 URL"

    def test_click_that_opens_nothing_returns_none_and_closes_nothing(self):
        """有的行点了不跳转（比如那一行其实是广告）。要返回 None 让调用方计一次失败，
        **而不是把当前列表页的 URL 当成岗位 URL 写进库**。"""
        tools, calls = _tools(pages_after_click=PAGES_ONE)
        url = _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        assert url is None
        assert not any(c[0] == "close_page" for c in calls)
