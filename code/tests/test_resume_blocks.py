"""简历块库：LLM 一步解析（parse_resume_to_blocks）+ 归一化兜底（_normalize_parsed_blocks）。"""
from unittest.mock import MagicMock

from services import resume_blocks as rb
from services.prompt_manager import PromptManager


def test_normalize_parsed_blocks_coerces_and_defaults():
    parsed = {
        "basic_info": {"name": "张三", "phone": "138", "extra": "ignored"},
        "education": [{"title": "复旦", "time": "2018-2022", "bullets": ["计科", ""], "summary": "本科"}],
        "skills": "not-a-list",                       # 非 list 被忽略
        "project": [{"title": "P", "bullets": ["a"]}, "junk"],  # 非 dict 元素被跳过
    }
    out = rb._normalize_parsed_blocks(parsed, self_description="desc")
    assert out["basic_info"]["name"] == "张三"
    assert out["basic_info"]["phone"] == "138"
    assert "extra" not in out["basic_info"]           # 只保留白名单字段
    assert out["self_description"] == "desc"
    assert len(out["education"]) == 1
    assert out["education"][0]["bullets"] == ["计科"]  # 空串被过滤
    assert out["skills"] == []                        # 非 list → 空
    assert len(out["project"]) == 1                   # junk 被跳过


def test_parse_resume_to_blocks_uses_resume_parse_prompt(tmp_path):
    mr = MagicMock()
    mr.complete.return_value = (
        '{"basic_info": {"name": "李四", "city": "北京"}, '
        '"internship": [{"title": "美团", "time": "2021", "bullets": ["后端"], "summary": "实习"}]}',
        "mock-provider",
    )
    pm = PromptManager(override_dir=tmp_path)  # 真实默认模板 + 临时覆盖目录
    out = rb.parse_resume_to_blocks("申小明 上海 复旦 计算机", mr, pm)

    # 忠实生产调用：balanced capability + resume_parse 模板（raw_text 已替换）
    _, kwargs = mr.complete.call_args
    assert kwargs["capability"] == "balanced"
    assert "申小明" in kwargs["prompt"]
    assert "{{raw_text}}" not in kwargs["prompt"]

    assert out["basic_info"]["name"] == "李四"
    assert out["basic_info"]["city"] == "北京"
    assert len(out["internship"]) == 1
    assert out["internship"][0]["title"] == "美团"


def test_parse_resume_vision_uses_vision_chain(tmp_path, monkeypatch):
    from services import resume_parser
    # 不碰真实 PDF：假 render_pdf_to_images 返回一张图
    monkeypatch.setattr(resume_parser, "render_pdf_to_images", lambda p, **k: ["B64IMG"])
    mr = MagicMock()
    mr.complete.return_value = (
        '{"basic_info": {"name": "王五"}, '
        '"project": [{"title": "X", "time": "2022", "bullets": ["a"], "summary": "s"}]}',
        "ollama_qwen2.5vl:7b",
    )
    pm = PromptManager(override_dir=tmp_path)
    out = rb.parse_resume_vision("fake.pdf", mr, pm)

    # 忠实生产调用：vision capability + 图片透传 + resume_parse_vision 模板
    _, kwargs = mr.complete.call_args
    assert kwargs["capability"] == "vision"
    assert kwargs["images"] == ["B64IMG"]
    assert out["basic_info"]["name"] == "王五"
    assert len(out["project"]) == 1
