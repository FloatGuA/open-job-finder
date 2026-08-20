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


def _ensure_ready(tools, logger):
    nodes, _ = _make_nodes(tools, personal_info={}, tracker=FakeTracker(),
                           quotas={}, logger=logger)
    return nodes["ensure_ready"][0]


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
