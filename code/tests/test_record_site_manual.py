"""`record_site_manual` 改成可增量调用之后的测试。

真机（2026-08-20，`m1_20260820_1357.jsonl`）：`survey_structure` 用了 19 个思考
轮次（预算 60，没耗尽），全程在做正事（用页面岗位计数验证筛选器多选/互斥：
152 -> 60 -> 64），最后一条却是纯文本总结、零工具调用——`record_site_manual`
当时要求 `job_url_source`/`pagination`/`filter_interaction`/`row_split` 四个
（`filter_interaction` 已于 2026-08-21 删除，现在是三个）
必填参数一次性齐全才能调用一次，agent 从没能凑齐去调用它。这是 PITFALLS
「答案必须最后一次性给出」那条记的第三次同类事故，`record_job` 是第一次治好
的样子——这组测试守的就是修复后的形状：参数全部可选、探到一点报一点、每次
调用都返回进度（已确认什么/还差什么），齐了才算完。
"""
import asyncio

import pytest

from multisite.layer1_agent import _make_nodes, make_record_site_manual_tool
from multisite.site_manual import SiteManual


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class TestRecordSiteManualToolIsIncremental:
    """直接测工具本身：不经过 agent 循环，只测 `sink` 的累积/校验逻辑。"""

    def test_partial_report_does_not_error_and_lists_whats_missing(self):
        sink: dict = {}
        tool = make_record_site_manual_tool(sink)

        result = _run(tool.ainvoke({"job_url_source": "link_in_row"}))

        # 不是"记录失败"——只报一部分是合法操作，不是错误。
        assert "完整" not in result
        assert "pagination" in result
        assert "row_split" in result
        assert "row_split" in result
        assert sink.get("manual") is None
        # 已经报的那部分确实落袋了，不是被丢弃。
        assert sink["fields"]["job_url_source"] == "link_in_row"

    def test_two_calls_complete_the_manual(self):
        sink: dict = {}
        tool = make_record_site_manual_tool(sink)

        first = _run(tool.ainvoke({
            "job_url_source": "link_in_row",
            "pagination": "next_button",
        }))
        assert "完整" not in first

        second = _run(tool.ainvoke({
            "filter_interaction": "direct_click",
            "row_split": "anchor_text",
            "row_anchor": "工作地点：",
        }))

        assert "完整" in second
        manual = sink.get("manual")
        assert isinstance(manual, SiteManual)
        assert manual.job_url_source == "link_in_row"
        assert manual.pagination == "next_button"
        assert manual.pagination == "next_button"
        assert manual.row_split == "anchor_text"
        assert manual.row_anchor == "工作地点："

    def test_empty_value_does_not_overwrite_an_already_reported_field(self):
        sink: dict = {}
        tool = make_record_site_manual_tool(sink)

        _run(tool.ainvoke({"pagination": "next_button"}))
        # 第二次调用没带 pagination（等于工具签名的默认空值）——不能把第一次
        # 报过的值冲掉。
        _run(tool.ainvoke({"job_url_source": "link_in_row"}))

        assert sink["fields"]["pagination"] == "next_button"

    def test_complete_required_fields_but_illegal_combo_returns_manual_error_verbatim(self):
        # 四个必填项都给了，但 row_split=anchor_text 却没给 row_anchor——
        # SiteManual.from_dict 会拒绝，工具必须原样带回这份 ManualError，不能报
        # "完整"，也不该在工具里重新写一遍这条条件必填规则。
        sink: dict = {}
        tool = make_record_site_manual_tool(sink)

        result = _run(tool.ainvoke({
            "job_url_source": "link_in_row",
            "pagination": "next_button",
            "filter_interaction": "direct_click",
            "row_split": "anchor_text",
        }))

        assert "完整" not in result
        assert "row_anchor" in result
        assert "不能为空" in result
        assert sink.get("manual") is None


class _FakeAgent:
    def __init__(self, tools):
        self.tools = tools


class _FakeTracker:
    """只给 `survey_structure` 用得到的那几个方法。"""

    def __init__(self):
        self.upserted = None

    def get_site_manual(self, site):
        return None

    def get_site_brief(self, site):
        return None

    def upsert_site_manual(self, site_name, manual):
        self.upserted = (site_name, manual)


def _real_mcp_tools():
    """跟 `test_m1_three_nodes.py` 里 `_real_mcp_tools` 同一个套路：用
    `StructuredTool` 构造出形状完整的假工具（`build_agent_toolset` 会读
    `tool.description`/`tool.args_schema`），本测试里都不会被真的调用到。
    """
    from langchain_core.tools import StructuredTool

    async def _noop(**kwargs) -> str:
        return ""

    names = ("take_snapshot", "click", "navigate_page", "wait_for",
             "list_pages", "select_page", "close_page")
    return [StructuredTool.from_function(coroutine=_noop, name=n, description=n)
            for n in names]


class TestSurveyStructureNodeUsesAccumulatedFields:
    """节点侧：agent 循环结束后，用 sink 累积到的字段重新跑一次唯一的校验
    实现（`SiteManual.from_dict`），不只信任某一次调用是否恰好凑齐了全部字段。
    """

    def _survey_structure_fn(self, monkeypatch, fake_run_agent):
        import multisite.layer1_agent as mod

        monkeypatch.setattr(mod.agent_runtime, "build_agent",
                            lambda tools, prompt: _FakeAgent(tools))
        monkeypatch.setattr(mod.agent_runtime, "run_agent", fake_run_agent)

        tracker = _FakeTracker()
        nodes, _snapshot_provider = mod._make_nodes(
            tools=_real_mcp_tools(), personal_info={}, tracker=tracker, quotas={})
        fn, _summarize = nodes["survey_structure"]
        return fn, tracker

    def test_incomplete_fields_raise_with_missing_field_names(self, monkeypatch):
        async def fake_run_agent(agent, message, on_step=None):
            tool = next(t for t in agent.tools if t.name == "record_site_manual")
            # 只报了一项，四个必填里的另外三项从没报过。
            await tool.ainvoke({"job_url_source": "link_in_row"})
            return {"messages": []}

        fn, _tracker = self._survey_structure_fn(monkeypatch, fake_run_agent)
        state = {"site_name": "test-site", "search_url": "https://x/search"}

        with pytest.raises(RuntimeError) as exc_info:
            asyncio.run(fn(state))

        message = str(exc_info.value)
        # 不是笼统的"没调用工具"——要能看出具体还差哪几项。
        assert "pagination" in message
        assert "row_split" in message
        assert "row_split" in message

    def test_two_partial_calls_across_the_loop_still_produce_a_manual(self, monkeypatch):
        async def fake_run_agent(agent, message, on_step=None):
            tool = next(t for t in agent.tools if t.name == "record_site_manual")
            await tool.ainvoke({"job_url_source": "link_in_row", "pagination": "next_button"})
            await tool.ainvoke({
                "filter_interaction": "direct_click",
                "row_split": "anchor_text",
                "row_anchor": "工作地点：",
            })
            return {"messages": []}

        fn, tracker = self._survey_structure_fn(monkeypatch, fake_run_agent)
        state = {"site_name": "test-site", "search_url": "https://x/search"}

        out = asyncio.run(fn(state))

        manual = out["manual"]
        assert isinstance(manual, SiteManual)
        assert manual.job_url_source == "link_in_row"
        assert manual.row_anchor == "工作地点："
        assert tracker.upserted == ("test-site", manual)
