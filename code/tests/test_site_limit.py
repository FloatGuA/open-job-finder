"""站点投递数量上限的测试。

**这组测试守的核心是三态**：`unknown`（没找到相关说明）必须跟 `no_limit`（页面明确
写了不限）分开。只存一个可空数字的话，`None` 会同时意味着两者，页面上就会显示成
"无限制"，然后人放心批十个——而真实上限可能是 3。这跟项目里记过的
「covered 三态：没失败≠验证到了」是同一个坑，只是换了个地方。
"""
import asyncio

import pytest

from multisite.layer1_agent import make_record_site_limit_tool
from services.tracker import ApplicationTracker


@pytest.fixture()
def tracker(tmp_path):
    return ApplicationTracker(db_path=str(tmp_path / "t.db"))


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _call(tracker, site="bambulab", **kw):
    tool = make_record_site_limit_tool(tracker, site)
    payload = {"status": "limited", "evidence": "校招每人最多投递 3 个岗位"}
    payload.update(kw)
    return _run(tool.ainvoke(payload))


class TestTracker:
    def test_missing_site_returns_none_not_a_default(self, tracker):
        # 返回一个 status='unknown' 的默认对象会让"从没跑过"和"跑过但没看到"
        # 长得一样；调用方需要能区分。
        assert tracker.get_site_limit("nope") is None

    def test_limited_roundtrip(self, tracker):
        tracker.upsert_site_limit("s", "limited", max_applications=3,
                                  applied_count=1, evidence="原文")
        got = tracker.get_site_limit("s")
        assert (got.status, got.max_applications, got.applied_count) == ("limited", 3, 1)
        assert got.evidence == "原文" and got.seen_at

    def test_no_limit_is_distinct_from_unknown(self, tracker):
        tracker.upsert_site_limit("s", "no_limit", evidence="不限投递数量")
        got = tracker.get_site_limit("s")
        assert got.status == "no_limit"
        assert got.max_applications is None

    def test_unknown_never_overwrites_a_known_result(self, tracker):
        """agent 是机会性发现的，每次跑都可能没看到那段说明。如果"这次没看见"
        能把上次真读到的 limited(3) 冲掉，这张表就永远停在 unknown——已知被无知
        覆盖是净损失。
        """
        tracker.upsert_site_limit("s", "limited", max_applications=3, evidence="e")
        tracker.upsert_site_limit("s", "unknown")

        got = tracker.get_site_limit("s")
        assert got.status == "limited" and got.max_applications == 3

    def test_a_new_known_result_does_overwrite(self, tracker):
        # 站点真的改了规则时要能更新——只有 unknown 是不覆盖的那个特例。
        tracker.upsert_site_limit("s", "limited", max_applications=3, evidence="e1")
        tracker.upsert_site_limit("s", "limited", max_applications=5, evidence="e2")
        assert tracker.get_site_limit("s").max_applications == 5

    def test_invalid_status_raises(self, tracker):
        with pytest.raises(AssertionError):
            tracker.upsert_site_limit("s", "maybe")


class TestRecordSiteLimitTool:
    def test_records_a_limit(self, tracker):
        result = _call(tracker, limit=3)
        assert "最多 3" in result
        assert tracker.get_site_limit("bambulab").max_applications == 3

    def test_records_no_limit(self, tracker):
        _call(tracker, status="no_limit", evidence="不限制投递数量")
        assert tracker.get_site_limit("bambulab").status == "no_limit"

    def test_records_applied_count_when_seen(self, tracker):
        _call(tracker, limit=3, applied_count=1)
        assert tracker.get_site_limit("bambulab").applied_count == 1

    def test_applied_count_defaults_to_not_seen(self, tracker):
        _call(tracker, limit=3)
        assert tracker.get_site_limit("bambulab").applied_count == -1

    def test_rejects_unknown_status(self, tracker):
        """agent 不该报 unknown——"没看到"就是不调用这个工具。允许它报 unknown
        会诱导它在每次跑完都调一次"我没看到"，白烧一步还可能覆盖已知结果。"""
        result = _call(tracker, status="unknown")
        assert "记录失败" in result
        assert tracker.get_site_limit("bambulab") is None

    def test_rejects_limited_without_a_number(self, tracker):
        result = _call(tracker, limit=0)
        assert "记录失败" in result
        assert tracker.get_site_limit("bambulab") is None

    @pytest.mark.parametrize("blank", ["", "   "])
    def test_rejects_empty_evidence(self, tracker, blank):
        # 原文是这条信息唯一可核对的部分；没有它就只是 agent 的一句话。
        result = _call(tracker, limit=3, evidence=blank)
        assert "记录失败" in result
        assert tracker.get_site_limit("bambulab") is None

    def test_evidence_is_capped(self, tracker):
        _call(tracker, limit=3, evidence="x" * 2000)
        assert len(tracker.get_site_limit("bambulab").evidence) <= 500


class TestClearSiteLimit:
    """人工把一条上限退回「未知」。

    **为什么是删行、不是 upsert 成 unknown**：`upsert_site_limit` 刻意让 unknown
    不覆盖已知（防 agent 用"这次没看见"冲掉上次真读到的数字），人工重置要的正是
    绕过那条保护。这段 SQL 以前内联在端点里——同一张表的写入散在两层，正是本项目
    连抓四例漂移的形状。
    """

    def test_removes_the_row(self, tracker):
        tracker.upsert_site_limit("s", "limited", max_applications=3, evidence="原文")
        assert tracker.clear_site_limit("s") == 1
        assert tracker.get_site_limit("s") is None

    def test_missing_row_is_a_noop_not_an_error(self, tracker):
        assert tracker.clear_site_limit("never-seen") == 0

    def test_only_touches_the_named_scope(self, tracker):
        """一个站可以有好几条互不相干的上限（按招聘项目分），清一条不能连坐。"""
        tracker.upsert_site_limit("s", "limited", scope="site", max_applications=5,
                                  evidence="全站")
        tracker.upsert_site_limit("s", "limited", scope="bucket", scope_name="研发类",
                                  max_applications=2, evidence="研发类")
        tracker.clear_site_limit("s", "研发类")
        assert tracker.get_site_limit("s", "研发类") is None
        assert tracker.get_site_limit("s").max_applications == 5

    def test_upsert_can_write_again_after_clearing(self, tracker):
        # 清空 = 回到"什么都没记到"，跟从没跑过这个站是同一个状态；下次 agent
        # 看到说明时要能正常写进来（这也是 unknown-不覆盖保护该放行的场景）。
        tracker.upsert_site_limit("s", "limited", max_applications=3, evidence="旧")
        tracker.clear_site_limit("s")
        tracker.upsert_site_limit("s", "unknown")
        assert tracker.get_site_limit("s").status == "unknown"
