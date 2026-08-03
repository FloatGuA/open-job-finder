"""按岗位挑简历：确定性路由规则（Agent 只选不写）。"""
from services.resume_matcher import pick_resume

ITEMS = [
    {"slug": "aaa11111", "name": "AI 开发版", "target": "AI Agent / LLM 应用开发", "updated_at": "2026-08-01T10:00:00"},
    {"slug": "bbb22222", "name": "游戏策划版", "target": "游戏策划 关卡设计", "updated_at": "2026-08-02T10:00:00"},
    {"slug": "ccc33333", "name": "通用版", "target": "", "updated_at": "2026-08-03T10:00:00"},
]


def test_picks_by_job_title_keyword():
    r = pick_resume(ITEMS, active_slug="ccc33333", job_title="游戏策划（关卡方向）")
    assert r["slug"] == "bbb22222" and r["matched"] is True
    assert "游戏策划" in r["hit_keywords"]


def test_title_beats_jd_when_both_match():
    """标题命中权重高于 JD——JD 里什么词都可能顺带出现。"""
    r = pick_resume(
        ITEMS, active_slug="ccc33333",
        job_title="LLM 应用开发",                      # 命中 AI 开发版（标题，权重 3）
        jd_text="团队也做游戏策划相关业务",              # 命中 游戏策划版（JD，权重 1）
    )
    assert r["slug"] == "aaa11111"


def test_falls_back_to_active_when_nothing_matches():
    r = pick_resume(ITEMS, active_slug="ccc33333", job_title="财务会计")
    assert r["slug"] == "ccc33333" and r["matched"] is False
    assert "兜底" in r["reason"]


def test_no_target_resume_never_wins_by_keyword():
    """没填目标岗位的简历不参与关键词竞争，只可能作为兜底。"""
    r = pick_resume(ITEMS, active_slug="aaa11111", job_title="游戏策划")
    assert r["slug"] == "bbb22222"


def test_tie_breaks_to_more_recently_updated():
    items = [
        {"slug": "old00000", "name": "旧", "target": "后端开发", "updated_at": "2026-01-01T00:00:00"},
        {"slug": "new00000", "name": "新", "target": "后端开发", "updated_at": "2026-08-01T00:00:00"},
    ]
    assert pick_resume(items, active_slug="old00000", job_title="后端开发")["slug"] == "new00000"


def test_empty_store_returns_blank_not_crash():
    r = pick_resume([], active_slug="", job_title="任意岗位")
    assert r["slug"] == "" and r["matched"] is False


def test_jd_only_match_still_works():
    r = pick_resume(ITEMS, active_slug="ccc33333", job_title="内容策划",
                    jd_text="负责关卡设计与数值调优")
    assert r["slug"] == "bbb22222" and r["matched"] is True
