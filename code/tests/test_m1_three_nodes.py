"""m1 的三节点形状。

拆之前 `find_jobs` 一个 ReAct 节点混着三件事：摸清站点结构（探索）、决定打哪几个桶
（纯判断）、逐条读岗位判类别落袋（机械+判断）。三件事共享一个步数预算、一个上下文、
一个完成判据——**一段跑飞就把整轮预算吃光**，前端也只能看到"find_jobs 卡住了"。
"""
import pytest

from multisite.layer1_agent import M1_STAGES, build_select_graph, stage_names


class FakeTool:
    def __init__(self, name):
        self.name = name


class FakeTracker:
    def get_pending_jobs(self):
        return []

    def get_site_manual(self, site):
        return None

    def get_site_brief(self, site):
        return None

    def get_golden_category_examples(self, limit=20):
        return []


def _kw():
    names = ["navigate_page", "take_snapshot", "click", "upload_file", "wait_for",
             "list_pages", "select_page", "close_page"]
    return dict(tools=[FakeTool(n) for n in names], personal_info={},
                tracker=FakeTracker(), quotas={"开发": 1})


class TestM1HasThreeNodes:
    def test_stage_order(self):
        assert stage_names("m1") == ("ensure_ready", "survey_structure",
                                     "plan_buckets", "scan_buckets", "write_pending_jobs")

    def test_find_jobs_is_gone(self):
        """旧节点必须真的消失，不能留着当死代码——留着会让"到底跑的是哪条路"
        变成一个需要读代码才能回答的问题。"""
        assert "find_jobs" not in M1_STAGES

    def test_graph_builds(self):
        assert build_select_graph(**_kw()) is not None

    def test_m2_is_untouched(self):
        """m2 与 m1 共用 `_make_nodes` 和 `ensure_ready`，改 m1 不能把 m2 带坏。"""
        from multisite.layer1_agent import M2_STAGES, build_survey_graph
        assert M2_STAGES == ("ensure_ready", "open_application",
                             "scan_and_classify_fields", "write_pending_application")
        assert build_survey_graph(**_kw()) is not None

    def test_drifted_stage_table_is_rejected_at_build_time(self, monkeypatch):
        import multisite.layer1_agent as mod
        monkeypatch.setattr(mod, "M1_STAGES", ("ensure_ready", "oops"))
        with pytest.raises(RuntimeError, match="阶段表"):
            build_select_graph(**_kw())


class TestHarvestItemsToFoundJobs:
    """修复轮 1：`scan_buckets` 把 `harvest_current_page` 的原始产出（已经过
    `classify_jobs` 加工）转成 `FoundJob` 时，`title`/`company` 必须用 classify
    的输出，不能退回用整行卡片文本——那正是这次修复要堵住的坏味道。这段转换
    逻辑被提到模块级 `_harvest_items_to_found_jobs`，就是为了能这样单测。
    """

    def test_title_and_company_come_from_classify_output_not_raw_text(self):
        from multisite.layer1_agent import _harvest_items_to_found_jobs

        raw_text = ("AI全栈工程师 技术 ｜ 应届毕业生 ｜ CDG CSIG IEG PCG TEG WXG "
                   "工作地点： 深圳总部 北京")
        raw = [{
            "url": "https://x/1",
            "text": raw_text,          # harvest_page 抓到的整行原文，仅供分类参考
            "jd": "职责：负责……",
            "bucket": "技术",
            "category": "开发",
            "why": "命中开发方向",
            "title": "AI全栈工程师",     # classify_jobs 抽取出的干净标题
            "company": "腾讯",
        }]

        jobs = _harvest_items_to_found_jobs(raw)

        assert jobs[0].title == "AI全栈工程师"
        assert jobs[0].company == "腾讯"
        assert jobs[0].title != raw_text
        assert jobs[0].jd == "职责：负责……"
        assert jobs[0].bucket == "技术"

    def test_missing_title_or_company_defaults_to_empty_string(self):
        """`classify_jobs` 没给这两个字段（比如整段解析失败前就短路）时不能
        炸——落库空字符串是诚实的、不是缺陷。"""
        from multisite.layer1_agent import _harvest_items_to_found_jobs

        jobs = _harvest_items_to_found_jobs([{"url": "https://x/2"}])
        assert jobs[0].title == ""
        assert jobs[0].company == ""


