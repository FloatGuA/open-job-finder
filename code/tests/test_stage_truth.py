"""阶段要如实报告自己：失败原因、有没有跑完、以及它到底停在哪个页面。

三个洞（2026-08-18 真机之后发现）：
1. `log_step` 收了 `error` 却没放进 SSE/回放事件——站点在前端变红，但看不到为什么。
2. agent 步数耗尽只 print，阶段照样报 successful——前端一片正常，而活儿没干完。
   这跟"名额没满"叠加成一个错误结论：看到「游戏 0/2」会以为站上没有，
   实际可能是压根没扫到。
3. `ensure_ready` 的产出是 `snapshot_chars`（快照字符数）——它只能回答"页面渲染了吗"，
   答不了"停在哪个 URL、标题是什么、过没过登录"，而那些信息就在快照第一行。
"""
import asyncio

import pytest

from multisite.layer1_agent import _describe_page
from multisite.observability import traced_stage
from pipeline.run_logger import RunLogger
from services.progress_emitter import ProgressEvent, event_to_dict
from services.run_log_reader import parse_run_events


class FakeEmitter:
    def __init__(self):
        self.events = []
        self.stop_requested = False

    def emit(self, event):
        self.events.append(event)


# ── 洞 1：失败原因要到得了前端 ──────────────────────────────────────────────

class TestErrorReachesTheFrontend:
    def test_event_to_dict_includes_error(self):
        ev = ProgressEvent(workflow="m1", step="find_jobs", status="error",
                           message="m", error="找不到筛选器")
        assert event_to_dict(ev)["error"] == "找不到筛选器"

    def test_error_is_none_on_success(self):
        ev = ProgressEvent(workflow="m1", step="find_jobs", status="done", message="m")
        assert event_to_dict(ev)["error"] is None

    def test_sse_step_event_carries_the_error(self, tmp_path, monkeypatch):
        import services.run_logger as srl
        monkeypatch.setattr(srl, "RUNS_DIR", tmp_path)
        emitter = FakeEmitter()
        logger = RunLogger(pipeline="m1", run_id="m1_err", emitter=emitter, debug=True)
        logger.log_step("find_jobs", {}, "failed", 900, data={}, error="页面加载后仍是空白")

        assert emitter.events[-1].error == "页面加载后仍是空白"

    def test_replayed_step_carries_the_error(self, tmp_path, monkeypatch):
        """回放和实时必须给同一个字段集合。"""
        import services.run_logger as srl
        monkeypatch.setattr(srl, "RUNS_DIR", tmp_path)
        logger = RunLogger(pipeline="m1", run_id="m1_err2", debug=True)
        logger.log_step("find_jobs", {}, "failed", 900, data={}, error="页面加载后仍是空白")
        logger.close("failed")

        events = parse_run_events(tmp_path / "m1_err2.jsonl")
        assert all("error" in e for e in events)
        step = next(e for e in events if e["step"] == "find_jobs")
        assert step["error"] == "页面加载后仍是空白"


# ── 洞 2：没跑完就不能报成功 ────────────────────────────────────────────────

class DumpLogger:
    def __init__(self, run_id="m1_partial"):
        self.run_id = run_id
        self.steps = []

    def log_step(self, name, scope, status, duration_ms, data=None, error=None):
        self.steps.append({"name": name, "status": status, "data": data or {}, "error": error})


class TestTruncatedStageIsNotReportedSuccessful:
    def _run(self, out):
        logger = DumpLogger()

        async def fn(state):
            return out

        asyncio.run(traced_stage("find_jobs", fn, logger, summarize=lambda o: {"found": 15})(
            {}))
        return logger.steps[-1]

    def test_a_truncated_stage_is_partial(self):
        """agent 步数耗尽 = 活儿没干完。报 successful 会让"扫完了"和"扫到一半"
        在日志和前端里完全无法区分。"""
        assert self._run({"truncated": True})["status"] == "partial"

    def test_a_complete_stage_is_successful(self):
        assert self._run({"found_jobs": []})["status"] == "successful"

    def test_partial_passes_through_to_the_ui_vocabulary(self):
        """`partial` 不能被映射成 done 或 skipped——两者在前端都是绿的。"""
        from pipeline.run_logger import _ui_status
        assert _ui_status("partial") == "partial"

    def test_the_truncation_is_visible_in_the_step_data(self):
        """光有状态不够，还要能看出"为什么是部分的"。"""
        assert self._run({"truncated": True})["data"]["truncated"] is True


# ── 洞 3：ensure_ready 要报有用的东西 ──────────────────────────────────────

SNAPSHOT = '''## Latest page snapshot
uid=1_0 RootWebArea "校园招聘 - 甲公司" url="https://example.com/campus/"
  uid=1_1 link "职位"
  uid=1_2 button "筛选"
'''


class TestDescribePage:
    def test_extracts_url_and_title(self):
        assert _describe_page(SNAPSHOT) == {
            "url": "https://example.com/campus/",
            "title": "校园招聘 - 甲公司",
            "snapshot_chars": len(SNAPSHOT),
        }

    def test_missing_root_area_degrades_gracefully(self):
        """快照形状变了不该让整个阶段炸——这一步的职责是导航，不是解析。"""
        out = _describe_page("## Latest page snapshot\n(nothing)\n")
        assert out["url"] == "" and out["title"] == ""

    def test_snapshot_chars_is_kept_as_a_secondary_signal(self):
        """字符数本身不够用，但"页面是不是空壳"仍然只有它能便宜地回答。"""
        assert _describe_page(SNAPSHOT)["snapshot_chars"] > 0


class TestDescribePageIsNotPositionCoupled:
    """`RootWebArea` 那一行有多种形态，标题与 url 之间可能夹着别的属性。

    2026-08-18 真机：m1 的 `ensure_ready` 报出 `title` 有值但 **`url` 是空的**——
    原正则要求 `url=` 紧跟在标题引号之后，入口页那行中间还有属性，就匹配不上了。
    标题和 url 是同一行上**互相独立**的两样东西，不该用位置把它们绑在一起。
    """

    def test_attributes_between_title_and_url(self):
        snap = ('## Latest page snapshot\n'
                'uid=1_0 RootWebArea "甲公司校园招聘" focusable url="https://example.com/campus/"\n')
        got = _describe_page(snap)
        assert got["title"] == "甲公司校园招聘"
        assert got["url"] == "https://example.com/campus/"

    def test_url_only_no_title(self):
        """页面还没渲染时根本没有标题——不能把 url 误当成标题。"""
        got = _describe_page('## Latest page snapshot\nuid=1_0 RootWebArea url="about:blank"\n')
        assert got["title"] == ""
        assert got["url"] == "about:blank"

    def test_title_only_no_url(self):
        got = _describe_page('## Latest page snapshot\nuid=1_0 RootWebArea "只有标题"\n')
        assert got["title"] == "只有标题"
        assert got["url"] == ""

    def test_url_of_a_child_node_is_not_mistaken_for_the_page_url(self):
        """子节点（链接）也带 url=，只能取根节点那一行的。"""
        snap = ('## Latest page snapshot\n'
                'uid=1_0 RootWebArea "页面" url="https://example.com/page"\n'
                '  uid=1_1 link "别处" url="https://elsewhere.com/"\n')
        assert _describe_page(snap)["url"] == "https://example.com/page"
