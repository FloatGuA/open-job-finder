"""简历库：一个文件夹，装所有能往外发的简历 PDF。

**为什么要有它**（用户 2026-08-16 提、2026-08-21 明确）：
「我可以自己把导出的简历、自己在其他地方做的简历放在系统里同一个文件夹下，
这样方便管理。系统里所有需要用到简历的地方都可以选择用这里的哪些简历。」

旧模型是 **PDF 是某份可编辑简历的派生物**：文件名里带 slug，
`latest_export_for_slug` 靠 `_{slug}_` 找。外来 PDF 没有 slug，**结构上永远选不中**。
新模型是 **PDF 就是简历本身，来源不限**。

**不能复用 `data/resume_pdfs/exports/`**：那里有 `_prune_exports()`，只留最近 20 个，
多的直接 `os.remove`——用户自己放进去的文件会被系统删掉。

三条语义（用户 2026-08-21 定）：
1. 自己放的 PDF **要能参与自动匹配**，靠用户给它填「目标岗位」；不填就只能手动选
2. 「允许自动发送」**默认关**，要手动勾——文件夹能随便扔东西，往外发的必须人确认
3. 老的 exports 路径**直接删掉**，不留兼容层
"""
import os

import pytest

from services.resume_library import ResumeLibrary


def _pdf(lib_dir: str, name: str, content: bytes = b"%PDF-1.4") -> str:
    os.makedirs(lib_dir, exist_ok=True)
    p = os.path.join(lib_dir, name)
    with open(p, "wb") as f:
        f.write(content)
    return p


@pytest.fixture()
def lib(tmp_path):
    return ResumeLibrary(str(tmp_path))


class TestTheFolderIsTheTruth:
    """**文件夹是"这份简历存不存在"的唯一真相**，元数据只是覆盖层。

    今天刚踩过反面教材：`resumes/index.yaml` 里列着两份简历、文件却不在了，
    而列表照样把它们显示出来。存在性和元数据分在两处、以元数据为准，
    就会出现"点开是空的"这种状态。
    """

    def test_a_file_dropped_in_shows_up_without_any_registration(self, lib):
        _pdf(lib.library_dir, "我自己做的简历.pdf")
        items = lib.list()
        assert [i["file"] for i in items] == ["我自己做的简历.pdf"]

    def test_a_dropped_file_starts_unmatched_and_not_sendable(self, lib):
        """没填目标岗位 → 不参与自动匹配；没勾允许 → 不会被自动发出去。"""
        _pdf(lib.library_dir, "我自己做的简历.pdf")
        it = lib.list()[0]
        assert it["target"] == ""
        assert it["allow_send"] is False
        assert it["source"] == "dropped"

    def test_its_name_defaults_to_the_filename(self, lib):
        _pdf(lib.library_dir, "游戏岗_2026.pdf")
        assert lib.list()[0]["name"] == "游戏岗_2026"

    def test_metadata_for_a_file_that_no_longer_exists_is_not_listed(self, lib):
        _pdf(lib.library_dir, "a.pdf")
        lib.update_meta("a.pdf", target="开发", allow_send=True)
        os.remove(os.path.join(lib.library_dir, "a.pdf"))
        assert lib.list() == []

    def test_non_pdf_files_are_ignored(self, lib):
        _pdf(lib.library_dir, "readme.txt")
        _pdf(lib.library_dir, "ok.pdf")
        assert [i["file"] for i in lib.list()] == ["ok.pdf"]


class TestMetadata:
    def test_target_and_allow_send_survive_a_reload(self, lib, tmp_path):
        _pdf(lib.library_dir, "a.pdf")
        lib.update_meta("a.pdf", name="游戏岗版", target="游戏 / 策划", allow_send=True)
        again = ResumeLibrary(str(tmp_path)).list()[0]
        assert again["name"] == "游戏岗版"
        assert again["target"] == "游戏 / 策划"
        assert again["allow_send"] is True

    def test_updating_an_unknown_file_raises(self, lib):
        with pytest.raises(KeyError):
            lib.update_meta("nope.pdf", target="x")

    def test_path_traversal_is_refused(self, lib):
        """文件名来自用户和文件夹，不能拿去拼路径就用。"""
        for bad in ("../secret.pdf", "a/b.pdf", "..\\x.pdf"):
            with pytest.raises(ValueError):
                lib.path_of(bad)


class TestAddingAnExport:
    """编辑器导出＝往库里加一份，**不是**另存到别处。"""

    def test_an_export_lands_in_the_library_with_its_metadata(self, lib):
        p = lib.new_export_path(name="AI Agent 开发版", target="AI Agent / LLM",
                                slug="d5211434")
        with open(p, "wb") as f:
            f.write(b"%PDF-1.4")
        it = lib.list()[0]
        assert it["source"] == "exported"
        assert it["name"] == "AI Agent 开发版"
        assert it["target"] == "AI Agent / LLM"
        assert it["slug"] == "d5211434"

    def test_an_export_is_also_not_sendable_until_ticked(self, lib):
        """用户 2026-08-21 定：**默认关**。导出是你亲手做的，但"往外发"仍要单独点头。"""
        p = lib.new_export_path(name="x", target="", slug="s1")
        with open(p, "wb") as f:
            f.write(b"%PDF-1.4")
        assert lib.list()[0]["allow_send"] is False

    def test_nothing_is_ever_pruned(self, lib):
        """旧 `exports/` 只留最近 20 个、多的直接删——**用户自己放的文件会被系统吃掉**。
        库里不做任何自动删除。"""
        for i in range(25):
            _pdf(lib.library_dir, f"r{i:02d}.pdf")
        assert len(lib.list()) == 25


