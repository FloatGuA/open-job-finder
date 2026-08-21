"""m2 发哪一份简历，以及发不出去时怎么办。

**设计哲学（用户 2026-08-16 定）**：「Agent 自己生成是我们做好了但是拦住了的窗口，
目前往外发尽量还是用人工做的精美简历」。所以这里**宁可不跑，也不凑合发一份**——
选中的简历没有一份对得上的已导出 PDF 时，就明确告诉人去导出，而不是悄悄换一份。

对照 W2 那条线：它的规则是"绝不漏发，没导出就回退站内简历"，因为 Boss 有站内简历
兜底。多站点**没有兜底**，传错一份的后果是它躺在企业系统的表单里。
"""
import os
import time

import pytest

from services.resume_store import ResumeStore
from services.workflow_orchestration import OrchestrationService


class _FakeEmitter:
    def __init__(self):
        self.current_workflow = None


class _FakeState:
    def __init__(self, tracker):
        self.tracker = tracker
        self.emitter = _FakeEmitter()
        self.model_router = object()


@pytest.fixture()
def tracker(tmp_path):
    from services.tracker import ApplicationTracker
    return ApplicationTracker(db_path=str(tmp_path / "t.db"))


@pytest.fixture()
def data_dir(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    return d


@pytest.fixture()
def service(data_dir, tracker):
    return OrchestrationService(
        get_state=lambda: _FakeState(tracker),
        ensure_state=lambda: None,
        data_dir=data_dir,
        write_schedule_log=lambda e: None,
        write_selfcheck_log=lambda e: None,
        smoke_log_path=data_dir / "smoke.jsonl",
    )


@pytest.fixture()
def captured(monkeypatch):
    import multisite.layer1_agent as la
    calls = []

    async def fake_run_layer1(**kwargs):
        calls.append(kwargs)
        return {"found_jobs": [], "pending_job_ids": [], "open_result": None,
                "classified_fields": [], "pending_application_id": None}

    monkeypatch.setattr(la, "run_layer1", fake_run_layer1)
    return calls


def _approved_job(tracker, title: str) -> int:
    job_id = tracker.add_pending_job(site_name="s", url=f"https://x/{title}", title=title)
    tracker.decide_pending_job(job_id, "approved")
    return job_id


def _export(store: ResumeStore, slug: str, name: str, offset: int = 60) -> None:
    os.makedirs(store.exports_dir, exist_ok=True)
    ts = time.strftime("%Y%m%d_%H%M%S", time.localtime(time.time() + offset))
    with open(os.path.join(store.exports_dir, f"{ts}_{slug}_{name}.pdf"), "wb") as f:
        f.write(b"%PDF-1.4")


class TestPicksByJob:
    def test_uses_the_resume_matching_the_job_not_the_newest_export(self, service, tracker,
                                                                    data_dir, captured):
        """此前用的是「最近导出的那份」——一个跟岗位毫无关系的时间属性。"""
        store = ResumeStore(str(data_dir))
        game = store.create("游戏岗版", target="游戏 客户端")
        agent = store.create("AI Agent 开发版", target="AI Agent LLM")
        _export(store, game["slug"], "游戏岗版")
        _export(store, agent["slug"], "AI_Agent")

        service._run_multisite_fill({"pending_job_id": _approved_job(tracker, "游戏客户端开发")})

        assert game["slug"] in captured[0]["resume_pdf_path"]


class TestRefusesWhenThePdfIsNotUsable:
    def test_refuses_when_the_matched_resume_was_never_exported(self, service, tracker,
                                                                data_dir, captured):
        store = ResumeStore(str(data_dir))
        store.create("游戏岗版", target="游戏 客户端")

        with pytest.raises(ValueError) as exc:
            service._run_multisite_fill({"pending_job_id": _approved_job(tracker, "游戏客户端开发")})

        assert "游戏岗版" in str(exc.value)      # 告诉人该去导哪一份
        assert captured == []                    # 一步都没跑

    def test_refuses_when_the_pdf_is_older_than_the_resume(self, service, tracker,
                                                           data_dir, captured):
        """今天真机踩到的就是这个：传了一份比简历还旧的 PDF，全程无提示。"""
        store = ResumeStore(str(data_dir))
        game = store.create("游戏岗版", target="游戏 客户端")
        _export(store, game["slug"], "游戏岗版", offset=-3600)   # PDF 早于简历

        with pytest.raises(ValueError) as exc:
            service._run_multisite_fill({"pending_job_id": _approved_job(tracker, "游戏客户端开发")})

        assert "游戏岗版" in str(exc.value)
        assert captured == []

    def test_does_not_silently_fall_back_to_another_resume(self, service, tracker,
                                                           data_dir, captured):
        """**最关键的一条**：匹配到的那份不可用时，绝不改发另一份可用的。
        悄悄换一份发出去，比不发严重得多——它会躺在企业系统的表单里。"""
        store = ResumeStore(str(data_dir))
        store.create("游戏岗版", target="游戏 客户端")            # 匹配岗位，但没 PDF
        agent = store.create("AI Agent 开发版", target="AI Agent")
        _export(store, agent["slug"], "AI_Agent")                  # 可用，但不对口

        with pytest.raises(ValueError):
            service._run_multisite_fill({"pending_job_id": _approved_job(tracker, "游戏客户端开发")})

        assert captured == []


class TestTheSendPathMatchesOnTheJd:
    """m2 挑简历时喂的是岗位 JD，跟 Checkpoint 1 显示用的那次**同一个输入**。

    **只改一处就是分叉**：`server.py` 决定审批页显示"批了会发哪份"，这里决定
    实际发出去的是哪份。两处输入不一样的话，人看到的和实际发生的就不是同一件事
    ——**比不显示还糟**。这条约束此前只写在注释里，没有测试守；变异验证时把
    这一处改回 `job.why`，全量测试一条都不红。

    对着 `server.py` 那边的 `TestCheckpoint1ResumePickUsesTheJd` 读。
    """

    def test_it_feeds_the_job_jd_not_the_one_line_reason(self, service, tracker,
                                                         data_dir, monkeypatch):
        seen = {}

        import services.resume_matcher as rm
        real = rm.pick_for_job

        def spy(store, job_title="", jd_text=""):
            seen["jd_text"] = jd_text
            return real(store, job_title=job_title, jd_text=jd_text)

        monkeypatch.setattr(rm, "pick_for_job", spy)

        job_id = tracker.add_pending_job(
            site_name="s", url="https://x/jd-probe", title="游戏客户端开发",
            why="一句话理由", jd="岗位描述\n负责游戏客户端玩法开发")
        tracker.decide_pending_job(job_id, "approved")
        try:
            service._run_multisite_fill({"pending_job_id": job_id})
        except Exception:
            pass  # 这条测试只看喂进去的是什么，后面的流程失不失败无所谓

        assert "负责游戏客户端玩法开发" in seen.get("jd_text", ""), \
            f"实发路径喂给匹配器的不是 JD：{seen.get('jd_text')!r}"


class TestExplicitOverride:
    def test_an_explicitly_given_path_still_wins(self, service, tracker, data_dir,
                                                 captured, tmp_path):
        """显式指定路径是**调试逃生口**，不是自动回退——它由人给出，不是系统在
        失败时偷偷改道。"""
        pdf = tmp_path / "manual.pdf"
        pdf.write_bytes(b"%PDF-1.4")
        ResumeStore(str(data_dir)).create("游戏岗版", target="游戏")

        service._run_multisite_fill({"pending_job_id": _approved_job(tracker, "游戏客户端开发"),
                                     "resume_pdf_path": str(pdf)})

        assert captured[0]["resume_pdf_path"] == str(pdf)
