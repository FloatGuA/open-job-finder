"""点开新标签页拿 URL，拿完必须关掉。

**为什么必须关**：不关的话标签页会越积越多，而 `list_pages` 的输出里"哪个是刚开的"
就再也判不准了——第 11 个岗位会拿到第 3 个岗位的 URL，而这种错**完全不会报错**，
只会让库里躺着一批指错地方的记录。
"""
import asyncio

import pytest
from langchain_core.tools import StructuredTool

from multisite.executors import JobRow, job_url_offline, job_url_online
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

    async def select_page(pageId: int):
        calls.append(("select_page", pageId))
        return f"Selected page {pageId}"

    async def take_snapshot():
        calls.append(("take_snapshot", None))
        return "DETAIL-SNAPSHOT: 岗位详情正文"

    async def close_page(pageId: int):
        calls.append(("close_page", pageId))
        state["pages"] = PAGES_ONE
        return "closed"

    return [StructuredTool.from_function(coroutine=f, name=n, description=n)
            for f, n in ((click, "click"), (list_pages, "list_pages"),
                         (select_page, "select_page"), (take_snapshot, "take_snapshot"),
                         (close_page, "close_page"))], calls


def _run(c):
    return asyncio.run(c)


class TestJobUrlOnline:
    def test_returns_the_url_of_the_newly_opened_page(self):
        tools, _ = _tools()
        url, _detail = _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
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
        got = _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        assert got is None
        assert not any(c[0] == "close_page" for c in calls)


class TestJobUrlOnlineAlsoReadsTheDetailPage:
    """取 URL 和取 JD 必须是同一次访问。

    spec §5.1 的成本论证就建立在这上面：`new_tab_on_click` 的站本来就必须点开详情页
    才能拿到 URL，既然已经在那一页上了，顺手读走快照近乎免费。分成两次访问会让
    run 时长翻倍（每个岗位 ≈8 秒 → ≈16 秒）。
    """

    def test_returns_url_and_detail_snapshot(self):
        tools, _ = _tools()
        got = _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        assert got is not None
        url, detail = got
        assert url == "https://join.qq.com/post_detail.html?postid=999"
        assert "DETAIL-SNAPSHOT" in detail

    def test_reads_the_detail_page_not_the_list_page(self):
        """必须在**切到新标签页之后**读快照。读成列表页的话，每个岗位拿到的 JD
        都一样，而那看起来完全正常——分类会按同一段文本给所有岗位打分。"""
        tools, calls = _tools()
        _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        names = [c[0] for c in calls]
        assert "select_page" in names, "没有切到详情页就读快照"
        assert names.index("select_page") < names.index("take_snapshot")

    def test_closes_the_tab_even_after_reading(self):
        """加了读快照这一步之后，「拿完必须关」这条不能被破坏。"""
        tools, calls = _tools()
        _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))
        assert ("close_page", 1) in calls
        assert ("close_page", 0) not in calls

    def test_still_returns_none_when_nothing_opens(self):
        tools, calls = _tools(pages_after_click=PAGES_ONE)
        assert _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual())) is None
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

        async def close_page(pageId: int):
            calls.append(("close_page", pageId))
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


class TestJobUrlOnlineReselectsListPageAfterClose:
    """真机行为（2026-08-20 run `m1_20260820_1620.jsonl`）：chrome-devtools-mcp 在
    「选中的页被关闭」之后**不会自动重选任何页**——`list_pages` 会持续返回
    "The selected page has been closed. Call list_pages to see open pages."，直到
    有人显式 `select_page`。之前一次代码评审读 MCP 源码得出"`McpContext.
    createPagesSnapshot` 会自动重选 `pages[0]`，因此不重选是安全的"的结论，被真机
    行为推翻。`job_url_online` 每取完一个岗位都会 `close_page` 掉刚选中的详情页，
    不显式重选回列表页的话，下一次调用开头的 `list_pages` 就会拿到错误字符串，
    触发 `TestJobUrlOnlineFailsFastWhenListPagesErrors` 那道 fail-fast 守卫，
    整个 harvest 循环中断。

    用索引 3 / 7（而不是 `_tools()` 惯用的 0 / 1）构造页面编号，是为了拆穿"重选
    硬编码 pageId=1 或 pages[0]"这种实现——必须重选的是**点击前处于 [selected]
    状态的那一页**，不是某个固定编号。
    """

    PAGES_BEFORE = ("## Pages\n"
                     "3: 岗位投递 (https://join.qq.com/post.html) [selected]\n")
    PAGES_AFTER_CLICK = ("## Pages\n"
                          "3: 岗位投递 (https://join.qq.com/post.html) [selected]\n"
                          "7: 岗位详情 (https://join.qq.com/post_detail.html?postid=999)\n")

    def _tools(self):
        calls = []
        state = {"pages": self.PAGES_BEFORE}

        async def click(uid: str):
            calls.append(("click", uid))
            state["pages"] = self.PAGES_AFTER_CLICK
            return "Successfully clicked on the element"

        async def list_pages():
            calls.append(("list_pages", None))
            return state["pages"]

        async def select_page(pageId: int):
            calls.append(("select_page", pageId))
            return f"Selected page {pageId}"

        async def take_snapshot():
            calls.append(("take_snapshot", None))
            return "DETAIL-SNAPSHOT: 岗位详情正文"

        async def close_page(pageId: int):
            calls.append(("close_page", pageId))
            state["pages"] = self.PAGES_BEFORE
            return "closed"

        return [StructuredTool.from_function(coroutine=f, name=n, description=n)
                for f, n in ((click, "click"), (list_pages, "list_pages"),
                             (select_page, "select_page"), (take_snapshot, "take_snapshot"),
                             (close_page, "close_page"))], calls

    def test_reselects_the_page_that_was_selected_before_the_click(self):
        tools, calls = self._tools()
        _run(job_url_online(JobRow(anchor_uid="1_87", text="x"), tools, _manual()))

        close_idx = calls.index(("close_page", 7))
        after_close = calls[close_idx + 1:]
        assert ("select_page", 3) in after_close, (
            "关闭详情页（索引 7）之后必须重新选中点击前处于 [selected] 状态的那一页"
            "（索引 3），不能不重选、也不能硬编码 pageId=1 或 pages[0]。实际调用序列："
            f"{calls!r}")


