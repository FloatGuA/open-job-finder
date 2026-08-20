"""`ensure_ready` 检测到未登录会轮询等最多 10 分钟。

今天的真实事故：等待期间唯一的提示是 `print(...)`，打进 uvicorn 的 stdout——
没有读者，还被块缓冲吃掉。结果系统在等人、人不知道，run 日志整整 10 分钟只有
一条 `run_start`。改成同时用 `logger.log(...)` 写 run 日志（JSONL + SSE），
Dashboard 实时日志上看得见，事后回放也看得见。`print` 保留（命令行直跑时是
唯一输出），但 `logger` 那条才是主路径——且 `logger` 可能是 None（命令行直跑
那条路径），必须不炸。
"""
import asyncio

import pytest
from langchain_core.tools import StructuredTool

from multisite.layer1_agent import _make_nodes

LOGGED_OUT_SNAPSHOT = (
    'uid=1_1 RootWebArea "首页" url="https://example.com"\n'
    'uid=1_2 StaticText "请登录后查看"\n'
    'uid=1_3 StaticText "更多内容"\n'
)
LOGGED_IN_SNAPSHOT = (
    'uid=1_1 RootWebArea "首页" url="https://example.com"\n'
    'uid=1_2 StaticText "欢迎回来"\n'
    'uid=1_3 StaticText "更多内容"\n'
)


class FakeTracker:
    def get_pending_jobs(self):
        return []


class FakeLogger:
    def __init__(self):
        self.calls = []

    def log(self, event, scope, data):
        self.calls.append((event, scope, data))


def _tools(snapshots):
    """`navigate_page` 什么都不做；`take_snapshot` 按传入序列依次返回，
    用完后重复最后一个值（防止多消费时 IndexError 掩盖真正的断言失败）。"""
    remaining = list(snapshots)

    async def navigate_page(type: str, url: str):
        return "ok"

    async def take_snapshot():
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return [
        StructuredTool.from_function(coroutine=navigate_page, name="navigate_page",
                                     description="navigate_page"),
        StructuredTool.from_function(coroutine=take_snapshot, name="take_snapshot",
                                     description="take_snapshot"),
    ]


def _ensure_ready(tools, logger, workflow="m2"):
    nodes, _ = _make_nodes(tools, personal_info={}, tracker=FakeTracker(),
                           quotas={}, logger=logger, workflow=workflow)
    return nodes["ensure_ready"][0]


def _tools_single_snapshot(snapshot):
    """`take_snapshot` 只允许被调用一次——第二次调用直接抛。用来证明 m1 分支
    检测到未登录后**没有**再截一次图去判断登录态是否变化（m1 根本不等）。"""
    calls = {"n": 0}

    async def navigate_page(type: str, url: str):
        return "ok"

    async def take_snapshot():
        calls["n"] += 1
        if calls["n"] > 1:
            raise AssertionError("m1 不该发起第二次截图（不该等待登录）")
        return snapshot

    return [
        StructuredTool.from_function(coroutine=navigate_page, name="navigate_page",
                                     description="navigate_page"),
        StructuredTool.from_function(coroutine=take_snapshot, name="take_snapshot",
                                     description="take_snapshot"),
    ]


def _run(c):
    return asyncio.run(c)


def _patch_sleep(monkeypatch):
    """真实实现 `asyncio.sleep(10)` 每轮等 10 秒，60 轮就是 10 分钟——测试不该
    真等这么久，把 `asyncio.sleep` 换成立即返回。"""
    async def fast_sleep(_seconds):
        return None
    monkeypatch.setattr(asyncio, "sleep", fast_sleep)


class TestEnsureReadyWaitsForManualLogin:
    def test_survives_without_a_logger(self, monkeypatch):
        _patch_sleep(monkeypatch)
        tools = _tools([LOGGED_OUT_SNAPSHOT, LOGGED_IN_SNAPSHOT])
        ensure_ready = _ensure_ready(tools, logger=None)
        result = _run(ensure_ready({"search_url": "https://example.com"}))
        assert result["snapshot_text"] == LOGGED_IN_SNAPSHOT

    def test_logs_entering_and_leaving_the_wait(self, monkeypatch):
        _patch_sleep(monkeypatch)
        tools = _tools([LOGGED_OUT_SNAPSHOT, LOGGED_IN_SNAPSHOT])
        logger = FakeLogger()
        ensure_ready = _ensure_ready(tools, logger=logger)
        _run(ensure_ready({"search_url": "https://example.com"}))

        events = [c[0] for c in logger.calls]
        assert "waiting_for_login" in events
        assert "login_detected" in events

        waiting_data = next(d for e, _, d in logger.calls if e == "waiting_for_login")
        assert waiting_data.get("url") == "https://example.com"
        assert waiting_data.get("max_wait_seconds", 0) > 0

    def test_times_out_after_ten_minutes_of_no_login(self, monkeypatch):
        _patch_sleep(monkeypatch)
        tools = _tools([LOGGED_OUT_SNAPSHOT])  # 永远不变成已登录
        ensure_ready = _ensure_ready(tools, logger=None)
        with pytest.raises(RuntimeError, match="超时"):
            _run(ensure_ready({"search_url": "https://example.com"}))


class TestEnsureReadyM1DoesNotBlockOnLogin:
    """m1（选岗）对外零副作用，站点真把岗位藏起来的话 scan_buckets/write_pending_jobs
    会诚实地找不到岗位——不需要在入口再拦一道。等 10 分钟登录的代价只对 m2（会真的
    填表/传简历）成立，m2 必须维持原有行为——见 TestEnsureReadyWaitsForManualLogin。
    """

    def test_does_not_wait_when_logged_out(self, monkeypatch):
        _patch_sleep(monkeypatch)
        tools = _tools_single_snapshot(LOGGED_OUT_SNAPSHOT)
        ensure_ready = _ensure_ready(tools, logger=None, workflow="m1")
        result = _run(ensure_ready({"search_url": "https://example.com"}))
        assert result["snapshot_text"] == LOGGED_OUT_SNAPSHOT

    def test_logs_anonymous_browsing(self, monkeypatch):
        _patch_sleep(monkeypatch)
        tools = _tools_single_snapshot(LOGGED_OUT_SNAPSHOT)
        logger = FakeLogger()
        ensure_ready = _ensure_ready(tools, logger=logger, workflow="m1")
        _run(ensure_ready({"search_url": "https://example.com"}))

        events = [c[0] for c in logger.calls]
        assert "anonymous_browsing" in events
        data = next(d for e, _, d in logger.calls if e == "anonymous_browsing")
        assert data.get("url") == "https://example.com"

    def test_survives_without_a_logger(self, monkeypatch):
        _patch_sleep(monkeypatch)
        tools = _tools_single_snapshot(LOGGED_OUT_SNAPSHOT)
        ensure_ready = _ensure_ready(tools, logger=None, workflow="m1")
        result = _run(ensure_ready({"search_url": "https://example.com"}))
        assert result["snapshot_text"] == LOGGED_OUT_SNAPSHOT

    def test_m2_still_waits_for_login(self, monkeypatch):
        """回归闸：改 m1 的路径绝不能把 m2 的等待门禁一起拆了。"""
        _patch_sleep(monkeypatch)
        tools = _tools([LOGGED_OUT_SNAPSHOT, LOGGED_IN_SNAPSHOT])
        ensure_ready = _ensure_ready(tools, logger=None, workflow="m2")
        result = _run(ensure_ready({"search_url": "https://example.com"}))
        assert result["snapshot_text"] == LOGGED_IN_SNAPSHOT
