"""哪些简历「真的能发出去」——即有一份不早于简历内容的已导出 PDF。

**为什么需要这个概念**：后端不能自己渲染 PDF（A4 排版的唯一实现在前端
`src/lib/resumeHtml.ts`，后端再写一份就是同一契约两份实现），所以多站点投递只能
用**已导出的存档**。于是「有没有 PDF」「PDF 是不是比简历新」直接决定这份简历能不
能用，而此前界面上没有任何地方显示这件事。

2026-08-16 的真实后果：m2 连投三个岗位，用的都是一份**比简历最后修改还早 10 分钟**
导出的 PDF——传出去的是旧内容，全程没有任何提示。
"""
import os
import time

import pytest

from services.resume_store import ResumeStore


@pytest.fixture()
def store(tmp_path):
    return ResumeStore(str(tmp_path))


def _export(store: ResumeStore, filename: str) -> str:
    os.makedirs(store.exports_dir, exist_ok=True)
    path = os.path.join(store.exports_dir, filename)
    with open(path, "wb") as f:
        f.write(b"%PDF-1.4 fake")
    return path


def _stamp(offset_seconds: int = 0) -> str:
    return time.strftime("%Y%m%d_%H%M%S", time.localtime(time.time() + offset_seconds))


class TestPdfStatus:
    def test_missing_when_never_exported(self, store):
        item = store.create("游戏岗版", target="游戏")
        assert store.pdf_status()[item["slug"]]["state"] == "missing"

    def test_ready_when_pdf_is_newer_than_the_resume(self, store):
        item = store.create("AI Agent 开发版", target="AI")
        _export(store, f"{_stamp(+60)}_{item['slug']}_AI_Agent_开发版.pdf")
        st = store.pdf_status()[item["slug"]]
        assert st["state"] == "ready"
        assert st["pdf"].endswith(".pdf")

    def test_stale_when_the_resume_changed_after_the_export(self, store):
        """今天踩到的就是这个：PDF 比简历还早，传出去的是旧内容。"""
        item = store.create("AI Agent 开发版", target="AI")
        _export(store, f"{_stamp(-3600)}_{item['slug']}_AI_Agent_开发版.pdf")
        assert store.pdf_status()[item["slug"]]["state"] == "stale"

    def test_stale_is_not_reported_as_ready_just_because_a_file_exists(self, store):
        # 「有文件」和「能用」是两件事——这条守的就是别把它们混成一件。
        item = store.create("X", target="x")
        _export(store, f"{_stamp(-3600)}_{item['slug']}_X.pdf")
        assert store.pdf_status()[item["slug"]]["state"] != "ready"


class TestSameNameResumes:
    """真实数据里有两份都叫「游戏岗版」的简历。导出文件名里原本只有名字，
    所以一旦两份都导出就分不清谁是谁——按 slug 存才是精确的。"""

    def test_two_resumes_with_the_same_name_do_not_share_a_pdf(self, store):
        a = store.create("游戏岗版", target="游戏")
        b = store.create("游戏岗版", target="游戏")
        _export(store, f"{_stamp(+60)}_{a['slug']}_游戏岗版.pdf")

        status = store.pdf_status()
        assert status[a["slug"]]["state"] == "ready"
        assert status[b["slug"]]["state"] == "missing"   # 不能因为重名就跟着变可用

    def test_export_filename_carries_the_slug(self, store):
        item = store.create("游戏岗版", target="游戏")
        path = store.export_path_for(item["slug"])
        assert item["slug"] in os.path.basename(path)


class TestLegacyExports:
    """已有的存档是老格式（文件名里没有 slug）。不能因为换了格式就把它们当不存在。"""

    def test_legacy_filename_still_matches_by_name(self, store):
        item = store.create("AI Agent 开发版", target="AI")
        _export(store, f"{_stamp(+60)}_余佩其_AI_Agent_开发版.pdf")
        assert store.pdf_status()[item["slug"]]["state"] == "ready"

    def test_legacy_filename_is_not_guessed_when_names_collide(self, store):
        """老格式 + 重名 = 真的分不清。**宁可报没有，也不要猜错一份发出去。**"""
        store.create("游戏岗版", target="游戏")
        store.create("游戏岗版", target="游戏")
        _export(store, f"{_stamp(+60)}_余佩其_游戏岗版.pdf")

        states = {v["state"] for v in store.pdf_status().values()}
        assert "ready" not in states
