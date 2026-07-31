"""多份简历存储（ResumeStore）+ 分区顺序（section_order）。"""
import os

from services import resume_blocks as rb
from services.resume_store import ResumeStore


def _store(tmp_path):
    return ResumeStore(str(tmp_path))


def test_migrate_absorbs_existing_blocks_as_first_resume(tmp_path):
    # 已有 resume_blocks.yaml → 首次 list 自动收编为「默认简历」且激活
    blocks = rb.empty_blocks()
    blocks["basic_info"]["name"] = "张三"
    rb.save_blocks(blocks, str(tmp_path / "resume_blocks.yaml"))
    idx = _store(tmp_path).list()
    assert len(idx["items"]) == 1
    assert idx["active"] == idx["items"][0]["slug"]
    slug = idx["active"]
    copied = rb.load_blocks(str(tmp_path / "resumes" / f"{slug}.yaml"))
    assert copied["basic_info"]["name"] == "张三"


def test_create_copy_and_activate_switches_compat_file(tmp_path):
    st = _store(tmp_path)
    blocks = rb.empty_blocks()
    blocks["basic_info"]["name"] = "原始版"
    st.save_active_blocks(blocks)

    item = st.create(name="游戏岗版", target="游戏运营", copy_from_active=True)
    assert item["target"] == "游戏运营"
    # 新份内容 = 复制自激活份
    copied = rb.load_blocks(str(tmp_path / "resumes" / f"{item['slug']}.yaml"))
    assert copied["basic_info"]["name"] == "原始版"

    # 改新份内容后激活 → 兼容位跟着换
    copied["basic_info"]["name"] = "游戏版名字"
    rb.save_blocks(copied, str(tmp_path / "resumes" / f"{item['slug']}.yaml"))
    st.activate(item["slug"])
    active_blocks = rb.load_blocks(str(tmp_path / "resume_blocks.yaml"))
    assert active_blocks["basic_info"]["name"] == "游戏版名字"


def test_save_active_double_writes(tmp_path):
    st = _store(tmp_path)
    st.list()  # 触发迁移建 index
    blocks = rb.empty_blocks()
    blocks["basic_info"]["name"] = "双写"
    st.save_active_blocks(blocks)
    slug = st.list()["active"]
    assert rb.load_blocks(str(tmp_path / "resume_blocks.yaml"))["basic_info"]["name"] == "双写"
    assert rb.load_blocks(str(tmp_path / "resumes" / f"{slug}.yaml"))["basic_info"]["name"] == "双写"


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


def test_section_order_normalize_and_roundtrip(tmp_path):
    assert rb.normalize_section_order(["project", "education", "bogus", "project"]) == [
        "project", "education", "internship", "skills", "awards"]
    blocks = rb.empty_blocks()
    blocks["section_order"] = ["skills", "project", "education", "internship", "awards"]
    p = str(tmp_path / "b.yaml")
    rb.save_blocks(blocks, p)
    assert rb.load_blocks(p)["section_order"][0] == "skills"


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
