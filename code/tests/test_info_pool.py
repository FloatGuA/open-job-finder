"""信息池（v2.16）：迁移初始化 / 解析合并语义 / 自述融入。"""
from unittest.mock import MagicMock

from services import info_pool
from services import resume_blocks as rb


def _doc(name="张三", sections=None):
    d = rb.empty_blocks()
    d["basic_info"]["name"] = name
    d["sections"] = sections or []
    return d


def test_load_pool_migrates_from_active_resume(tmp_path):
    active = str(tmp_path / "resume_blocks.yaml")
    pool_p = str(tmp_path / "info_pool.yaml")
    rb.save_blocks(_doc(sections=[{"name": "教育经历", "blocks": [
        {"title": "甲大学", "time": "", "bullets": [], "summary": ""}]}]), active)
    pool = info_pool.load_pool(pool_p, active)
    assert pool["sections"][0]["name"] == "教育经历"
    import os
    assert os.path.exists(pool_p)  # 迁移已落盘


def test_merge_parsed_semantics():
    pool = _doc(sections=[
        {"name": "教育经历", "blocks": [
            {"title": "甲大学", "time": "2019", "bullets": ["旧"], "summary": "旧版"},
            {"title": "乙大学", "time": "2025", "bullets": [], "summary": ""},
        ]},
        {"name": "游戏经历", "blocks": [{"title": "手游运营", "time": "", "bullets": [], "summary": ""}]},
    ])
    parsed = _doc(name="", sections=[
        {"name": "教育经历", "blocks": [
            {"title": "甲大学", "time": "2019-2023", "bullets": ["新"], "summary": "新版"},   # 同名分区同标题 → 替换
            {"title": "丙学院", "time": "", "bullets": [], "summary": ""},                  # 新标题 → 追加
        ]},
        {"name": "Agent 经历", "blocks": [{"title": "求职Agent", "time": "", "bullets": [], "summary": ""}]},  # 新分区 → 追加
    ])
    parsed["basic_info"]["phone"] = "138"
    out = info_pool.merge_parsed(pool, parsed)
    edu = out["sections"][0]
    assert [b["title"] for b in edu["blocks"]] == ["甲大学", "乙大学", "丙学院"]
    assert edu["blocks"][0]["bullets"] == ["新"]                       # 同标题被替换为新版
    assert out["sections"][1]["name"] == "游戏经历"                    # 池独有分区保留
    assert out["sections"][2]["name"] == "Agent 经历"                  # 新分区追加尾部
    assert out["basic_info"]["name"] == "张三"                         # 解析空字段不覆盖
    assert out["basic_info"]["phone"] == "138"                         # 解析非空字段覆盖


def test_build_pool_keeps_basic_info_fallback(tmp_path):
    pool = _doc(name="张三")
    pool["basic_info"]["email"] = "a@b.c"
    mr = MagicMock()
    mr.complete.return_value = (
        '{"basic_info": {"name": "张三"}, "sections": [{"name": "技能", "blocks": [{"title": "Python", "time": "", "bullets": [], "summary": "s"}]}]}',
        "mock",
    )
    from services.prompt_manager import PromptManager
    out = info_pool.build_pool(pool, "会 Python", mr, PromptManager(override_dir=tmp_path))
    assert out["sections"][0]["blocks"][0]["title"] == "Python"
    assert out["basic_info"]["email"] == "a@b.c"    # LLM 没回的字段用池原值兜底
    assert out["self_description"] == "会 Python"


# ── 快照（每次 save_pool 前留档，防 LLM 整理丢内容不可逆）────────────────────
def test_save_pool_snapshots_previous_content(tmp_path):
    p = str(tmp_path / "info_pool.yaml")
    info_pool.save_pool(_doc(sections=[{"name": "教育经历", "blocks": [
        {"title": "原始", "time": "", "bullets": [], "summary": ""}]}]), p)
    assert info_pool.list_snapshots(p) == []          # 首次写盘时无旧内容可留档

    info_pool.save_pool(_doc(sections=[]), p)          # 第二次写盘 → 旧内容进快照
    snaps = info_pool.list_snapshots(p)
    assert len(snaps) == 1 and snaps[0]["blocks"] == 1


def test_restore_snapshot_recovers_and_protects_current(tmp_path):
    p = str(tmp_path / "info_pool.yaml")
    good = _doc(sections=[{"name": "教育经历", "blocks": [
        {"title": "重要经历", "time": "", "bullets": ["别丢"], "summary": ""}]}])
    info_pool.save_pool(good, p)
    info_pool.save_pool(_doc(sections=[]), p)          # 模拟"被 LLM 清空"
    assert sum(len(s["blocks"]) for s in info_pool.load_pool(p)["sections"]) == 0

    snap = info_pool.list_snapshots(p)[0]["file"]
    restored = info_pool.restore_snapshot(snap, p)
    assert restored["sections"][0]["blocks"][0]["title"] == "重要经历"
    assert info_pool.load_pool(p)["sections"][0]["blocks"][0]["bullets"] == ["别丢"]
    # 回滚本身也留了档（可以再回滚回去）
    assert len(info_pool.list_snapshots(p)) >= 2


