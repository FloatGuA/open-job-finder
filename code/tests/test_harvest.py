"""抓一页岗位：切行 → 逐行取 URL 和 JD → 批量分类 → 落袋。

**为什么必须是代码而不是 agent 自己做**：一页 10 个岗位，每个都要「点开→读 URL→
读 JD→关掉」。交给 agent 就是 40 次工具调用、40 个 ReAct 轮次；60 步预算只够一页半。
代码做完这些只占 agent 的**一次**工具调用。
"""
import asyncio
from pathlib import Path

import pytest
from langchain_core.tools import StructuredTool

from multisite.harvest import harvest_page
from multisite.site_manual import SiteManual

SNAPSHOT = (Path(__file__).parent / "fixtures" / "joinqq_post_list.txt").read_text(encoding="utf-8")
BAMBULAB_SNAPSHOT = (Path(__file__).parent / "fixtures" / "bambulab_job_list.txt").read_text(encoding="utf-8")


def _manual(**over) -> SiteManual:
    d = {"job_url_source": "new_tab_on_click", "url_template": "", "pagination": "next_button",
         "filter_interaction": "expand_group_then_click", "filters_survive_reload": False,
         "total_count_locator": r"共(\d+)个岗位", "row_split": "anchor_text",
         "row_anchor": "工作地点：", "dimensions": [], "important_notes": ""}
    d.update(over)
    return SiteManual.from_dict(d)


def _tools(fail_uids=()):
    """假浏览器：每次 click 开一个 URL 带自增序号的新页，快照里带该序号。"""
    state = {"n": 0, "pages": "## Pages\n0: list (https://x/list) [selected]\n"}
    calls = []

    async def click(uid: str):
        calls.append(("click", uid))
        if uid in fail_uids:
            return "Successfully clicked on the element"   # 点了但不开新页
        state["n"] += 1
        state["pages"] = ("## Pages\n0: list (https://x/list) [selected]\n"
                          f"1: detail (https://x/job/{state['n']})\n")
        return "Successfully clicked on the element"

    async def list_pages():
        return state["pages"]

    async def select_page(pageId: int):
        calls.append(("select_page", pageId))
        return "ok"

    async def navigate_page(url: str):
        return "Navigated"

    async def take_snapshot():
        return f"## Latest page snapshot\nJD-{state['n']}"

    async def close_page(pageId: int):
        calls.append(("close_page", pageId))
        state["pages"] = "## Pages\n0: list (https://x/list) [selected]\n"
        return "closed"

    fns = ((click, "click"), (list_pages, "list_pages"), (select_page, "select_page"),
           (navigate_page, "navigate_page"), (take_snapshot, "take_snapshot"), (close_page, "close_page"))
    return [StructuredTool.from_function(coroutine=f, name=n, description=n) for f, n in fns], calls


async def _classify_all(items):
    """假分类器：每条都归「开发」。"""
    return [{**it, "category": "开发", "why": "测试"} for it in items]


def _run(c):
    return asyncio.run(c)


def _bambulab_manual(**over) -> SiteManual:
    """`link_in_row` + `container_per_row`：bambulab 这类站，行本身就是那个 link
    节点，url 属性里带 `/position/`，节点 name 里标题/地点/类型/JD 摘要全挤在一起。
    见 `executors._split_rows_container_per_row` 的 docstring。"""
    d = {"job_url_source": "link_in_row", "url_template": "", "pagination": "none",
         "filter_interaction": "direct_click", "filters_survive_reload": False,
         "total_count_locator": "", "row_split": "container_per_row",
         "row_anchor": "/position/", "dimensions": [], "important_notes": ""}
    d.update(over)
    return SiteManual.from_dict(d)


