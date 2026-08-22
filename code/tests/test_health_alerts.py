"""「有东西坏了但没人发现」的信号。

这个系统的卖点是"不用盯着也能跑"，而 session 过期 / Boss 改版选择器失效 /
调度器不再触发，任何一个都可能**安静地跑好几天**——日志里全是记录，只是没人翻。

**渠道选的是 Dashboard**（用户 2026-08-22：别的都要接 MCP，更复杂）。
它的边界要说清楚：**解决不了"三天没打开"**，解决的是"打开了但没看出来有问题"。

**误报率决定它的存活率。** 本项目已经在 `precommit_pii_scan` 上学过一次：
误报 → 用户开始无视 → 防线归零。所以这里的判据一律偏保守，宁可漏报：
没启用定时的 workflow 一律不报（用户压根没打算让它自动跑）。
"""
from datetime import datetime, timedelta, timezone

from services.health_alerts import detect_alerts

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
ENABLED = {"apply": {"enabled": True}, "check": {"enabled": True}}
DISABLED = {"apply": {"enabled": False}, "check": {"enabled": False}}


def _entry(wf, result, days_ago=0, **kw):
    return {"workflow": wf, "result": result,
            "triggered_at": (NOW - timedelta(days=days_ago)).isoformat(), **kw}


def _ids(alerts):
    return {a["id"] for a in alerts}


class TestConsecutiveFailures:
    def test_two_failures_in_a_row_raise_it(self):
        log = [_entry("apply", "error", 1), _entry("apply", "error", 0)]
        assert "apply:consecutive_failures" in _ids(
            detect_alerts(schedule_log=log, selfcheck_log=[], schedule=ENABLED, now=NOW))

    def test_one_failure_is_not_enough(self):
        """单次失败太常见了（网络抖一下）。报它 = 天天报 = 没人看。"""
        log = [_entry("apply", "success", 1), _entry("apply", "error", 0)]
        assert "apply:consecutive_failures" not in _ids(
            detect_alerts(schedule_log=log, selfcheck_log=[], schedule=ENABLED, now=NOW))

    def test_a_success_after_the_failures_clears_it(self):
        log = [_entry("apply", "error", 2), _entry("apply", "error", 1),
               _entry("apply", "success", 0)]
        assert "apply:consecutive_failures" not in _ids(
            detect_alerts(schedule_log=log, selfcheck_log=[], schedule=ENABLED, now=NOW))

    def test_skipped_neither_breaks_nor_counts(self):
        """`skipped` 是"今天撞了配额，没跑"——它既不是失败，也不代表恢复正常。
        当成成功会掩盖连续失败，当成失败会在正常限流时误报。"""
        log = [_entry("apply", "error", 2), _entry("apply", "skipped", 1),
               _entry("apply", "error", 0)]
        assert "apply:consecutive_failures" in _ids(
            detect_alerts(schedule_log=log, selfcheck_log=[], schedule=ENABLED, now=NOW))

    def test_workflows_are_counted_separately(self):
        log = [_entry("apply", "error", 1), _entry("check", "success", 1),
               _entry("apply", "error", 0), _entry("check", "success", 0)]
        got = _ids(detect_alerts(schedule_log=log, selfcheck_log=[],
                                 schedule=ENABLED, now=NOW))
        assert "apply:consecutive_failures" in got
        assert "check:consecutive_failures" not in got


class TestNothingSucceededInAWhile:
    """**这条是最值钱的**：它不管失败长什么样，只问"上一次真的正常是什么时候"。
    调度器不再触发、每次都失败、session 过期——全都会落到这一条上。"""

    def test_no_success_within_the_window(self):
        log = [_entry("apply", "success", 5)]
        assert "apply:stale" in _ids(
            detect_alerts(schedule_log=log, selfcheck_log=[], schedule=ENABLED,
                          now=NOW, stale_days=2))

    def test_a_recent_success_is_fine(self):
        log = [_entry("apply", "success", 1)]
        assert "apply:stale" not in _ids(
            detect_alerts(schedule_log=log, selfcheck_log=[], schedule=ENABLED,
                          now=NOW, stale_days=2))

    def test_never_ran_at_all_counts_as_stale(self):
        """开了定时却一条记录都没有 —— 调度器根本没在跑。"""
        assert "apply:stale" in _ids(
            detect_alerts(schedule_log=[], selfcheck_log=[], schedule=ENABLED, now=NOW))

    def test_failures_do_not_count_as_activity(self):
        """一直在跑但一直失败，仍然是"很久没有真的正常过"。"""
        log = [_entry("apply", "error", 0), _entry("apply", "success", 9)]
        assert "apply:stale" in _ids(
            detect_alerts(schedule_log=log, selfcheck_log=[], schedule=ENABLED,
                          now=NOW, stale_days=2))


class TestFalsePositivesAreTheRealRisk:
    def test_a_disabled_workflow_is_never_reported(self):
        """**误报率＝存活率。** 用户没开定时，就是没打算让它自动跑，
        报"两天没成功"是纯噪音——而噪音会让人开始无视整块横幅。"""
        assert detect_alerts(schedule_log=[], selfcheck_log=[],
                             schedule=DISABLED, now=NOW) == []

    def test_a_disabled_workflow_with_old_failures_is_still_silent(self):
        log = [_entry("apply", "error", 3), _entry("apply", "error", 2)]
        assert detect_alerts(schedule_log=log, selfcheck_log=[],
                             schedule=DISABLED, now=NOW) == []


class TestSelfcheck:
    def test_the_last_selfcheck_failing_is_reported(self):
        checks = [{"ok": True, "started_at": (NOW - timedelta(days=1)).isoformat()},
                  {"ok": False, "started_at": NOW.isoformat()}]
        assert "selfcheck:failing" in _ids(
            detect_alerts(schedule_log=[], selfcheck_log=checks,
                          schedule=DISABLED, now=NOW))

    def test_an_older_failure_that_since_passed_is_not_reported(self):
        checks = [{"ok": False, "started_at": (NOW - timedelta(days=1)).isoformat()},
                  {"ok": True, "started_at": NOW.isoformat()}]
        assert "selfcheck:failing" not in _ids(
            detect_alerts(schedule_log=[], selfcheck_log=checks,
                          schedule=DISABLED, now=NOW))


class TestShape:
    def test_every_alert_says_what_and_how_bad(self):
        log = [_entry("apply", "error", 1), _entry("apply", "error", 0)]
        for a in detect_alerts(schedule_log=log, selfcheck_log=[],
                               schedule=ENABLED, now=NOW):
            assert a["level"] in ("error", "warn")
            assert a["title"] and a["detail"]

    def test_unparsable_timestamps_do_not_blow_up_the_endpoint(self):
        """日志是追加写的文本，历史上出现过半截行。告警是**诊断工具**，
        它自己因为一行坏数据就 500，恰恰是在最需要它的时候失灵。"""
        log = [{"workflow": "apply", "result": "success", "triggered_at": "不是时间"}]
        detect_alerts(schedule_log=log, selfcheck_log=[], schedule=ENABLED, now=NOW)
