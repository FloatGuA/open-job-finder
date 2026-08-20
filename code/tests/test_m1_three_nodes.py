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

        async def fake_classify_jobs(items, quotas, *, router=None, prompt_text=None,
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


class TestScanBucketsFailsWhenItNeverHarvested:
    """agent **正常结束**、却一次 `harvest_current_page` 都没调 —— 这必须是失败。

    **真机（2026-08-21 run `m1_20260820_1831`）**：agent 把整段预算耗在点「深圳」
    城市筛选器上（反复撞 `did not become interactive`），最后写了一段总结文字、
    没有任何工具调用，ReAct 循环就此正常返回。于是：

    ```
    scan_buckets  successful  {"found": 0, "by_category": {}}
    run_end       done
    ```

    **全绿，而它什么都没抓。**

    `observability.stage()` 里那句「没跑完就不许报成功」只认 `truncated`
    （`hit_step_limit`，即步数耗尽）。这次 `hit_step_limit` 是 False——
    **agent 正常结束 ≠ agent 干了活**，那是两件事，而只有前者有守门。

    对照 `survey_structure`：它在 `record_site_manual` 一次都没调时会
    `raise RuntimeError(还差：...)`，诚实失败并说清缺什么。`scan_buckets` 缺这道门。

    **为什么判据是"调用次数"而不是"found > 0"**：harvest 调过、但这一页的岗位
    全都已收录（`skipped_known`）或这一页本来就没岗位，`found=0` 是**诚实的成功**。
    区别在于 agent 到底看没看——**没看过和看了没有，不能长成一个样子。**
    """

    def _tools(self):
        from langchain_core.tools import StructuredTool

        async def _noop(uid: str = "") -> str:
            return ""

        names = ("take_snapshot", "click", "navigate_page", "wait_for",
                 "list_pages", "select_page", "close_page")
        return [StructuredTool.from_function(coroutine=_noop, name=n, description=n)
                for n in names]

    def _state(self):
        from multisite.site_manual import SiteManual
        manual = SiteManual.from_dict({
            "job_url_source": "new_tab_on_click", "url_template": "",
            "pagination": "next_button", "filter_interaction": "direct_click",
            "filters_survive_reload": False, "total_count_locator": "",
            "row_split": "anchor_text", "row_anchor": "x", "dimensions": [],
            "important_notes": ""})
        return {
            "manual": manual,
            "bucket_plan": [{"dimension": "d", "option": "o", "why": "", "targets": ["开发"]}],
            "site_name": "test-site",
            "search_url": "https://x/search",
        }

    def _run(self, monkeypatch, fake_run_agent, fake_harvest=None):
        import asyncio

        import multisite.layer1_agent as mod

        async def default_harvest(snapshot_text, tools, manual, *, bucket, classify,
                                  sink, known_urls, limit):
            return {"rows": 0, "collected": 0, "skipped_known": 0, "url_failed": 0,
                    "truncated": False}

        class _FakeAgent:
            def __init__(self, tools):
                self.tools = tools

        monkeypatch.setattr(mod, "harvest_page", fake_harvest or default_harvest)
        monkeypatch.setattr(mod.preferences, "render_golden_examples", lambda tracker: "")
        monkeypatch.setattr(mod.agent_runtime, "build_agent",
                            lambda tools, prompt: _FakeAgent(tools))
        monkeypatch.setattr(mod.agent_runtime, "run_agent", fake_run_agent)

        nodes, _ = mod._make_nodes(tools=self._tools(), personal_info={},
                                   tracker=FakeTracker(), quotas={"开发": 1})
        return asyncio.run(nodes["scan_buckets"][0](self._state()))

    def test_agent_that_calls_nothing_is_a_failure(self, monkeypatch):
        """真机那次的形状：agent 写了段文字就结束，一个工具都没调。"""
        async def fake_run_agent(agent, message, on_step=None):
            return {"messages": []}

        with pytest.raises(RuntimeError, match="harvest_current_page"):
            self._run(monkeypatch, fake_run_agent)

    def test_agent_that_only_clicked_around_is_a_failure(self, monkeypatch):
        """更贴近真机：它**调了**别的工具（点筛选器、截图），只是从没抓过。
        "调过工具"不能算干过活——**干的是不是这个活**才是判据。"""
        async def fake_run_agent(agent, message, on_step=None):
            for name in ("take_snapshot", "click", "click", "take_snapshot"):
                await next(t for t in agent.tools if t.name == name).ainvoke({"uid": "1_2"})
            return {"messages": []}

        with pytest.raises(RuntimeError, match="harvest_current_page"):
            self._run(monkeypatch, fake_run_agent)

    def test_harvesting_a_page_that_yields_nothing_is_still_success(self, monkeypatch):
        """抓了、但这一页的岗位全都已收录 —— `found=0` 是诚实的成功，不该报错。"""
        async def fake_run_agent(agent, message, on_step=None):
            tool = next(t for t in agent.tools if t.name == "harvest_current_page")
            await tool.ainvoke({"bucket": "技术"})
            return {"messages": []}

        async def all_known(snapshot_text, tools, manual, *, bucket, classify,
                            sink, known_urls, limit):
            return {"rows": 3, "collected": 0, "skipped_known": 3, "url_failed": 0,
                    "truncated": False}

        out = self._run(monkeypatch, fake_run_agent, fake_harvest=all_known)
        assert out["found_jobs"] == []

    def test_an_empty_plan_still_returns_quietly(self, monkeypatch):
        """`bucket_plan` 为空是合法结果（手册探出的桶没一个匹配目标类别），
        节点在进 agent 之前就返回了——那条早退路径不该被这道守门误伤。"""
        import asyncio

        import multisite.layer1_agent as mod
        nodes, _ = mod._make_nodes(tools=self._tools(), personal_info={},
                                   tracker=FakeTracker(), quotas={"开发": 1})
        state = {**self._state(), "bucket_plan": []}
        out = asyncio.run(nodes["scan_buckets"][0](state))
        assert out["found_jobs"] == []


class TestNodesHandTheirRouterToThePlainLlmCalls:
    """`_make_nodes(model_router=...)` 拿到的 router，必须真的交到
    `classify_jobs` / `compute_bucket_plan` 手上。

    **这条是变异验证逼出来的**：只守"编排层 → run_layer1"那一跳时，把节点里的
    `router=model_router` 改成 `router=None`，**全量测试一条都不红**——因为
    `TestScanBucketsWiresGoldenExamplesIntoClassify` 用的是假 classify（真的那个
    根本没跑），而 `test_classify_jobs.py` 是直接给 classify 注入 router 单测的。
    中间那一跳谁都没看着。

    router 要经过六道逐个枚举的关键字参数（编排层 → run_layer1 → build_select_graph
    → _make_nodes → 闭包 → classify_jobs/plan_buckets）。**漏一处不会报错**，
    只会让那条链路悄悄退回没有兜底的状态——W2 接简历时踩过一模一样的坑。
    """

    def _tools(self):
        from langchain_core.tools import StructuredTool

        async def _noop(uid: str = "") -> str:
            return ""

        names = ("take_snapshot", "click", "navigate_page", "wait_for",
                 "list_pages", "select_page", "close_page")
        return [StructuredTool.from_function(coroutine=_noop, name=n, description=n)
                for n in names]

    def _manual(self):
        from multisite.site_manual import SiteManual
        return SiteManual.from_dict({
            "job_url_source": "new_tab_on_click", "url_template": "",
            "pagination": "next_button", "filter_interaction": "direct_click",
            "filters_survive_reload": False, "total_count_locator": "",
            "row_split": "anchor_text", "row_anchor": "x", "dimensions": [],
            "important_notes": ""})

    def test_scan_buckets_passes_it_to_classify_jobs(self, monkeypatch):
        import asyncio

        import multisite.layer1_agent as mod

        sentinel = object()
        captured = {}

        async def fake_classify_jobs(items, quotas, *, router=None, prompt_text=None,
                                     golden_examples=None):
            captured["router"] = router
            return [{**it, "category": "开发", "why": ""} for it in items]

        async def fake_harvest_page(snapshot_text, tools, manual, *, bucket, classify,
                                    sink, known_urls, limit):
            sink.extend(await classify(
                [{"url": "https://x/1", "jd": "j", "bucket": bucket, "text": "raw"}]))
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
        monkeypatch.setattr(mod.preferences, "render_golden_examples", lambda tracker: "")
        monkeypatch.setattr(mod.agent_runtime, "build_agent",
                            lambda tools, prompt: _FakeAgent(tools))
        monkeypatch.setattr(mod.agent_runtime, "run_agent", fake_run_agent)

        nodes, _ = mod._make_nodes(tools=self._tools(), personal_info={},
                                   tracker=FakeTracker(), quotas={"开发": 1},
                                   model_router=sentinel)
        asyncio.run(nodes["scan_buckets"][0]({
            "manual": self._manual(),
            "bucket_plan": [{"dimension": "d", "option": "o", "why": "", "targets": ["开发"]}],
            "site_name": "s", "search_url": "https://x/search",
        }))

        assert captured["router"] is sentinel, \
            "节点没把自己的 model_router 交给 classify_jobs——那条链路会静默退回无兜底"

    def test_plan_buckets_passes_it_to_compute_bucket_plan(self, monkeypatch):
        import asyncio

        import multisite.layer1_agent as mod

        sentinel = object()
        captured = {}

        async def fake_compute_bucket_plan(manual, quotas, constraints, *, router=None):
            captured["router"] = router
            return []

        monkeypatch.setattr(mod, "compute_bucket_plan", fake_compute_bucket_plan)

        nodes, _ = mod._make_nodes(tools=self._tools(), personal_info={},
                                   tracker=FakeTracker(), quotas={"开发": 1},
                                   model_router=sentinel)
        asyncio.run(nodes["plan_buckets"][0]({"manual": self._manual()}))

        assert captured["router"] is sentinel


class TestScanBucketsSummaryNamesTheFiltersThatFailed:
    """设不上的筛选选项要出现在阶段摘要里。

    **不然它是隐形的**：地点筛选没设上 → 那个桶要么没扫、要么扫回来一堆外地岗位，
    而摘要上只有 `found: N`，人得从"这类怎么一个岗位都没有"反推。
    **agent 自己常常不报**（它写完总结就结束了），所以由工具层收集、由摘要输出。
    """

    def _tools(self):
        from langchain_core.tools import StructuredTool

        async def _noop(uid: str = "") -> str:
            return ""

        names = ("take_snapshot", "click", "navigate_page", "wait_for",
                 "list_pages", "select_page", "close_page")
        return [StructuredTool.from_function(coroutine=_noop, name=n, description=n)
                for n in names]

    def test_summary_carries_filter_failures(self):
        import multisite.layer1_agent as mod
        nodes, _ = mod._make_nodes(tools=self._tools(), personal_info={},
                                   tracker=FakeTracker(), quotas={"开发": 1})
        _fn, summarize = nodes["scan_buckets"]
        out = {"found_jobs": [], "truncated": False,
               "filter_failures": [{"option": "深圳", "reason": "找不到那个选项"}]}
        data = summarize(out)
        assert data["filter_failures"] == [{"option": "深圳", "reason": "找不到那个选项"}]

    def test_no_failures_means_the_key_is_absent(self):
        """没失败就别塞一个空列表进摘要——每个阶段的 data 都会进 run 日志和前端，
        常驻一个空字段只会让"有没有出问题"变得要多看一眼。"""
        import multisite.layer1_agent as mod
        nodes, _ = mod._make_nodes(tools=self._tools(), personal_info={},
                                   tracker=FakeTracker(), quotas={"开发": 1})
        _fn, summarize = nodes["scan_buckets"]
        data = summarize({"found_jobs": [], "truncated": False, "filter_failures": []})
        assert "filter_failures" not in data
