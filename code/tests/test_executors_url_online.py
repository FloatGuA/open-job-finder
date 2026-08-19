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
        """不仅要关一页，关的必须是**新开的那一页**（索引 1），绝不能是列表页本身
        （索引 0）——关错列表页比不关更严重：后续每一个岗位都会取不到 URL，
        而这种错同样不报错、不崩溃。"""
        tools, calls = _tools()
        _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        assert ("close_page", 1) in calls, "没关掉新开的详情页（索引 1）"
        assert ("close_page", 0) not in calls, "绝不能关掉列表页本身（索引 0）"

    def test_click_that_opens_nothing_returns_none_and_closes_nothing(self):
        """有的行点了不跳转（比如那一行其实是广告）。要返回 None 让调用方计一次失败，
        **而不是把当前列表页的 URL 当成岗位 URL 写进库**。"""
        tools, calls = _tools(pages_after_click=PAGES_ONE)
        url = _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        assert url is None
        assert not any(c[0] == "close_page" for c in calls)


class TestJobUrlOnlineFailsFastWhenListPagesErrors:
    """chrome-devtools-mcp 把执行错误当正常内容返回（`isError=False`，见
    `safe_tools.py` `_result_text` 的注释）——真机日志里 29 次点击失败没有一次是异常，
    这是预期内路径。点击前的那次 `list_pages` 如果解析不出任何页面（页面数不可能是 0），
    几乎总是工具出错，而不是真的没有页面。旧实现用 URL 集合做基准，这种情况下
    `before` 是空集，`after` 里的每一页（包括索引 0 的**列表页本身**）都会被判成
    "新开的"，函数会把**列表页 URL** 当成岗位 URL 返回，并把**列表页本身**关掉。"""

    def _tools_with_broken_list_pages(self):
        calls = []

        async def click(uid: str):
            calls.append(("click", uid))
            return "Successfully clicked on the element"

        async def list_pages():
            calls.append(("list_pages", None))
            return "Error: Protocol error (Page.captureSnapshot): Target closed"

        async def close_page(pageIdx: int):
            calls.append(("close_page", pageIdx))
            return "closed"

        tools = [StructuredTool.from_function(coroutine=f, name=n, description=n)
                 for f, n in ((click, "click"), (list_pages, "list_pages"),
                              (close_page, "close_page"))]
        return tools, calls

    def test_raises_instead_of_returning_the_list_page_url(self):
        tools, calls = self._tools_with_broken_list_pages()
        with pytest.raises(RuntimeError, match="list_pages"):
            _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        assert not any(c[0] == "click" for c in calls), \
            "点击前的 list_pages 就该 fail fast，不该往下点"

    def test_never_closes_the_list_page(self):
        tools, calls = self._tools_with_broken_list_pages()
        with pytest.raises(RuntimeError):
            _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        assert not any(c[0] == "close_page" for c in calls), \
            "绝不能把列表页（索引 0）当成新开的页面关掉"
