"""`analysis_state` 派生：UI 显示的「这次分析成没成」必须与流水线的真实行为一致。

背景：LLM 失败时 AnalyzeStep 刻意不写库（不污染数据、不推进水位线，下轮才会重试），
代价是 intent 列留着旧值。这个派生字段就是用来分辨旧值的——所以它的分支必须严格
镜像 `filter_conversations`，否则 UI 会承诺一件流水线不会做的事。
"""
import time
from types import SimpleNamespace

from dashboard.server import _analysis_state
from tools.biz_logic.filter_conversations import FilterConversations

DAY_MS = 86400 * 1000
WINDOW = 14


def _conv(last_msg_ts: int, last_analyzed_ts: int):
    return SimpleNamespace(last_msg_ts=last_msg_ts, last_analyzed_ts=last_analyzed_ts)


def _now_ms() -> int:
    return int(time.time() * 1000)


def test_watermark_caught_up_is_ok():
    ts = _now_ms()
    assert _analysis_state(_conv(ts, ts), WINDOW) == "ok"


def test_watermark_ahead_is_ok():
    """分析水位线可以领先（分析后没有新消息）——不是异常。"""
    ts = _now_ms()
    assert _analysis_state(_conv(ts - 1000, ts), WINDOW) == "ok"


def test_watermark_behind_inside_window_is_pending():
    """上轮分析失败且会话仍活跃 → 下轮会重试。"""
    ts = _now_ms() - 2 * DAY_MS
    assert _analysis_state(_conv(ts, ts - 5000), WINDOW) == "pending"


def test_watermark_behind_outside_window_is_stale():
    """超出活跃窗口 → too_old 优先于 unanalyzed，永远不会再分析。"""
    ts = _now_ms() - 40 * DAY_MS
    assert _analysis_state(_conv(ts, ts - 5000), WINDOW) == "stale"


def test_no_window_gate_never_reports_stale():
    """窗口为 0 = 关闭闸门，此时没有「不会再分析」这回事。"""
    ts = _now_ms() - 400 * DAY_MS
    assert _analysis_state(_conv(ts, ts - 5000), 0) == "pending"


def test_zero_timestamp_is_ok_not_pending():
    """没有真实时间戳的行，脏检查同样不会挑它——UI 不能显示成「下轮会重试」。"""
    assert _analysis_state(_conv(0, 0), WINDOW) == "ok"


def test_missing_attributes_default_to_ok():
    assert _analysis_state(SimpleNamespace(), WINDOW) == "ok"


# ── 与 filter_conversations 的一致性守门 ────────────────────────────────────
# 这才是真正重要的测试：UI 说「下轮会重试」，filter 就必须真的挑它。

def _filter_action(last_msg_ts: int, last_analyzed_ts: int) -> str:
    """跑真实的 filter，返回它对这个会话的处置。"""
    tool = FilterConversations()
    convs = [{"conv_id": "c1", "hr_name": "张三", "company": "甲公司",
              "last_msg_ts": last_msg_ts, "unread": 0, "preview": "hi"}]
    states = {"c1": {"last_analyzed_ts": last_analyzed_ts, "last_msg_preview": "hi",
                     "reply_status": None, "stage": "active"}}
    res = tool.execute(
        current_convs=convs, stored_states=states,
        approved_reply_ids=[], active_window_days=WINDOW,
    )
    picked = {c["conv_id"] for c in res.data["conversations_to_process"]}
    return "process" if "c1" in picked else "skip"


def test_pending_means_filter_actually_reprocesses():
    ts = _now_ms() - 2 * DAY_MS
    assert _analysis_state(_conv(ts, ts - 5000), WINDOW) == "pending"
    assert _filter_action(ts, ts - 5000) == "process", "UI 说会重试，filter 就必须真的挑它"


def test_stale_means_filter_really_skips():
    ts = _now_ms() - 40 * DAY_MS
    assert _analysis_state(_conv(ts, ts - 5000), WINDOW) == "stale"
    assert _filter_action(ts, ts - 5000) == "skip", "UI 说不会再分析，filter 就必须真的跳过"
