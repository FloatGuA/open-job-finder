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


def _lib(data_dir):
    from services.resume_library import ResumeLibrary
    return ResumeLibrary(str(data_dir))


def _put(data_dir, file: str, target: str = "", allow_send: bool = True,
         name: str = None, slug: str = "", source: str = "dropped") -> None:
    """往简历库里放一份 PDF 并登记元数据。

    默认 `allow_send=True` 只是为了让测试短——**生产的默认是关**
    （用户 2026-08-21 定：往外发的东西要人确认），那条由
    `tests/test_resume_library.py` 单独守着。
    """
    import os
    lib = _lib(data_dir)
    os.makedirs(lib.library_dir, exist_ok=True)
    with open(os.path.join(lib.library_dir, file), "wb") as f:
        f.write(b"%PDF-1.4")
    lib.update_meta(file, name=name or os.path.splitext(file)[0], target=target,
                    allow_send=allow_send, source=source, slug=slug)


class TestPicksByJob:
    def test_uses_the_resume_matching_the_job_not_the_newest_one(self, service, tracker,
                                                                 data_dir, captured):
        """此前用的是「最近导出的那份」——一个跟岗位毫无关系的时间属性。"""
        _put(data_dir, "game.pdf", target="游戏 客户端")
        _put(data_dir, "agent.pdf", target="AI Agent LLM")

        service._run_multisite_fill({"pending_job_id": _approved_job(tracker, "游戏客户端开发")})

        assert "game.pdf" in captured[0]["resume_pdf_path"]

    def test_a_file_you_dropped_in_yourself_competes_normally(self, service, tracker,
                                                              data_dir, captured):
        """自己在别处做的简历，填了目标岗位就跟系统导出的一样参与匹配
        （用户 2026-08-21 定）。旧模型里它结构上永远选不中——文件名里没有 slug。"""
        _put(data_dir, "我自己做的游戏简历.pdf", target="游戏", source="dropped")
        _put(data_dir, "agent.pdf", target="AI Agent", source="exported", slug="s1")

        service._run_multisite_fill({"pending_job_id": _approved_job(tracker, "游戏客户端开发")})

        assert "我自己做的游戏简历.pdf" in captured[0]["resume_pdf_path"]


class TestAuthorisation:
    """**没勾「允许发送」的，连"最匹配的那份"都不该是它。**

    用户 2026-08-16 提、2026-08-21 定：文件夹能随便扔东西，所以往外发必须有一层
    人工授权。没有这层的话，随手放进去的草稿会被自动发到企业系统里。
    """

    def test_an_unticked_resume_is_never_sent(self, service, tracker, data_dir, captured):
        _put(data_dir, "game.pdf", target="游戏 客户端", allow_send=False)

        with pytest.raises(ValueError):
            service._run_multisite_fill({"pending_job_id": _approved_job(tracker, "游戏客户端开发")})
        assert captured == []

    def test_an_empty_library_refuses(self, service, tracker, data_dir, captured):
        with pytest.raises(ValueError) as exc:
            service._run_multisite_fill({"pending_job_id": _approved_job(tracker, "游戏客户端开发")})
        assert "库" in str(exc.value)
        assert captured == []


class TestRefusesWhenTheMatchIsNotUsable:
    def test_no_match_and_no_fallback_refuses(self, service, tracker, data_dir, captured):
        """挑不中又没指定兜底 → 拒发。**宁可不发也不乱发。**"""
        _put(data_dir, "agent.pdf", target="AI Agent")

        with pytest.raises(ValueError) as exc:
            service._run_multisite_fill({"pending_job_id": _approved_job(tracker, "秘书")})
        assert "兜底" in str(exc.value) or "没挑到" in str(exc.value)
        assert captured == []

    def test_a_designated_fallback_is_used(self, service, tracker, data_dir, captured):
        """兜底是**你指定的**，不是系统失败时偷偷改道——这是两件事。"""
        _put(data_dir, "agent.pdf", target="AI Agent")
        _lib(data_dir).set_fallback("agent.pdf")

        service._run_multisite_fill({"pending_job_id": _approved_job(tracker, "秘书")})

        assert "agent.pdf" in captured[0]["resume_pdf_path"]

    def test_refuses_when_the_pdf_is_older_than_its_source_resume(self, service, tracker,
                                                                  data_dir, captured,
                                                                  monkeypatch):
        """2026-08-16 真机踩到的：传了一份比简历还旧的 PDF，全程无提示。
        换了模型这条判断不能丢——**但只对系统导出的那些成立**，自己放的文件
        没有源简历可比。"""
        _put(data_dir, "20200101_000000_s1_game.pdf", target="游戏 客户端",
             source="exported", slug="s1")

        import services.resume_store as rs

        class _Idx:
            def list(self):
                return {"active": "s1",
                        "items": [{"slug": "s1", "name": "game",
                                   "updated_at": "2099-01-01T00:00:00"}]}

        monkeypatch.setattr(rs, "ResumeStore", lambda *a, **kw: _Idx())

        with pytest.raises(ValueError) as exc:
            service._run_multisite_fill({"pending_job_id": _approved_job(tracker, "游戏客户端开发")})
        assert "旧" in str(exc.value)
        assert captured == []

    def test_does_not_silently_fall_back_to_another_resume(self, service, tracker,
                                                           data_dir, captured, monkeypatch):
        """**最关键的一条**：匹配到的那份不可用时，绝不改发另一份可用的。
        悄悄换一份发出去，比不发严重得多——它会躺在企业系统的表单里。"""
        _put(data_dir, "20200101_000000_s1_game.pdf", target="游戏 客户端",
             source="exported", slug="s1")                      # 匹配岗位，但是旧的
        _put(data_dir, "agent.pdf", target="AI Agent")           # 可用，但不对口

        import services.resume_store as rs

        class _Idx:
            def list(self):
                return {"active": "s1",
                        "items": [{"slug": "s1", "name": "game",
                                   "updated_at": "2099-01-01T00:00:00"}]}

        monkeypatch.setattr(rs, "ResumeStore", lambda *a, **kw: _Idx())

        with pytest.raises(ValueError):
            service._run_multisite_fill({"pending_job_id": _approved_job(tracker, "游戏客户端开发")})
        assert captured == []