class TestScanBucketsWiresGoldenExamplesIntoClassify:
    """FIX-4：Checkpoint 1 的人工纠正一直在写 `is_golden`
    （`POST /api/checkpoint1/jobs/{id}/review`），`preferences.render_golden_examples`
    也早就写好了，但重构之后 `scan_buckets` 从没调用过它——标了也教不到。

    这里不碰真浏览器/真 LLM：把 `agent_runtime.build_agent`/`run_agent` 换成假的
    （直接调一次 `harvest_current_page` 工具，模拟 agent 决定去扫一个桶），
    `harvest_page`/`classify_jobs` 也换成假的，只用来捕获最终传给 `classify_jobs`
    的 `golden_examples` 参数，断言它就是 `preferences.render_golden_examples(tracker)`
    的产出——而不是重构前那个从没被调用过的值。
    """

    def _real_mcp_tools(self):
        """跟 `FakeTool`（只有 `.name`）不同——这里要真的跑一次
        `build_agent_toolset`（`_agent_tools` → `make_repeat_failure_guard`），
        它会读 `tool.description`/`tool.args_schema`。用 `StructuredTool`
        构造出形状完整的假工具，跟 `test_harvest.py`/`test_executors_url_online.py`
        的假浏览器同一个套路；这些工具在本测试里都不会被真的调用到
        （`fake_run_agent` 只调 `harvest_current_page`），签名不重要。"""
        from langchain_core.tools import StructuredTool

        async def _noop(**kwargs) -> str:
            return ""

        names = ("take_snapshot", "click", "navigate_page", "wait_for",
                 "list_pages", "select_page", "close_page")
        return [StructuredTool.from_function(coroutine=_noop, name=n, description=n)
                for n in names]

    def test_golden_examples_flow_from_tracker_into_classify_jobs(self, monkeypatch):
        import asyncio

        import multisite.layer1_agent as mod
        from multisite.site_manual import SiteManual

        captured = {}

        async def fake_classify_jobs(items, quotas, *, model=None, prompt_text=None,
                                     golden_examples=None):
            captured["golden_examples"] = golden_examples
            return [{**it, "category": "开发", "why": ""} for it in items]

        async def fake_harvest_page(snapshot_text, tools, manual, *, bucket, classify,
                                    sink, known_urls, limit):
            classified = await classify(
                [{"url": "https://x/1", "jd": "j", "bucket": bucket, "text": "raw"}])
            sink.extend(classified)
            return {"rows": 1, "collected": 1, "skipped_known": 0, "url_failed": 0,
                    "truncated": False}

        class _FakeAgent:
            def __init__(self, tools):
                self.tools = tools

        async def fake_run_agent(agent, message, on_step=None):
            tool = next(t for t in agent.tools if t.name == "harvest_current_page")
            await tool.ainvoke({"bucket": "技术"})
            return {"messages": []}

        monkeypatch.setattr(mod, "classify_jobs", fake_classify_jobs)
        monkeypatch.setattr(mod, "harvest_page", fake_harvest_page)
        monkeypatch.setattr(mod.preferences, "render_golden_examples",
                            lambda tracker: "【golden marker】")
        monkeypatch.setattr(mod.agent_runtime, "build_agent",
                            lambda tools, prompt: _FakeAgent(tools))
        monkeypatch.setattr(mod.agent_runtime, "run_agent", fake_run_agent)

        nodes, _snapshot_provider = mod._make_nodes(
            tools=self._real_mcp_tools(), personal_info={},
            tracker=FakeTracker(), quotas={"开发": 1})
        scan_buckets_fn, _summarize = nodes["scan_buckets"]

        manual = SiteManual.from_dict({
            "job_url_source": "new_tab_on_click", "url_template": "", "pagination": "next_button",
            "filter_interaction": "direct_click", "filters_survive_reload": False,
            "total_count_locator": "", "row_split": "anchor_text", "row_anchor": "x",
            "dimensions": [], "important_notes": ""})
        state = {
            "manual": manual,
            "bucket_plan": [{"dimension": "d", "option": "o", "why": "", "targets": ["开发"]}],
            "site_name": "test-site",
            "search_url": "https://x/search",
        }
        asyncio.run(scan_buckets_fn(state))

        assert captured["golden_examples"] == "【golden marker】"
