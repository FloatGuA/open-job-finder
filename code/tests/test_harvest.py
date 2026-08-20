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

    async def select_page(pageIdx: int):
        calls.append(("select_page", pageIdx))
        return "ok"

    async def take_snapshot():
        return f"## Latest page snapshot\nJD-{state['n']}"

    async def close_page(pageIdx: int):
        calls.append(("close_page", pageIdx))
        state["pages"] = "## Pages\n0: list (https://x/list) [selected]\n"
        return "closed"

    fns = ((click, "click"), (list_pages, "list_pages"), (select_page, "select_page"),
           (take_snapshot, "take_snapshot"), (close_page, "close_page"))
    return [StructuredTool.from_function(coroutine=f, name=n, description=n) for f, n in fns], calls


async def _classify_all(items):
    """假分类器：每条都归「开发」。"""
    return [{**it, "category": "开发", "why": "测试"} for it in items]


def _run(c):
    return asyncio.run(c)


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