class TestTheSendPathMatchesOnTheJd:
    """m2 挑简历时喂的是岗位 JD，跟 Checkpoint 1 显示用的那次**同一个输入**。

    **只改一处就是分叉**：`server.py` 决定审批页显示"批了会发哪份"，这里决定
    实际发出去的是哪份。两处输入不一样的话，人看到的和实际发生的就不是同一件事
    ——**比不显示还糟**。这条约束此前只写在注释里，没有测试守；变异验证时把
    这一处改回 `job.why`，全量测试一条都不红。
    """

    def test_it_feeds_the_job_jd_not_the_one_line_reason(self, service, tracker,
                                                         data_dir, monkeypatch):
        seen = {}
        _put(data_dir, "agent.pdf", target="AI Agent")

        from services.resume_library import ResumeLibrary
        real = ResumeLibrary.pick

        def spy(self, job_title="", jd_text=""):
            seen["jd_text"] = jd_text
            return real(self, job_title=job_title, jd_text=jd_text)

        monkeypatch.setattr(ResumeLibrary, "pick", spy)

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


class TestExplicitOverrideStaysInsideTheLibrary:
    """显式指定发哪一份，**也必须是库里的一份**（用户 2026-08-21 定：
    「每个发简历的地方都要收紧成同样的链路」）。

    原来它收的是**任意文件路径**，于是一条命令就能把库、把「允许发送」那层授权
    整个绕过去——而授权正是用户要的东西。指定哪一份是个合理的逃生口，
    "指定一个库外的文件"不是。

    Boss 直聘的站内简历不在此列：那份文件在 Boss 的存储里，我们根本不提供字节。
    """

    def test_naming_a_library_file_works(self, service, tracker, data_dir, captured):
        _put(data_dir, "game.pdf", target="游戏")
        _put(data_dir, "agent.pdf", target="AI Agent")

        service._run_multisite_fill({"pending_job_id": _approved_job(tracker, "游戏客户端开发"),
                                     "resume_file": "agent.pdf"})

        assert "agent.pdf" in captured[0]["resume_pdf_path"], "没听指定的那一份"

    def test_it_overrides_the_match(self, service, tracker, data_dir, captured):
        """指定了就以指定的为准——它是人给出的，不是系统在失败时偷偷改道。"""
        _put(data_dir, "game.pdf", target="游戏 客户端")
        _put(data_dir, "agent.pdf", target="AI Agent")

        service._run_multisite_fill({"pending_job_id": _approved_job(tracker, "游戏客户端开发"),
                                     "resume_file": "agent.pdf"})

        assert "agent.pdf" in captured[0]["resume_pdf_path"]

    def test_a_file_outside_the_library_is_refused(self, service, tracker, data_dir,
                                                   captured, tmp_path):
        """**这是这一条的重点。** 库外的文件没有经过「允许发送」那层授权。"""
        outside = tmp_path / "manual.pdf"
        outside.write_bytes(b"%PDF-1.4")
        _put(data_dir, "agent.pdf", target="AI Agent")

        with pytest.raises(ValueError) as exc:
            service._run_multisite_fill({"pending_job_id": _approved_job(tracker, "游戏客户端开发"),
                                         "resume_file": str(outside)})
        assert "库" in str(exc.value)
        assert captured == []

    def test_an_unticked_library_file_is_refused(self, service, tracker, data_dir, captured):
        """在库里但没勾「允许发送」，指定它也不行——否则显式指定就成了绕过授权的后门。"""
        _put(data_dir, "game.pdf", target="游戏", allow_send=False)
        _put(data_dir, "agent.pdf", target="AI Agent")

        with pytest.raises(ValueError):
            service._run_multisite_fill({"pending_job_id": _approved_job(tracker, "游戏客户端开发"),
                                         "resume_file": "game.pdf"})
        assert captured == []

    def test_an_unknown_file_is_refused(self, service, tracker, data_dir, captured):
        _put(data_dir, "agent.pdf", target="AI Agent")
        with pytest.raises(ValueError):
            service._run_multisite_fill({"pending_job_id": _approved_job(tracker, "游戏客户端开发"),
                                         "resume_file": "nope.pdf"})
        assert captured == []
