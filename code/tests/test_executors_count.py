"""「共 N 个岗位」是整个试探机制的 oracle。

判定筛选维度是多选还是互斥，**只能靠「勾一个 → 回读总数」**——a11y 快照里根本没有
勾选状态（真机实测：整张快照 0 处 `checked`）。这个数字没了，`survey_structure`
就失去了唯一可靠的反馈信号。
"""
from pathlib import Path

from multisite.executors import read_total_count
from multisite.site_manual import SiteManual

SNAPSHOT = (Path(__file__).parent / "fixtures" / "joinqq_post_list.txt").read_text(encoding="utf-8")


def _manual(locator: str) -> SiteManual:
    return SiteManual.from_dict({
        "job_url_source": "new_tab_on_click", "url_template": "", "pagination": "next_button",
        "filter_interaction": "expand_group_then_click", "filters_survive_reload": False,
        "total_count_locator": locator, "row_split": "anchor_text",
        "row_anchor": "工作地点：", "dimensions": [], "important_notes": ""})


class TestReadTotalCount:
    def test_reads_the_real_count(self):
        assert read_total_count(SNAPSHOT, _manual(r"共(\d+)个岗位")) == 940

    def test_missing_locator_returns_none_not_zero(self):
        """**None 和 0 语义完全不同**：None＝这个站没有计数（试探判定要退化成数行数），
        0＝筛得一个岗位都不剩（是个有效结果）。合并成 0 会让「筛太窄」和「读不到」
        变得无法区分。"""
        assert read_total_count(SNAPSHOT, _manual("")) is None

    def test_locator_that_matches_nothing_returns_none(self):
        assert read_total_count(SNAPSHOT, _manual(r"共(\d+)个职位")) is None

    def test_locator_without_a_capture_group_returns_none(self):
        """手册写错正则（忘了捕获组）现在会在 `SiteManual.from_dict` 的边界被 fail fast
        拦下（见 test_site_manual.py `TestTotalCountLocatorMustBeValidRegex`），所以这里
        绕过 `from_dict`、直接用 dataclass 构造函数，只测 `read_total_count` 自己那道
        兜底还在——**表现为 None，不要抛**，防的是万一将来有路径绕开 `from_dict`
        送进来一个没有捕获组的正则，整条 run 不该因此崩掉。"""
        manual = SiteManual(job_url_source="new_tab_on_click", pagination="next_button",
                            row_split="anchor_text", row_anchor="工作地点：",
                            total_count_locator=r"共\d+个岗位")
        assert read_total_count(SNAPSHOT, manual) is None
