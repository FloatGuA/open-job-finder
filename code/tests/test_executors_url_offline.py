"""不碰浏览器就能取到 URL 的两种站点形状。

分成 offline / online 两个函数**不是为了好看**：offline 这两种可以纯单测，
online 那种要 fake 浏览器工具。混在一个函数里，可测的那部分就被不可测的部分拖下水了。
"""
from pathlib import Path

import pytest

from multisite.executors import JobRow, job_url_offline, split_rows
from multisite.site_manual import SiteManual

FIXTURE = (Path(__file__).parent / "fixtures" / "joinqq_post_list.txt").read_text(encoding="utf-8")


def _manual(**over) -> SiteManual:
    d = {"job_url_source": "link_in_row", "url_template": "", "pagination": "none",
         "filter_interaction": "direct_click", "filters_survive_reload": False,
         "total_count_locator": "", "row_split": "anchor_text",
         "row_anchor": "地点", "dimensions": [], "important_notes": ""}
    d.update(over)
    return SiteManual.from_dict(d)


ROW_SNAPSHOT = (
    '## Latest page snapshot\n'
    'uid=1_0 RootWebArea "岗位列表" url="https://example.com/jobs"\n'
    'uid=1_5 link "后端开发工程师" url="https://example.com/job/12345"\n'
    'uid=1_6 StaticText "地点"\n'
)


class TestLinkInRow:
    def test_reads_the_url_from_the_row(self):
        row = JobRow(anchor_uid="1_6", text="后端开发工程师 地点")
        assert job_url_offline(row, ROW_SNAPSHOT, _manual()) == "https://example.com/job/12345"

    def test_row_without_a_link_returns_none(self):
        """**返回 None，不要返回空串**：调用方要能区分"这一行没有链接"和"链接是空的"。
        None 会被 harvest 记成"这条取 URL 失败"并计数，空串会被当成合法 URL 写进库。"""
        snap = '## Latest page snapshot\nuid=1_6 StaticText "地点"\n'
        assert job_url_offline(JobRow(anchor_uid="1_6", text="x"), snap, _manual()) is None

    def test_real_fixture_rows_without_a_link_return_none_not_the_footer_link(self):
        """FIX-2 回归测试：真实 fixture（join.qq.com 的 10 个岗位行）里每一行都只有
        StaticText，没有 link 节点。旧实现从快照开头一路扫到锚点，取"最近见到的带 url
        的 link"——快照里锚点之前永远有导航栏/页脚链接，所以实测**10 行全部**返回同一个
        页脚链接 `https://join.qq.com/about.html`（"部门介绍"）。3 行的玩具快照测不出这个
        bug，因为那份快照里唯一的链接恰好就是那一行自己的——必须用真实尺寸的 fixture。"""
        manual = _manual(row_split="anchor_text", row_anchor="工作地点：")
        rows = split_rows(FIXTURE, manual)
        assert len(rows) == 10  # 真机这一页恰好 10 个岗位

        for row in rows:
            url = job_url_offline(row, FIXTURE, manual)
            assert url is None, f"行 {row.anchor_uid} 没有链接，不该返回 {url!r}"
            assert url != "https://join.qq.com/about.html"


class TestIdTemplate:
    def test_fills_the_template_with_the_id_found_in_the_row(self):
        row = JobRow(anchor_uid="1_6", text="后端开发工程师 编号 98765 地点")
        manual = _manual(job_url_source="id_template",
                         url_template="https://example.com/detail?id={id}")
        assert job_url_offline(row, ROW_SNAPSHOT, manual) == "https://example.com/detail?id=98765"

    def test_row_without_a_number_returns_none(self):
        manual = _manual(job_url_source="id_template",
                         url_template="https://example.com/detail?id={id}")
        row = JobRow(anchor_uid="1_6", text="后端开发工程师 地点")
        assert job_url_offline(row, ROW_SNAPSHOT, manual) is None


class TestNewTabIsNotHandledHere:
    def test_it_raises_so_the_caller_uses_the_online_path(self):
        """静默返回 None 会让调用方以为"这一行没有 URL"，而真相是"你用错函数了"。"""
        manual = _manual(job_url_source="new_tab_on_click")
        with pytest.raises(ValueError, match="new_tab_on_click"):
            job_url_offline(JobRow(anchor_uid="1_6", text="x"), ROW_SNAPSHOT, manual)


class TestUnknownJobUrlSourceRaises:
    def test_unknown_source_raises_instead_of_falling_through_to_id_template(self):
        """`from_dict` 的闭集校验让未知的 `job_url_source` 理论上不可达，但"不可达"
        是靠**另一个函数**保证的——直接构造 dataclass（本测试就是这么做的）能绕过它。
        `job_url_offline` 自己也要显式拒绝，不能隐式落进 `id_template` 分支。"""
        manual = SiteManual(job_url_source="scrape_the_api", pagination="none",
                            filter_interaction="direct_click", row_split="anchor_text",
                            row_anchor="地点")
        row = JobRow(anchor_uid="1_6", text="x")
        with pytest.raises(ValueError, match="scrape_the_api"):
            job_url_offline(row, ROW_SNAPSHOT, manual)
