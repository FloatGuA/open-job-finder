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