def test_snapshot_rejects_path_traversal(tmp_path):
    import pytest
    p = str(tmp_path / "info_pool.yaml")
    info_pool.save_pool(_doc(), p)
    with pytest.raises(ValueError):
        info_pool.restore_snapshot("../../secret.yaml", p)


def test_snapshots_keep_recent_n(tmp_path, monkeypatch):
    """同一天里连续保存：只保留最近 N 个 + 当天最早那个。"""
    monkeypatch.setattr(info_pool, "SNAPSHOT_KEEP_RECENT", 3)
    p = str(tmp_path / "info_pool.yaml")
    for i in range(8):
        info_pool.save_pool(_doc(name=f"v{i}"), p)      # 同秒也各留一档（加序号）
    snaps = info_pool.list_snapshots(p)
    assert len(snaps) == 4                              # 最近 3 个 + 当天最早 1 个
    assert sum(1 for s in snaps if s["daily"]) == 1
    assert snaps[-1]["daily"] is True                   # 最早那个被标为每日存档


def test_daily_keeper_survives_flood_of_new_saves(tmp_path, monkeypatch):
    """核心诉求：一天内狂点保存，也不能把前几天那个「内容完好」的版本挤掉。"""
    import os
    monkeypatch.setattr(info_pool, "SNAPSHOT_KEEP_RECENT", 2)
    d = tmp_path / "pool_snapshots"
    d.mkdir()
    p = str(tmp_path / "info_pool.yaml")
    # 伪造三天前的一份存档（内容完好，8 条）
    old_doc = _doc(sections=[{"name": "教育经历", "blocks": [
        {"title": f"经历{i}", "time": "", "bullets": [], "summary": ""} for i in range(8)]}])
    rb.save_blocks(old_doc, str(d / "20260101_090000.yaml"))

    rb.save_blocks(_doc(), p)
    for i in range(6):                                   # 今天狂点 6 次保存
        info_pool.save_pool(_doc(name=f"v{i}"), p)

    files = os.listdir(str(d))
    assert "20260101_090000.yaml" in files, "跨天的每日存档被今天的琐碎保存挤掉了"
    old_snap = next(s for s in info_pool.list_snapshots(p) if s["file"] == "20260101_090000.yaml")
    assert old_snap["blocks"] == 8 and old_snap["daily"] is True
    # 仍可回滚到它
    assert sum(len(x["blocks"]) for x in info_pool.restore_snapshot(old_snap["file"], p)["sections"]) == 8


def test_daily_keepers_limited_to_recent_days(tmp_path, monkeypatch):
    """每日存档也不是无限攒——只留最近 N 天。"""
    import os
    monkeypatch.setattr(info_pool, "SNAPSHOT_KEEP_RECENT", 1)
    monkeypatch.setattr(info_pool, "SNAPSHOT_KEEP_DAYS", 3)
    d = tmp_path / "pool_snapshots"
    d.mkdir()
    p = str(tmp_path / "info_pool.yaml")
    for day in range(1, 7):                              # 6 天各一份
        rb.save_blocks(_doc(), str(d / f"2026010{day}_090000.yaml"))
    rb.save_blocks(_doc(), p)
    info_pool.save_pool(_doc(), p)                       # 触发一次修剪
    days = {f[:8] for f in os.listdir(str(d))}
    assert len(days) <= 4                                # 最近 3 天 + 今天


# ── 「我现在在哪个版本」：当前版本标记，防盲跳回滚 ──────────────────────────
def test_is_current_marks_the_version_in_use(tmp_path):
    p = str(tmp_path / "info_pool.yaml")
    v1 = _doc(sections=[{"name": "教育经历", "blocks": [
        {"title": "A", "time": "", "bullets": [], "summary": ""}]}])
    v2 = _doc(sections=[{"name": "教育经历", "blocks": [
        {"title": "B", "time": "", "bullets": [], "summary": ""}]}])
    info_pool.save_pool(v1, p)
    info_pool.save_pool(v2, p)          # 现在用的是 v2；快照里存着 v1

    snaps = info_pool.list_snapshots(p)
    assert [s["is_current"] for s in snaps] == [False]      # v1 快照 ≠ 当前
    assert info_pool.current_summary(p)["blocks"] == 1

    # 回滚到 v1 后，那个快照应被标为「当前」
    info_pool.restore_snapshot(snaps[0]["file"], p)
    snaps2 = info_pool.list_snapshots(p)
    cur = [s for s in snaps2 if s["is_current"]]
    assert cur, "回滚后应有快照被标记为当前"
    assert all(s["blocks"] == 1 for s in cur)


def test_current_summary_reports_live_pool(tmp_path):
    p = str(tmp_path / "info_pool.yaml")
    info_pool.save_pool(_doc(sections=[
        {"name": "教育经历", "blocks": [{"title": "A", "time": "", "bullets": [], "summary": ""}]},
        {"name": "项目经历", "blocks": [{"title": "P", "time": "", "bullets": [], "summary": ""}]},
    ]), p)
    cur = info_pool.current_summary(p)
    assert cur["sections"] == 2 and cur["blocks"] == 2 and cur["saved_at"]
