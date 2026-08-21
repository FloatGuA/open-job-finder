"""会话列表要显示岗位名，而 `hr_conversations` 上没有它。

主路径是 `job_id` JOIN `applications`。真机 1170 条会话里：
- 607 条走通（52%）
- 425 条 `job_id` 能 JOIN 上、但 `applications.title` 是**空的**——那是
  `backfill_application_from_conversation` 造的桩行，注释写明「title 留空」
  作为"这行是重建的"的标记。不是缺陷。
- 138 条根本没有 `job_id`

这个模块管的是第三类的兜底：按公司名回查。**只在该公司只投过一个岗位时才算数**
——同一公司投过多个岗位时，挑一个填进会话的**主标题**，比留空误导得多。
真机那 138 条里 25 条能确定、22 条有歧义、91 条查无此公司。
"""
import pytest

from services.tracker import ApplicationTracker


@pytest.fixture
def tracker(tmp_path):
    t = ApplicationTracker(str(tmp_path / "t.db"))
    yield t
    t.close()


def _app(tracker, job_id, company, title):
    tracker.conn.execute(
        "INSERT INTO applications (job_id, title, company, url, status, created_at) "
        "VALUES (?, ?, ?, ?, 'APPLIED', '2026-08-01T00:00:00+00:00')",
        (job_id, title, company, f"https://x/{job_id}"))
    tracker.conn.commit()


class TestUniqueJobTitleByCompany:
    def test_one_application_gives_a_confident_answer(self, tracker):
        _app(tracker, "j1", "甲公司", "后端工程师")
        assert tracker.unique_job_title_by_company(["甲公司"]) == {"甲公司": "后端工程师"}

    def test_two_different_titles_give_nothing(self, tracker):
        """**这条是重点。** 猜错的岗位名会落在会话列表的主标题上，
        比不显示更糟——它看起来跟确定的一模一样。"""
        _app(tracker, "j1", "甲公司", "后端工程师")
        _app(tracker, "j2", "甲公司", "前端工程师")
        assert tracker.unique_job_title_by_company(["甲公司"]) == {}

    def test_the_same_title_twice_is_still_confident(self, tracker):
        """投过同一个岗位两次（重投）不构成歧义——答案唯一。"""
        _app(tracker, "j1", "甲公司", "后端工程师")
        _app(tracker, "j2", "甲公司", "后端工程师")
        assert tracker.unique_job_title_by_company(["甲公司"]) == {"甲公司": "后端工程师"}

    def test_blank_titles_do_not_count_as_a_candidate(self, tracker):
        """W2 回填的桩行 title 就是空的。空串既不该被当答案，
        也不该让一个本来唯一的答案变成"有歧义"。"""
        _app(tracker, "j1", "甲公司", "")
        _app(tracker, "j2", "甲公司", "后端工程师")
        assert tracker.unique_job_title_by_company(["甲公司"]) == {"甲公司": "后端工程师"}

    def test_only_blank_titles_give_nothing(self, tracker):
        _app(tracker, "j1", "甲公司", "")
        assert tracker.unique_job_title_by_company(["甲公司"]) == {}

    def test_unknown_company_is_absent_not_blank(self, tracker):
        assert tracker.unique_job_title_by_company(["查无此公司"]) == {}

    def test_companies_do_not_bleed_into_each_other(self, tracker):
        _app(tracker, "j1", "甲公司", "后端工程师")
        _app(tracker, "j2", "乙公司", "前端工程师")
        _app(tracker, "j3", "乙公司", "测试工程师")
        got = tracker.unique_job_title_by_company(["甲公司", "乙公司"])
        assert got == {"甲公司": "后端工程师"}

    def test_no_companies_asked_means_no_query(self, tracker):
        assert tracker.unique_job_title_by_company([]) == {}