class TestPickingOneToSend:
    """挑哪一份发出去。**只在勾了「允许发送」的里面挑**。"""

    def _ready(self, lib, file, target, **kw):
        _pdf(lib.library_dir, file)
        lib.update_meta(file, target=target, allow_send=True, **kw)

    def test_it_matches_on_target_keywords(self, lib):
        self._ready(lib, "game.pdf", "游戏 / 策划")
        self._ready(lib, "agent.pdf", "AI Agent / LLM")
        got = lib.pick(job_title="游戏动效设计", jd_text="")
        assert got["file"] == "game.pdf"
        assert got["matched"] is True

    def test_a_dropped_file_with_a_target_competes_normally(self, lib):
        """自己放进来的 PDF 填了目标岗位就跟导出的平起平坐——用户 2026-08-21 定。"""
        self._ready(lib, "外面做的.pdf", "游戏")
        got = lib.pick(job_title="游戏客户端开发", jd_text="")
        assert got["file"] == "外面做的.pdf"

    def test_files_not_ticked_are_invisible_to_the_picker(self, lib):
        """没勾就是没授权——**连"最匹配的那份"都不该是它**，否则等于绕过授权。"""
        _pdf(lib.library_dir, "game.pdf")
        lib.update_meta("game.pdf", target="游戏", allow_send=False)
        got = lib.pick(job_title="游戏动效设计", jd_text="")
        assert got["file"] == "", got

    def test_no_match_falls_back_to_the_designated_one(self, lib):
        self._ready(lib, "agent.pdf", "AI Agent")
        lib.set_fallback("agent.pdf")
        got = lib.pick(job_title="秘书", jd_text="")
        assert got["file"] == "agent.pdf"
        assert got["matched"] is False

    def test_no_match_and_no_fallback_refuses(self, lib):
        """**宁可不发也不乱发。** 挑不中又没指定兜底时返回空，让调用方拒发。"""
        self._ready(lib, "agent.pdf", "AI Agent")
        got = lib.pick(job_title="秘书", jd_text="")
        assert got["file"] == ""
        assert "兜底" in got["reason"] or "没有" in got["reason"]

    def test_a_fallback_that_is_not_ticked_is_not_used(self, lib):
        _pdf(lib.library_dir, "agent.pdf")
        lib.update_meta("agent.pdf", target="", allow_send=False)
        lib.set_fallback("agent.pdf")
        assert lib.pick(job_title="秘书", jd_text="")["file"] == ""


class TestStaleDetection:
    """导出的那份，源简历改过之后就是**旧内容**——这条不能因为换了模型就丢。

    2026-08-16 真机连投三个岗位，用的都是比简历最后修改还早 10 分钟的 PDF，
    而界面上没有任何地方显示这件事。自己放进来的文件没有"源简历"，不参与这个判断。
    """

    def test_an_export_older_than_its_source_is_stale(self, lib):
        p = lib.new_export_path(name="x", target="", slug="s1")
        with open(p, "wb") as f:
            f.write(b"%PDF-1.4")
        st = lib.staleness({"s1": "2099-01-01T00:00:00"})
        assert st[os.path.basename(p)] == "stale"

    def test_an_export_newer_than_its_source_is_fine(self, lib):
        p = lib.new_export_path(name="x", target="", slug="s1")
        with open(p, "wb") as f:
            f.write(b"%PDF-1.4")
        st = lib.staleness({"s1": "2000-01-01T00:00:00"})
        assert st[os.path.basename(p)] == "ready"

    def test_a_dropped_file_has_no_staleness(self, lib):
        _pdf(lib.library_dir, "外面做的.pdf")
        assert lib.staleness({})["外面做的.pdf"] == "ready"


class TestLookupByName:
    """W2 那条链存的是简历**名字**（`hr_conversations.matched_resume`，聊天页显示
    「建议发 X 版」），发送时按名字回查 PDF。

    **重名时拒绝，不猜。** 真实数据里出现过两份都叫「游戏岗版」的简历——猜错的
    后果是给这个 HR 发了另一份简历。沿用旧 `latest_export_for_slug` 的立场：
    宁可报"没有"让人去确认，也不要赌一把。
    """

    def test_it_finds_the_file_by_display_name(self, lib, tmp_path):
        import os
        p = os.path.join(lib.library_dir, "a.pdf")
        os.makedirs(lib.library_dir, exist_ok=True)
        open(p, "wb").write(b"%PDF-1.4")
        lib.update_meta("a.pdf", name="游戏岗版", allow_send=True)
        assert lib.path_for_name("游戏岗版") == p

    def test_a_name_that_is_not_ticked_is_refused(self, lib):
        import os
        os.makedirs(lib.library_dir, exist_ok=True)
        open(os.path.join(lib.library_dir, "a.pdf"), "wb").write(b"%PDF-1.4")
        lib.update_meta("a.pdf", name="游戏岗版", allow_send=False)
        assert lib.path_for_name("游戏岗版") == ""

    def test_a_duplicated_name_is_refused_rather_than_guessed(self, lib):
        import os
        os.makedirs(lib.library_dir, exist_ok=True)
        for f in ("a.pdf", "b.pdf"):
            open(os.path.join(lib.library_dir, f), "wb").write(b"%PDF-1.4")
            lib.update_meta(f, name="游戏岗版", allow_send=True)
        assert lib.path_for_name("游戏岗版") == ""

    def test_an_unknown_name_is_empty(self, lib):
        assert lib.path_for_name("没这份") == ""
