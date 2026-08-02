"""简历块文档（v2.16 动态分区）：归一化 / LLM 解析 / 旧形状自动迁移。"""
from unittest.mock import MagicMock

from services import resume_blocks as rb
from services.prompt_manager import PromptManager


def test_normalize_parsed_doc_coerces_and_defaults():
    parsed = {
        "basic_info": {"name": "张三", "phone": "138", "extra": "ignored"},
        "sections": [
            {"name": "教育经历", "blocks": [{"title": "复旦", "time": "2018-2022", "bullets": ["计科", ""], "summary": "本科"}]},
            {"name": "", "blocks": [{"title": "P", "bullets": ["a"]}, "junk"]},   # 无名分区给占位名、junk 跳过
            "not-a-dict",                                                          # 非 dict 分区跳过
        ],
    }
    out = rb.normalize_parsed_doc(parsed, self_description="desc")
    assert out["basic_info"]["name"] == "张三"
    assert "extra" not in out["basic_info"]
    assert out["self_description"] == "desc"
    assert len(out["sections"]) == 2
    assert out["sections"][0]["name"] == "教育经历"
    assert out["sections"][0]["blocks"][0]["bullets"] == ["计科"]   # 空串过滤
    assert out["sections"][1]["name"] == "未命名分区"
    assert len(out["sections"][1]["blocks"]) == 1


def test_load_blocks_converts_legacy_shape(tmp_path):
    """≤v2.15 的固定五键 + section_order 旧文件 → 自动转成动态 sections（按旧顺序）。"""
    import yaml
    legacy = {
        "basic_info": {"name": "李四"},
        "self_description": "sd",
        "education": [{"title": "甲大学", "time": "2019", "bullets": ["双学位"], "summary": "本科"}],
        "project": [{"title": "AgentX", "time": "2026", "bullets": ["LLM"], "summary": "项目"}],
        "internship": [], "skills": [], "awards": [],
        "section_order": ["project", "education", "internship", "skills", "awards"],
    }
    p = tmp_path / "legacy.yaml"
    p.write_text(yaml.safe_dump(legacy, allow_unicode=True), encoding="utf-8")
    out = rb.load_blocks(str(p))
    assert [s["name"] for s in out["sections"]][:2] == ["项目经历", "教育经历"]  # 顺序沿用 section_order
    assert out["sections"][0]["blocks"][0]["title"] == "AgentX"
    assert out["basic_info"]["name"] == "李四"
    assert out["self_description"] == "sd"
    # 存盘后固化为新形状
    p2 = tmp_path / "new.yaml"
    rb.save_blocks(out, str(p2))
    again = rb.load_blocks(str(p2))
    assert [s["name"] for s in again["sections"]][:2] == ["项目经历", "教育经历"]


def test_parse_resume_to_blocks_uses_resume_parse_prompt(tmp_path):
    mr = MagicMock()
    mr.complete.return_value = (
        '{"basic_info": {"name": "李四", "city": "北京"}, '
        '"sections": [{"name": "实习经历", "blocks": [{"title": "美团", "time": "2021", "bullets": ["后端"], "summary": "实习"}]}]}',
        "mock-provider",
    )
    pm = PromptManager(override_dir=tmp_path)  # 真实默认模板 + 临时覆盖目录
    out = rb.parse_resume_to_blocks("申小明 上海 复旦 计算机", mr, pm)

    _, kwargs = mr.complete.call_args
    assert kwargs["capability"] == "balanced"
    assert "申小明" in kwargs["prompt"]
    assert "{{raw_text}}" not in kwargs["prompt"]

    assert out["basic_info"]["name"] == "李四"
    assert out["sections"][0]["name"] == "实习经历"
    assert out["sections"][0]["blocks"][0]["title"] == "美团"


def test_parse_resume_vision_uses_vision_chain(tmp_path, monkeypatch):
    from services import resume_parser
    monkeypatch.setattr(resume_parser, "render_pdf_to_images", lambda p, **k: ["B64IMG"])
    mr = MagicMock()
    mr.complete.return_value = (
        '{"basic_info": {"name": "王五"}, '
        '"sections": [{"name": "游戏经历", "blocks": [{"title": "X", "time": "2022", "bullets": ["a"], "summary": "s"}]}]}',
        "codex_cli",
    )
    pm = PromptManager(override_dir=tmp_path)
    out = rb.parse_resume_vision("fake.pdf", mr, pm)

    _, kwargs = mr.complete.call_args
    assert kwargs["capability"] == "vision"
    assert kwargs["images"] == ["B64IMG"]
    assert out["basic_info"]["name"] == "王五"
    assert out["sections"][0]["name"] == "游戏经历"    # 自定义分区名原样保留
