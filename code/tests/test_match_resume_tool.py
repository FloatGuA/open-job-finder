"""match_resume 工具：按岗位选简历并落库（W2 只选不写的接线守门）。"""
from unittest.mock import MagicMock

from tools.db.w2.match_resume import MatchResume


class _FakeStore:
    """替身 ResumeStore：只提供 list()。"""
    def __init__(self, items, active):
        self._d = {"items": items, "active": active}

    def list(self):
        return self._d


def _patch_store(monkeypatch, items, active):
    import services.resume_store as rs
    monkeypatch.setattr(rs, "ResumeStore", lambda *a, **k: _FakeStore(items, active))


ITEMS = [
    {"slug": "game0001", "name": "游戏策划版", "target": "游戏策划", "updated_at": "2026-08-02T00:00:00"},
    {"slug": "dev00001", "name": "开发版", "target": "后端开发", "updated_at": "2026-08-01T00:00:00"},
]


def test_matches_by_job_title_and_persists(monkeypatch):
    _patch_store(monkeypatch, ITEMS, "dev00001")
    db = MagicMock()
    db.get.return_value = MagicMock(title="游戏策划（关卡）")
    db.set_matched_resume.return_value = 1

    res = MatchResume(db=db).execute(conv_id="c1", job_id="j1")

    assert res.ok and res.data["resume"] == "游戏策划版" and res.data["matched"] is True
    db.set_matched_resume.assert_called_once()
    conv_id, name, reason = db.set_matched_resume.call_args[0]
    assert conv_id == "c1" and name == "游戏策划版" and reason


def test_falls_back_to_active_when_no_match(monkeypatch):
    _patch_store(monkeypatch, ITEMS, "dev00001")
    db = MagicMock()
    db.get.return_value = MagicMock(title="财务会计")

    res = MatchResume(db=db).execute(conv_id="c1", job_id="j1")

    assert res.data["resume"] == "开发版" and res.data["matched"] is False   # 兜底也要记，供追溯
    db.set_matched_resume.assert_called_once()


def test_no_resumes_records_nothing(monkeypatch):
    """一份简历都没有时别把空建议写成「选过了」。"""
    _patch_store(monkeypatch, [], "")
    db = MagicMock()
    db.get.return_value = MagicMock(title="任意岗位")

    res = MatchResume(db=db).execute(conv_id="c1", job_id="j1")

    assert res.ok and res.data["resume"] == ""
    db.set_matched_resume.assert_not_called()


def test_works_without_job_id(monkeypatch):
    """软键会话没有 job_id：拿不到标题也不能崩，走兜底。"""
    _patch_store(monkeypatch, ITEMS, "dev00001")
    db = MagicMock()

    res = MatchResume(db=db).execute(conv_id="c1")

    assert res.ok and res.data["matched"] is False
    db.get.assert_not_called()


def test_registered_in_w2_tools():
    """接线守门：工具必须注册进 W2，否则 pipeline 的 registry.call 静默失效。"""
    from tools.db.w2 import register_w2_tools
    reg = MagicMock()
    registered = []
    reg.register.side_effect = lambda t: registered.append(getattr(t, "name", ""))
    register_w2_tools(reg, db=MagicMock(), model_router=MagicMock(), prompt_manager=MagicMock())
    assert "match_resume" in registered