class TestHarvestPage:
    def test_collects_every_row_on_the_page(self):
        tools, _ = _tools()
        sink = []
        out = _run(harvest_page(SNAPSHOT, tools, _manual(), bucket="技术",
                                classify=_classify_all, sink=sink,
                                known_urls=set(), limit=100))
        assert out["rows"] == 10
        assert out["collected"] == 10
        assert len(sink) == 10

    def test_each_job_gets_its_own_url_and_jd(self):
        """**每个岗位的 JD 必须来自它自己的详情页。** 全都一样的话，分类会按同一段
        文本给所有岗位打分，而那看起来完全正常。"""
        tools, _ = _tools()
        sink = []
        _run(harvest_page(SNAPSHOT, tools, _manual(), bucket="技术",
                          classify=_classify_all, sink=sink, known_urls=set(), limit=100))
        assert len({j["url"] for j in sink}) == 10
        assert len({j["jd"] for j in sink}) == 10

    def test_bucket_is_recorded_on_every_job(self):
        """投递上限常常按招聘项目算，没有 bucket 就只能拿全站数去比。"""
        tools, _ = _tools()
        sink = []
        _run(harvest_page(SNAPSHOT, tools, _manual(), bucket="技术",
                          classify=_classify_all, sink=sink, known_urls=set(), limit=100))
        assert all(j["bucket"] == "技术" for j in sink)

    def test_known_urls_are_skipped_and_counted(self):
        """跨 run 没有记忆，重跑同一个站必然重新找到上次那批岗位。
        跳过它们**而且要计数**——不计数的话"这一页都是旧的"和"这一页是空的"分不开。"""
        tools, _ = _tools()
        sink = []
        first = []
        _run(harvest_page(SNAPSHOT, tools, _manual(), bucket="技术",
                          classify=_classify_all, sink=first, known_urls=set(), limit=100))
        known = {j["url"] for j in first}

        tools2, _ = _tools()
        out = _run(harvest_page(SNAPSHOT, tools2, _manual(), bucket="技术",
                                classify=_classify_all, sink=sink, known_urls=known, limit=100))
        assert out["skipped_known"] == 10
        assert out["collected"] == 0

    def test_a_row_whose_url_cannot_be_read_is_counted_not_fatal(self):
        """一行取不到 URL 不能中断整页——但要计数，否则"少了两个"无声无息。"""
        tools, _ = _tools(fail_uids={"1_78", "1_87"})
        sink = []
        out = _run(harvest_page(SNAPSHOT, tools, _manual(), bucket="技术",
                                classify=_classify_all, sink=sink, known_urls=set(), limit=100))
        assert out["url_failed"] == 2
        assert out["collected"] == 8

    def test_limit_stops_early_and_says_so(self):
        """`limit` 是成本闸（每个岗位一次详情页往返 ≈8 秒）。停下来要**说出来**，
        否则"这一页只有 3 个岗位"和"抓到 3 个就到上限了"分不开。"""
        tools, _ = _tools()
        sink = []
        out = _run(harvest_page(SNAPSHOT, tools, _manual(), bucket="技术",
                                classify=_classify_all, sink=sink, known_urls=set(), limit=3))
        assert out["collected"] == 3
        assert out["truncated"] is True

    def test_not_truncated_when_the_whole_page_fits(self):
        tools, _ = _tools()
        sink = []
        out = _run(harvest_page(SNAPSHOT, tools, _manual(), bucket="技术",
                                classify=_classify_all, sink=sink, known_urls=set(), limit=100))
        assert out["truncated"] is False

    def test_classify_failure_drops_the_whole_page_without_writing(self):
        """分类挂了整页回退、**不落袋**。半页结果落袋会让下次去重误判成"已收录"。"""
        async def boom(items):
            raise RuntimeError("LLM down")

        tools, _ = _tools()
        sink = []
        with pytest.raises(RuntimeError, match="LLM down"):
            _run(harvest_page(SNAPSHOT, tools, _manual(), bucket="技术",
                              classify=boom, sink=sink, known_urls=set(), limit=100))
        assert sink == []

    def test_no_rows_is_a_distinct_result_from_failure(self):
        """锚点切不出行 → rows=0、collected=0，**不抛**。这是合法结果
        （筛到了一个空桶），跟解析失败要能分开。"""
        tools, _ = _tools()
        sink = []
        out = _run(harvest_page(SNAPSHOT, tools, _manual(row_anchor="这个文本不存在"),
                                bucket="技术", classify=_classify_all, sink=sink,
                                known_urls=set(), limit=100))
        assert out["rows"] == 0 and out["collected"] == 0


