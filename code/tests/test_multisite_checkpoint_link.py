"""Checkpoint 2 的记录要认得出自己来自 Checkpoint 1 的哪个岗位。

**断言的是库里最终那条记录**，不是某个辅助函数的返回值：这条链路真正会断的地方
是"算出来了但没往下传"，而只测辅助函数恰恰漏掉那一段。
"""
import pytest

from multisite.layer1_agent import FoundJob, record_application, record_candidates
from services.tracker import ApplicationTracker


@pytest.fixture()
def tracker(tmp_path):
    return ApplicationTracker(db_path=str(tmp_path / "t.db"))


def _fill_state(job_url: str) -> dict:
    """m2 走到写库那一步时 state 里该有的东西（必填字段、无候选值）。"""
    return {"site_name": "s", "job_url": job_url, "job_title": "t", "company": "c",
            "empty_elements": [{"uid": "1", "role": "textbox", "label": "学校",
                                "required": True}],
            "classified_fields": [], "form_screenshot": ""}


class TestApplicationPointsBackToItsJob:
    def test_link_survives_the_whole_m2_path(self, tracker):
        """m2 的完整路径：岗位早就在库里（审批过的），选岗阶段只是"又找到"它。

        这条是主路径——**url 去重每次都命中**，所以回指不能依赖"这次新插入的 id"。
        """
        job_id = tracker.add_pending_job(site_name="s", url="https://x/1", title="t")
        tracker.decide_pending_job(job_id, "approved")

        state = {"site_name": "s", "found_jobs": [FoundJob(url="https://x/1")]}
        state.update(record_candidates(tracker, state))
        state.update(_fill_state("https://x/1"))
        app_id = record_application(tracker, state, personal_info={})["pending_application_id"]

        assert tracker.get_pending_application(app_id).source_job_id == job_id

    def test_debug_path_without_a_candidate_records_no_link(self, tracker):
        """`--job-url` 直接指定一个不在 pending_jobs 里的岗位是合法的调试用法。
        这时回指为空是**诚实**，不是缺数据——绝不能编一个 id 出来。"""
        state = _fill_state("https://x/never-selected")
        app_id = record_application(tracker, state, personal_info={})["pending_application_id"]

        assert tracker.get_pending_application(app_id).source_job_id is None

    def test_link_is_to_the_job_being_processed(self, tracker):
        """一次 run 可能选出一批岗位，但只有 `found_jobs[0]` 会被打开、填表。
        回指必须是它，指到别的岗位比不指更糟——审批人会对着错误的岗位做判断。"""
        first = tracker.add_pending_job(site_name="s", url="https://x/a", title="a")
        tracker.add_pending_job(site_name="s", url="https://x/b", title="b")

        state = {"site_name": "s", "found_jobs": [FoundJob(url="https://x/a"),
                                                  FoundJob(url="https://x/b")]}
        state.update(record_candidates(tracker, state))
        state.update(_fill_state("https://x/a"))
        app_id = record_application(tracker, state, personal_info={})["pending_application_id"]

        assert tracker.get_pending_application(app_id).source_job_id == first


class TestCandidatesStillLandInTheirOwnTable:
    """回指是顺带的，Checkpoint 1 自己的落库行为不能被改坏。"""

    def test_new_jobs_are_inserted(self, tracker):
        state = {"site_name": "s", "found_jobs": [FoundJob(url="https://x/1", title="t")]}
        out = record_candidates(tracker, state)
        assert len(out["pending_job_ids"]) == 1
        assert [j.url for j in tracker.get_pending_jobs()] == ["https://x/1"]

    def test_already_known_url_is_not_duplicated(self, tracker):
        tracker.add_pending_job(site_name="s", url="https://x/1", title="t")
        state = {"site_name": "s", "found_jobs": [FoundJob(url="https://x/1")]}
        out = record_candidates(tracker, state)
        assert out["pending_job_ids"] == []          # 没有新行
        assert len(tracker.get_pending_jobs()) == 1  # 也没重复插
