"""match_resume 工具：按岗位从**简历库**选一份并落库（W2 只选不写的接线守门）。

库＝`data/resumes/library/`，装所有能往外发的 PDF（系统导出的 + 你自己放进去的）。
只在勾了「允许发送」的里面挑；挑不中就用你指定的兜底那份；都没有就如实报空。
"""
import os

from unittest.mock import MagicMock

import pytest

from tools.db.w2.match_resume import MatchResume


@pytest.fixture()
def lib(tmp_path, monkeypatch):
    """真库，落在 tmp_path——比造替身诚实：`pick` 的授权/兜底/重名逻辑都真的跑一遍。"""
    from services.resume_library import ResumeLibrary
    real = ResumeLibrary(str(tmp_path))
    os.makedirs(real.library_dir, exist_ok=True)

    import services.resume_library as rl
    monkeypatch.setattr(rl, "ResumeLibrary", lambda *a, **k: real)
    return real


def _put(lib, file, target, allow_send=True, name=None):
    with open(os.path.join(lib.library_dir, file), "wb") as f:
        f.write(b"%PDF-1.4")
    lib.update_meta(file, name=name or os.path.splitext(file)[0],
                    target=target, allow_send=allow_send)


def test_matches_by_job_title_and_persists(lib):
    _put(lib, "game.pdf", "游戏策划", name="游戏策划版")
    _put(lib, "dev.pdf", "后端开发", name="开发版")
    db = MagicMock()
    db.get.return_value = MagicMock(title="游戏策划（关卡）")
    db.set_matched_resume.return_value = 1

    res = MatchResume(db=db).execute(conv_id="c1", job_id="j1")

    assert res.ok and res.data["resume"] == "游戏策划版" and res.data["matched"] is True
    db.set_matched_resume.assert_called_once()
    conv_id, name, reason = db.set_matched_resume.call_args[0]
    assert conv_id == "c1" and name == "游戏策划版" and reason


def test_falls_back_to_the_designated_one(lib):
    """兜底那份是**你指定的**，不是系统随手挑的——但它同样要记下来，供追溯。"""
    _put(lib, "game.pdf", "游戏策划", name="游戏策划版")
    _put(lib, "dev.pdf", "后端开发", name="开发版")
    lib.set_fallback("dev.pdf")
    db = MagicMock()
    db.get.return_value = MagicMock(title="财务会计")

    res = MatchResume(db=db).execute(conv_id="c1", job_id="j1")

    assert res.data["resume"] == "开发版" and res.data["matched"] is False
    db.set_matched_resume.assert_called_once()


def test_an_unticked_resume_is_never_suggested(lib):
    """没勾「允许发送」的连"建议"都不该出现——建议会被 W2 直接拿去发。"""
    _put(lib, "game.pdf", "游戏策划", allow_send=False, name="游戏策划版")
    db = MagicMock()
    db.get.return_value = MagicMock(title="游戏策划（关卡）")

    res = MatchResume(db=db).execute(conv_id="c1", job_id="j1")

    assert res.data["resume"] == ""
    db.set_matched_resume.assert_not_called()


def test_no_resumes_records_nothing(lib):
    """库里一份能发的都没有时，别把空建议写成「选过了」。"""
    db = MagicMock()
    db.get.return_value = MagicMock(title="任意岗位")

    res = MatchResume(db=db).execute(conv_id="c1", job_id="j1")

    assert res.ok and res.data["resume"] == ""
    db.set_matched_resume.assert_not_called()