class TestHarvestPageTruncatesOversizedJd:
    """真实详情页 a11y 快照全文可能有 75-120KB；`classify_jobs` 把一页所有条目的
    jd 拼进同一个 prompt，撑爆 deepseek-chat 64k 上下文 → classify 抛 → 整页被
    丢弃（found=0）。必须在 harvest 边界截断，不能留到 classify 才截——那样落库
    的 jd 依然是全文。"""

    def _tools_with_long_jd(self, jd_len: int):
        state = {"n": 0, "pages": "## Pages\n0: list (https://x/list) [selected]\n"}

        async def click(uid: str):
            state["n"] += 1
            state["pages"] = ("## Pages\n0: list (https://x/list) [selected]\n"
                              f"1: detail (https://x/job/{state['n']})\n")
            return "Successfully clicked on the element"

        async def list_pages():
            return state["pages"]

        async def select_page(pageId: int):
            return "ok"

        async def navigate_page(url: str):
            return "Navigated"

        async def take_snapshot():
            return "JD" * jd_len  # 远超任何合理截断上限的超长详情页快照

        async def close_page(pageId: int):
            state["pages"] = "## Pages\n0: list (https://x/list) [selected]\n"
            return "closed"

        fns = ((click, "click"), (list_pages, "list_pages"), (select_page, "select_page"),
               (navigate_page, "navigate_page"), (take_snapshot, "take_snapshot"), (close_page, "close_page"))
        return [StructuredTool.from_function(coroutine=f, name=n, description=n) for f, n in fns]

    def test_jd_over_the_cap_is_truncated(self):
        from multisite.harvest import _JD_MAX_CHARS

        tools = self._tools_with_long_jd(jd_len=50_000)
        sink = []
        _run(harvest_page(SNAPSHOT, tools, _manual(), bucket="技术",
                          classify=_classify_all, sink=sink, known_urls=set(), limit=1))
        assert len(sink) == 1
        assert len(sink[0]["jd"]) == _JD_MAX_CHARS

    def test_jd_under_the_cap_is_left_untouched(self):
        tools = self._tools_with_long_jd(jd_len=10)  # "JD" * 10 = 20 字符，远低于上限
        sink = []
        _run(harvest_page(SNAPSHOT, tools, _manual(), bucket="技术",
                          classify=_classify_all, sink=sink, known_urls=set(), limit=1))
        assert sink[0]["jd"] == "JD" * 10


class TestHarvestPageOfflineJd:
    """`job_url_offline` 这条路（`link_in_row` 类站点，真机是 bambulab）以前 `jd`
    恒为空串——`row.text` 已经被当成分类 prompt 的 `title` 用了，但没人把它也
    当 `jd` 用，导致落库的 `jd` 长度为 0，分类规则「职责里出现 xx 就归 xx 类」
    完全没有 jd 可读（哪怕分类当时靠 title 里混进的同一段文本蒙对了）。修复：
    拿不到详情页快照时，`row.text` 本身就是这个站手边能拿到的最好的 JD 替代
    ——见 `_split_rows_container_per_row` 的 docstring：容器模式下这一行的
    accessible name 里标题/地点/类型/JD 摘要全挤在一起。用**真实 fixture**
    （不是玩具快照），因为这正是"看起来完全正常"的错误形态：10 条全部落进同一段
    文本或全部落空，测试用小快照测不出来。"""

    def test_jd_is_not_empty_for_every_row(self):
        sink = []
        out = _run(harvest_page(BAMBULAB_SNAPSHOT, None, _bambulab_manual(), bucket="技术",
                                classify=_classify_all, sink=sink, known_urls=set(), limit=100))
        assert out["collected"] == 10
        assert all(j["jd"] for j in sink), "有岗位的 jd 仍是空串"

    def test_each_row_s_jd_is_its_own_not_shared(self):
        """10 条岗位必须拿到 10 段不同的 jd——全部相同的话分类会按同一段文本给
        所有岗位打分，而那看起来完全正常（不报错、不崩溃）。"""
        sink = []
        _run(harvest_page(BAMBULAB_SNAPSHOT, None, _bambulab_manual(), bucket="技术",
                          classify=_classify_all, sink=sink, known_urls=set(), limit=100))
        assert len({j["jd"] for j in sink}) == len(sink) == 10


