"""多份简历存储（ResumeStore）+ 分区顺序（section_order）。"""
import os

from services import resume_blocks as rb
from services.resume_store import ResumeStore


def _store(tmp_path):
    return ResumeStore(str(tmp_path))


def test_first_use_creates_one_empty_resume(tmp_path):
    """没有 index.yaml 时建一份空的「默认简历」。

    原本这里还会去收编 data/resume_blocks.yaml（v2.15 之前那唯一一份简历）。
    那个一次性迁移早跑完了，文件也已删除（2026-08-15）。
    """
    idx = _store(tmp_path).list()
    assert len(idx["items"]) == 1
    assert idx["active"] == idx["items"][0]["slug"]
    assert os.path.exists(str(tmp_path / "resumes" / f"{idx['active']}.yaml"))


def test_create_copies_from_active(tmp_path):
    st = _store(tmp_path)
    blocks = rb.empty_blocks()
    blocks["basic_info"]["name"] = "原始版"
    st.save_active_blocks(blocks)

    item = st.create(name="游戏岗版", target="游戏运营", copy_from_active=True)
    assert item["target"] == "游戏运营"
    copied = rb.load_blocks(str(tmp_path / "resumes" / f"{item['slug']}.yaml"))
    assert copied["basic_info"]["name"] == "原始版"


def test_activate_only_moves_the_pointer(tmp_path):
    """切换激活简历**不该拷贝内容**——内容一直在各自的 {slug}.yaml 里。

    原先 activate() 会把选中份拷进 resume_blocks.yaml 兼容位，于是同一份内容存两处。
    """
    st = _store(tmp_path)
    first = rb.empty_blocks()
    first["basic_info"]["name"] = "原始版"
    st.save_active_blocks(first)
    slug_a = st.list()["active"]

    item = st.create(name="游戏岗版", copy_from_active=False)
    other = rb.empty_blocks()
    other["basic_info"]["name"] = "游戏版名字"
    rb.save_blocks(other, str(tmp_path / "resumes" / f"{item['slug']}.yaml"))

    st.activate(item["slug"])
    assert st.list()["active"] == item["slug"]
    assert st.load_active()["basic_info"]["name"] == "游戏版名字"
    # 切换不改动原来那份
    assert rb.load_blocks(str(tmp_path / "resumes" / f"{slug_a}.yaml"))["basic_info"]["name"] == "原始版"


def test_save_active_writes_exactly_one_file(tmp_path):
    """**这条是删掉兼容位的核心不变量**：一份简历的内容只落一个文件。

    原来 save_active_blocks 双写 {slug}.yaml + resume_blocks.yaml，两个写入口写同一
    份数据——这个项目为此栽过五次。如果有人把兼容位加回来，这条会红。
    """
    st = _store(tmp_path)
    st.list()
    blocks = rb.empty_blocks()
    blocks["basic_info"]["name"] = "只写一处"
    st.save_active_blocks(blocks)

    slug = st.list()["active"]
    assert rb.load_blocks(str(tmp_path / "resumes" / f"{slug}.yaml"))["basic_info"]["name"] == "只写一处"
    assert st.load_active()["basic_info"]["name"] == "只写一处"
    assert not os.path.exists(str(tmp_path / "resume_blocks.yaml")), \
        "兼容位不该再被写出来——它是同一份内容的第二个副本"

    # data_dir 下只应有 resumes/ 这一处放简历内容的地方
    yamls = [f for f in os.listdir(tmp_path) if f.endswith(".yaml")]
    assert yamls == [], f"data 根目录不该出现简历 yaml，实际有 {yamls}"


def test_delete_keeps_at_least_one_and_reactivates(tmp_path):
    st = _store(tmp_path)
    st.list()
    import pytest
    with pytest.raises(ValueError):
        st.delete(st.list()["active"])  # 只剩一份不许删
    second = st.create(name="第二份")
    st.activate(second["slug"])
    st.delete(second["slug"])  # 删激活份 → 自动切回剩下那份
    idx = st.list()
    assert len(idx["items"]) == 1
    assert idx["active"] == idx["items"][0]["slug"]


def test_dynamic_sections_roundtrip(tmp_path):
    """v2.16 动态分区：自定义分区名与顺序原样往返。"""
    blocks = rb.empty_blocks()
    blocks["sections"] = [
        {"name": "游戏经历", "blocks": [{"title": "手游", "time": "", "bullets": ["b"], "summary": ""}]},
        {"name": "教育经历", "blocks": []},
    ]
    p = str(tmp_path / "b.yaml")
    rb.save_blocks(blocks, p)
    out = rb.load_blocks(p)
    assert [s["name"] for s in out["sections"]] == ["游戏经历", "教育经历"]
    assert out["sections"][0]["blocks"][0]["title"] == "手游"


def test_export_archive_list_and_prune(tmp_path):
    st = _store(tmp_path)
    p = st.export_path("张三 简历/v1")  # 非法文件名字符被清洗
    assert p.endswith(".pdf") and "/" not in os.path.basename(p).replace("\\", "")
    open(p, "wb").write(b"%PDF fake")
    lst = st.list_exports()
    assert len(lst) == 1 and lst[0]["file"] == os.path.basename(p)
    # 路径穿越拒绝
    import pytest
    with pytest.raises(ValueError):
        st.export_file("../secret.pdf")
    st.delete_export(lst[0]["file"])
    assert st.list_exports() == []


# ── 按简历名回查已导出 PDF（自动发送用「已导出存档」，不让后端再实现一套排版）──
def test_latest_export_for_finds_newest_matching(tmp_path):
    st = _store(tmp_path)
    st.list()
    blocks = rb.empty_blocks()
    blocks["basic_info"]["name"] = "张三"
    st.save_active_blocks(blocks)
    st.update_meta(st.list()["active"], name="开发版")

    exp = tmp_path / "resume_pdfs" / "exports"
    exp.mkdir(parents=True)
    (exp / "20260101_090000_张三_开发版.pdf").write_bytes(b"%PDF old")
    (exp / "20260808_090000_张三_开发版.pdf").write_bytes(b"%PDF new")
    (exp / "20260909_090000_张三_游戏版.pdf").write_bytes(b"%PDF other")

    got = st.latest_export_for("开发版")
    assert got.endswith("20260808_090000_张三_开发版.pdf")     # 取最新那份


def test_latest_export_for_no_partial_name_collision(tmp_path):
    """「开发版」不得误命中「AI Agent 开发版」的存档（后缀须精确匹配）。"""
    st = _store(tmp_path)
    st.list()
    blocks = rb.empty_blocks()
    blocks["basic_info"]["name"] = "张三"
    st.save_active_blocks(blocks)
    st.update_meta(st.list()["active"], name="开发版")

    exp = tmp_path / "resume_pdfs" / "exports"
    exp.mkdir(parents=True)
    (exp / "20260808_090000_张三_AI_Agent_开发版.pdf").write_bytes(b"%PDF other")

    assert st.latest_export_for("开发版") == ""


def test_latest_export_for_missing_returns_empty(tmp_path):
    st = _store(tmp_path)
    st.list()
    assert st.latest_export_for("不存在的简历") == ""
