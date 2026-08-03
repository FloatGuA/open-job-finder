"""ResumeStep 适配简历路径：开关行为 + 「绝不因想发适配版而漏发」的回退保证。"""
from unittest.mock import MagicMock

from pipeline.base import StepStatus
from pipeline.w2.steps.resume import ResumeStep


def _reg(**tool_results):
    reg = MagicMock()
    reg.logger = MagicMock()

    def call(name, **kw):
        res = tool_results.get(name)
        if res is None:
            return MagicMock(ok=False, data={}, error="not stubbed")
        return res
    reg.call.side_effect = call
    return reg


def _ok(**data):
    return MagicMock(ok=True, data=data, error=None)


def _fail(err="boom", **data):
    return MagicMock(ok=False, data=data, error=err)


def test_sends_adapted_pdf_when_export_exists(monkeypatch):
    monkeypatch.setattr(ResumeStep, "_adapted_pdf_path", lambda self, n: "C:/tmp/x.pdf")
    reg = _reg(upload_resume_file=_ok(sent=True))
    out = ResumeStep(reg).run(request_type="hr_text", adapted_resume="游戏策划版")

    assert out.sent is True and out.strategy_used == "adapted_pdf"
    assert reg.call.call_args_list[0][0][0] == "upload_resume_file"


def test_falls_back_to_station_resume_when_no_export(monkeypatch):
    """没导出过该简历 → 不能就此不发，必须回退站内简历。"""
    monkeypatch.setattr(ResumeStep, "_adapted_pdf_path", lambda self, n: "")
    reg = _reg(click_toolbar_send_resume=_ok(sent=True))
    out = ResumeStep(reg).run(request_type="hr_text", adapted_resume="游戏策划版")

    assert out.sent is True and out.strategy_used == "toolbar"
    called = [c[0][0] for c in reg.call.call_args_list]
    assert "upload_resume_file" not in called          # 没 PDF 就别去点上传
    assert "click_toolbar_send_resume" in called


def test_falls_back_when_upload_not_confirmed(monkeypatch):
    """上传点了但没出现送达气泡 → 视为没发出去，回退站内简历。"""
    monkeypatch.setattr(ResumeStep, "_adapted_pdf_path", lambda self, n: "C:/tmp/x.pdf")
    reg = _reg(
        upload_resume_file=_ok(sent=False),            # ok 但未确认送达
        click_toolbar_send_resume=_ok(sent=True),
    )
    out = ResumeStep(reg).run(request_type="hr_text", adapted_resume="游戏策划版")

    assert out.sent is True and out.strategy_used == "toolbar"
    reg.logger.log.assert_called()                     # 回退原因要留痕，不做哑谜


def test_upload_error_also_falls_back(monkeypatch):
    monkeypatch.setattr(ResumeStep, "_adapted_pdf_path", lambda self, n: "C:/tmp/x.pdf")
    reg = _reg(upload_resume_file=_fail("file input not found"),
               click_toolbar_send_resume=_ok(sent=True))
    out = ResumeStep(reg).run(request_type="hr_text", adapted_resume="游戏策划版")
    assert out.sent is True and out.strategy_used == "toolbar"


def test_toggle_off_never_touches_upload(monkeypatch):
    """开关关着（adapted_resume 传空）→ 完全走原有路径，一次都不碰上传。"""
    monkeypatch.setattr(ResumeStep, "_adapted_pdf_path",
                        lambda self, n: (_ for _ in ()).throw(AssertionError("不该查 PDF")))
    reg = _reg(click_toolbar_send_resume=_ok(sent=True))
    out = ResumeStep(reg).run(request_type="hr_text", adapted_resume="")

    assert out.sent is True and out.strategy_used == "toolbar"
    assert "upload_resume_file" not in [c[0][0] for c in reg.call.call_args_list]


def test_all_paths_fail_reports_degraded(monkeypatch):
    monkeypatch.setattr(ResumeStep, "_adapted_pdf_path", lambda self, n: "C:/tmp/x.pdf")
    reg = _reg(upload_resume_file=_ok(sent=False), click_toolbar_send_resume=_ok(sent=False))
    out = ResumeStep(reg).run(request_type="hr_text", adapted_resume="游戏策划版")
    assert out.sent is False and out.status == StepStatus.DEGRADED