class TestHarvestPageOfflineJdTruncation:
    """离线路径的 jd 走**同一个** `_JD_MAX_CHARS` 上限，不另开一个常量——见
    `harvest.py` 顶部 `_JD_MAX_CHARS` 的注释：截断必须在 harvest 边界做一次，
    落库和分类 prompt 才不会各自面对一份没截断的原文。"""

    def _long_row_snapshot(self, length: int) -> str:
        long_text = "JD" * length
        return (
            '## Latest page snapshot\n'
            'uid=6_0 RootWebArea "x" url="https://example.com/"\n'
            f'  uid=6_1 link "{long_text}" url="https://example.com/position/111/detail"\n'
        )

    def test_offline_jd_over_the_cap_is_truncated(self):
        from multisite.harvest import _JD_MAX_CHARS

        snap = self._long_row_snapshot(50_000)
        sink = []
        _run(harvest_page(snap, None, _bambulab_manual(), bucket="技术",
                          classify=_classify_all, sink=sink, known_urls=set(), limit=1))
        assert len(sink) == 1
        assert len(sink[0]["jd"]) == _JD_MAX_CHARS

    def test_offline_jd_under_the_cap_is_left_untouched(self):
        snap = self._long_row_snapshot(10)  # "JD" * 10 = 20 字符，远低于上限
        sink = []
        _run(harvest_page(snap, None, _bambulab_manual(), bucket="技术",
                          classify=_classify_all, sink=sink, known_urls=set(), limit=1))
        assert sink[0]["jd"] == "JD" * 10


class TestHarvestStoresReadableJd:
    """落库的 `jd` 必须是可读正文，不是 a11y 快照转储。

    两个消费方都吃不下原始快照：Checkpoint 1 审批页原样渲染就是一屏 `uid=`；
    分类 prompt 里 `_JD_MAX_CHARS` 的额度大半花在标记上，真正的岗位正文被挤掉。
    **截断在 harvest 边界只做一次**，所以转换必须发生在截断之前——顺序反了的话
    先按标记算的 3000 字里，转换完可能只剩一千出头。
    """

    SNAP_DETAIL = ('## Latest page snapshot\n'
                   'uid=7_0 RootWebArea "岗位详情" url="https://example.test/d?id=1"\n'
                   '  uid=7_1 link "关于我们" url="https://example.test/about"\n'
                   '    uid=7_2 StaticText "关于我们"\n'
                   '  uid=7_3 StaticText "岗位描述"\n'
                   '  uid=7_4 StaticText "1、负责后端开发；\\n2、参与架构设计；"\n')

    def _tools(self):
        state = {"pages": "## Pages\n0: list (https://x/list) [selected]\n"}

        async def click(uid: str):
            state["pages"] = ("## Pages\n0: list (https://x/list) [selected]\n"
                              "1: detail (https://example.test/d?id=1)\n")
            return "ok"

        async def list_pages():
            return state["pages"]

        async def select_page(pageId: int):
            return "ok"

        async def navigate_page(url: str):
            return "Navigated"

        async def take_snapshot():
            return self.SNAP_DETAIL

        async def close_page(pageId: int):
            state["pages"] = "## Pages\n0: list (https://x/list) [selected]\n"
            return "ok"

        return [StructuredTool.from_function(coroutine=f, name=n, description=n)
                for f, n in ((click, "click"), (list_pages, "list_pages"),
                             (select_page, "select_page"), (navigate_page, "navigate_page"),
                             (take_snapshot, "take_snapshot"), (close_page, "close_page"))]

    def test_jd_has_no_markup(self):
        sink = []

        async def classify(items):
            return [dict(it, category="开发", why="", title="t", company="c")
                    for it in items]

        rep = asyncio.run(harvest_page(SNAPSHOT, self._tools(), _manual(),
                                       bucket="b", classify=classify, sink=sink,
                                       known_urls=set(), limit=1))
        assert rep["collected"] == 1, rep
        jd = sink[0]["jd"]
        assert "uid=" not in jd, jd[:120]
        assert "RootWebArea" not in jd
        assert "岗位描述" in jd
        assert "1、负责后端开发；" in jd
