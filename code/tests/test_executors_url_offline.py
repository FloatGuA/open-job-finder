"""不碰浏览器就能取到 URL 的两种站点形状。

分成 offline / online 两个函数**不是为了好看**：offline 这两种可以纯单测，
online 那种要 fake 浏览器工具。混在一个函数里，可测的那部分就被不可测的部分拖下水了。
"""
import pytest

from multisite.executors import JobRow, job_url_offline
from multisite.site_manual import SiteManual


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
