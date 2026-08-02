"""AI 组合（v2.16）：LLM 只挑 id，内容由 code 从池复制；非法 id 丢弃。"""
from unittest.mock import MagicMock

from services import resume_blocks as rb
from services.prompt_manager import PromptManager
from services.resume_tailor import _blocks_digest, generate_composed_sections


def _pool():
    d = rb.empty_blocks()
    d["sections"] = [
        {"name": "教育经历", "blocks": [{"title": "甲大学", "time": "2019", "bullets": ["双学位"], "summary": "本科"}]},
        {"name": "游戏经历", "blocks": [
            {"title": "手游运营", "time": "2021", "bullets": ["上线"], "summary": "游戏"},
            {"title": "游戏策划", "time": "2022", "bullets": ["关卡"], "summary": "策划"},
        ]},
    ]
    return d


def test_digest_uses_section_index_notation():
    text = _blocks_digest(_pool())
    assert "s0#0: [教育经历] 甲大学 | 本科" in text
    assert "s1#1: [游戏经历] 游戏策划 | 策划" in text


def test_compose_copies_picked_blocks_and_drops_invalid(tmp_path):
    mr = MagicMock()
    mr.complete.return_value = (
        '{"sections": ['
        '{"name": "游戏经历", "picks": ["s1#1", "s1#0", "s9#9", "bogus"]},'   # 非法 id 丢弃、顺序按 picks
        '{"name": "教育背景", "picks": ["s0#0"]},'
        '{"name": "空的", "picks": ["s8#8"]}'                                  # 全非法 → 分区丢弃
        ']}',
        "mock",
    )
    out = generate_composed_sections(_pool(), {"title": "游戏策划", "company": "", "jd_text": ""},
                                     mr, PromptManager(override_dir=tmp_path))
    assert [s["name"] for s in out] == ["游戏经历", "教育背景"]
    assert [b["title"] for b in out[0]["blocks"]] == ["游戏策划", "手游运营"]   # 按 picks 顺序复制
    assert out[1]["blocks"][0]["bullets"] == ["双学位"]                        # 内容原样复制不改写
    # prompt 走 resume_compose 模板且带 digest
    _, kwargs = mr.complete.call_args
    assert "s1#0" in kwargs["prompt"]
    assert kwargs["capability"] == "balanced"