class TestJobUrlOnlineSurvivesConsecutiveCallsAfterClose:
    """这是本次修复的守门测试：模拟真实 chrome-devtools-mcp 的行为——`close_page`
    关掉当前选中的页之后，`list_pages` 返回错误字符串，直到有人 `select_page`。
    修复前，第一次 `job_url_online` 调用会在结尾把选中态清空，第二次调用开头的
    `list_pages`（判据①）就会拿到错误字符串 → `before` 解析不出页面 → fail-fast
    抛异常。修复后第二次调用应当照常成功，这正是真机 run 里 `scan_buckets`
    连续取多个岗位时会撞上的形态。
    """

    def _tools(self):
        calls = []
        # 状态机模拟真实 MCP：`pages` 是当前打开的页 {idx: url}；`selected` 是当前
        # 选中的页 idx，`close_page` 关掉「当前选中」的页后把 `selected` 置空
        # （真机不会自动重选），此后 `list_pages` 返回错误字符串直到 `select_page`。
        state = {"pages": {0: "https://join.qq.com/post.html"}, "selected": 0,
                 "next_idx": 1}

        def render_pages():
            if state["selected"] is None:
                return "The selected page has been closed. Call list_pages to see open pages."
            lines = ["## Pages"]
            for idx, url in sorted(state["pages"].items()):
                mark = " [selected]" if idx == state["selected"] else ""
                lines.append(f"{idx}: 岗位 ({url}){mark}")
            return "\n".join(lines) + "\n"

        async def click(uid: str):
            calls.append(("click", uid))
            idx = state["next_idx"]
            state["next_idx"] += 1
            state["pages"][idx] = f"https://join.qq.com/post_detail.html?postid={idx}"
            # 真机：新开的标签页不会自动被选中（`job_url_online` 自己会显式
            # select_page 切过去），当前选中的仍是点击前那一页。

        async def list_pages():
            calls.append(("list_pages", None))
            return render_pages()

        async def select_page(pageId: int):
            calls.append(("select_page", pageId))
            assert pageId in state["pages"], f"select_page 到一个不存在的页 {pageId}"
            state["selected"] = pageId

        async def take_snapshot():
            calls.append(("take_snapshot", None))
            return "DETAIL-SNAPSHOT: 岗位详情正文"

        async def close_page(pageId: int):
            calls.append(("close_page", pageId))
            del state["pages"][pageId]
            if state["selected"] == pageId:
                state["selected"] = None  # 真机行为：不自动重选

        return [StructuredTool.from_function(coroutine=f, name=n, description=n)
                for f, n in ((click, "click"), (list_pages, "list_pages"),
                             (select_page, "select_page"), (take_snapshot, "take_snapshot"),
                             (close_page, "close_page"))], calls

    def test_second_call_still_succeeds_after_first_call_closed_the_selected_page(self):
        tools, calls = self._tools()
        manual = _manual()

        first = _run(job_url_online(JobRow(anchor_uid="1_87", text="row1"), tools, manual))
        assert first is not None, "第一次调用本身就该成功"

        # 修复前：第一次调用结尾选中态被清空，这里会抛
        # RuntimeError("list_pages 在点击前解析不出任何页面...")。
        second = _run(job_url_online(JobRow(anchor_uid="1_88", text="row2"), tools, manual))
        assert second is not None, (
            "第二次调用应当照常成功——真机上「关掉选中页之后 list_pages 报错」"
            "不能让后续每一次取 URL 都失败"
        )
        assert second[0] == "https://join.qq.com/post_detail.html?postid=2"


class TestJobUrlOfflineUnaffectedByReselectFix:
    """`job_url_offline` 的函数签名里根本没有 `tools` 参数，压根不碰浏览器标签页，
    本次修复只改了 `job_url_online` 里 `close_page` 之后的重选逻辑——这条测试只是
    确认这条路径原样不受影响。"""

    def test_offline_path_does_not_touch_any_browser_tool(self):
        manual = SiteManual.from_dict({
            "job_url_source": "link_in_row", "url_template": "", "pagination": "none",
            "filter_interaction": "direct_click", "filters_survive_reload": False,
            "total_count_locator": "", "row_split": "anchor_text", "row_anchor": "地点",
            "dimensions": [], "important_notes": ""})
        snapshot = ('## Latest page snapshot\n'
                    'uid=1_5 link "后端开发工程师" '
                    'url="https://example.com/job/12345"\n'
                    'uid=1_6 StaticText "地点"\n')
        row = JobRow(anchor_uid="1_6", text="x")
        assert job_url_offline(row, snapshot, manual) == "https://example.com/job/12345"
