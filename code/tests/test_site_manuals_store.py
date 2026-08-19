"""手册的持久化。与 site_briefs **并存**，不是替代。

职责分开：手册＝本轮可执行的事实（结构化，代码消费），brief＝跨轮经验笔记
（自由文本，喂进 prompt 给模型看，明确标注可能过期）。
"""
import pytest

from multisite.site_manual import SiteManual
from services.tracker import ApplicationTracker


@pytest.fixture()
def tracker(tmp_path):
    return ApplicationTracker(db_path=str(tmp_path / "t.db"))


def _manual(anchor="工作地点：") -> SiteManual:
    return SiteManual.from_dict({
        "job_url_source": "new_tab_on_click", "url_template": "", "pagination": "next_button",
        "filter_interaction": "expand_group_then_click", "filters_survive_reload": False,
        "total_count_locator": r"共(\d+)个岗位", "row_split": "anchor_text",
        "row_anchor": anchor, "dimensions": [{"name": "工作城市", "options": ["深圳"],
                                              "multi_select": True}],
        "important_notes": ""})


class TestSiteManualStore:
    def test_missing_site_returns_none(self, tracker):
        assert tracker.get_site_manual("从来没跑过的站") is None

    def test_round_trips(self, tracker):
        tracker.upsert_site_manual("joinqq", _manual())
        got, updated_at = tracker.get_site_manual("joinqq")
        assert got.to_dict() == _manual().to_dict()
        assert updated_at

    def test_upsert_overwrites_and_bumps_updated_at(self, tracker):
        tracker.upsert_site_manual("joinqq", _manual())
        first = tracker.get_site_manual("joinqq")[1]
        tracker.upsert_site_manual("joinqq", _manual(anchor="工作城市："))
        got, second = tracker.get_site_manual("joinqq")
        assert got.row_anchor == "工作城市："
        assert second >= first

    def test_sites_do_not_leak_into_each_other(self, tracker):
        tracker.upsert_site_manual("joinqq", _manual())
        tracker.upsert_site_manual("bambulab", _manual(anchor="Location"))
        assert tracker.get_site_manual("joinqq")[0].row_anchor == "工作地点："
        assert tracker.get_site_manual("bambulab")[0].row_anchor == "Location"


class TestBriefIsUntouched:
    def test_manual_and_brief_coexist(self, tracker):
        """两者并存是**有意的职责分离**，不是冗余。谁要把
        brief 删了合并进手册，这条会红。"""
        tracker.upsert_site_manual("joinqq", _manual())
        tracker.upsert_site_brief("joinqq", "这个站要登录，筛选器在顶部")
        assert tracker.get_site_manual("joinqq")[0].row_anchor == "工作地点："
        assert "要登录" in tracker.get_site_brief("joinqq").brief
