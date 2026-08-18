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


class TestM2InitialStateCarriesJobIdentity:
    """m2 的真实调用路径：`run_layer1` 必须把 `job_title`/`company`/`source_job_id`
    塞进**它自己构造的初始 state**，不能指望图里某个节点替它查出来——拆图后 m2
    没有 `find_jobs`/`write_pending_jobs`，没人会做这件事。

    **不手工在测试里拼好这几个字段**（`_fill_state` 那种写法早就手工把它们塞进去
    了，所以即使 `run_layer1` 从没传过这三样，那组测试也照样绿——这正是这个回归
    第一次没被抓到的原因）。这里跑的是 `run_layer1` 真实的状态构建代码，只在
    "开真 Chrome" 这一层拿假对象截断。
    """

    @pytest.fixture()
    def fake_chrome(self, monkeypatch):
        import multisite.chrome_mcp_client as ccm

        class _Session:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *a):
                return False

        async def fake_get_tools(session):
            return []

        monkeypatch.setattr(ccm, "build_client", lambda *a, **kw: object())
        monkeypatch.setattr(ccm, "open_session", lambda client: _Session())
        monkeypatch.setattr(ccm, "get_tools", fake_get_tools)

    def test_job_identity_reaches_record_application(self, tracker, fake_chrome, monkeypatch,
                                                     tmp_path):
        import asyncio

        import multisite.layer1_agent as la

        job_id = tracker.add_pending_job(site_name="s", url="https://x/1",
                                         title="真实标题", company="真实公司")
        tracker.decide_pending_job(job_id, "approved")

        captured_state = {}

        class _FakeApp:
            async def ainvoke(self, state):
                # 记下 run_layer1 真正构造并喂进图的初始 state——这是本测试要盯的
                # 那一份。后面手动补上"扫到一个必填空字段"，模拟 open_application /
                # scan_and_classify_fields 跑完之后的形状，让流程走到 record_application
                # 的落库分支（`record_application` 本身另有单测，这里不重复验证它的
                # 落库细节，只验证它拿到的 state 里 job_title/company/source_job_id
                # 是不是空的）。
                captured_state.update(state)
                filled = dict(state,
                              empty_elements=[{"uid": "1", "role": "textbox",
                                               "label": "学校", "required": True}],
                              classified_fields=[])
                return la.record_application(tracker, filled, {})

        monkeypatch.setattr(la, "build_survey_graph", lambda *a, **kw: _FakeApp())

        # m2 要求给简历（它的活儿就是往企业系统传简历，没简历这一步没有意义），
        # 所以这里造一个真文件——`staged_resume` 会真的复制它。
        resume = tmp_path / "resume.pdf"
        resume.write_bytes(b"%PDF-1.4 fake")

        state = asyncio.run(la.run_layer1(
            workflow="m2", site_name="s", job_url="https://x/1",
            resume_pdf_path=str(resume),
            tracker=tracker, job_title="真实标题", company="真实公司",
            source_job_id=job_id,
        ))

        # run_layer1 真的把这三样放进了它喂给图的初始 state 里。
        assert captured_state["job_title"] == "真实标题"
        assert captured_state["company"] == "真实公司"
        assert captured_state["source_job_id"] == job_id

        # 落库结果不是空值——这才是最终会被写进 pending_applications 表的东西。
        app = tracker.get_pending_application(state["pending_application_id"])
        assert app.job_title == "真实标题"
        assert app.company == "真实公司"
        assert app.source_job_id == job_id
