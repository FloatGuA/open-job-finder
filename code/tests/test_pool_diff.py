"""信息池变更提案的 diff 与选择性落盘。

**为什么这套东西存在**：池是求职者全部信息的唯一主库，而 `build_pool` 让 LLM
**整体重写 sections**——一次错误保存就把内容覆盖掉了。原本的防线只有"写前快照 +
事后回滚"，那是发现丢了东西之后的补救。用户 2026-08-15 要求改成事前把关。

这一组守的核心是 `apply_selection` 的一条不变量：**没勾的一律保持现状**，尤其是
"提案里压根没提到的内容不能消失"——那正是 LLM 重写最危险的地方。
"""
import pytest

from services.pool_diff import apply_selection, block_key, diff_pools


def _blk(title, bullets=None, time="", summary=""):
    return {"title": title, "time": time, "bullets": list(bullets or []), "summary": summary}


def _pool(sections=None, **basic):
    return {"basic_info": dict(basic), "self_description": "",
            "sections": list(sections or [])}


def _sec(name, *blocks):
    return {"name": name, "blocks": list(blocks)}


class TestDiff:
    def test_no_changes_reports_nothing(self):
        p = _pool([_sec("教育经历", _blk("甲大学"))], name="张三")
        d = diff_pools(p, p)
        assert d["has_changes"] is False
        assert d["sections"] == [] and d["basic_info"] == []

    def test_unchanged_blocks_are_omitted(self):
        """池里十几个块，全列出来人根本找不到改了哪里。"""
        cur = _pool([_sec("教育经历", _blk("甲大学"), _blk("乙大学"))])
        new = _pool([_sec("教育经历", _blk("甲大学"), _blk("乙大学", ["新要点"]))])
        blocks = diff_pools(cur, new)["sections"][0]["blocks"]
        assert [b["title"] for b in blocks] == ["乙大学"]

    def test_added_block(self):
        cur = _pool([_sec("教育经历", _blk("甲大学"))])
        new = _pool([_sec("教育经历", _blk("甲大学"), _blk("乙大学"))])
        b = diff_pools(cur, new)["sections"][0]["blocks"][0]
        assert b["kind"] == "added" and b["title"] == "乙大学"

    def test_removed_block_is_surfaced(self):
        """LLM 重写把块弄丢了必须看得见——这是做这套确认的起因。"""
        cur = _pool([_sec("项目经历", _blk("甲项目"), _blk("乙项目"))])
        new = _pool([_sec("项目经历", _blk("甲项目"))])
        b = diff_pools(cur, new)["sections"][0]["blocks"][0]
        assert b["kind"] == "removed" and b["title"] == "乙项目"

    def test_bullet_level_diff(self):
        """要点通常只动一两条，整块红绿会让人看不出改了啥。"""
        cur = _pool([_sec("项目经历", _blk("甲项目", ["保留", "旧的"]))])
        new = _pool([_sec("项目经历", _blk("甲项目", ["保留", "新的"]))])
        bullets = diff_pools(cur, new)["sections"][0]["blocks"][0]["bullets"]
        assert {"op": " ", "text": "保留"} in bullets
        assert {"op": "-", "text": "旧的"} in bullets
        assert {"op": "+", "text": "新的"} in bullets

    def test_field_change_is_listed(self):
        cur = _pool([_sec("教育经历", _blk("甲大学", time="2019-2023"))])
        new = _pool([_sec("教育经历", _blk("甲大学", time="2019-2024"))])
        f = diff_pools(cur, new)["sections"][0]["blocks"][0]["fields"]
        assert f == [{"field": "time", "old": "2019-2023", "new": "2019-2024"}]

    def test_style_change_alone_is_not_a_change(self):
        # style 是排版（粗体/斜体），不是信息，改了不值得让人确认。
        cur = _pool([_sec("教育经历", dict(_blk("甲大学"), style={"title": ["bold"]}))])
        new = _pool([_sec("教育经历", dict(_blk("甲大学"), style={}))])
        assert diff_pools(cur, new)["has_changes"] is False

    def test_basic_info_added_vs_changed(self):
        cur = _pool(name="张三")
        new = _pool(name="李四", phone="123")
        got = {b["key"]: b["kind"] for b in diff_pools(cur, new)["basic_info"]}
        assert got == {"basic_info␟name": "changed", "basic_info␟phone": "added"}

    def test_blank_proposed_value_never_wipes_an_existing_one(self):
        """解析没读出电话，不代表电话没了。"""
        cur = _pool(phone="123")
        new = _pool(phone="")
        assert diff_pools(cur, new)["basic_info"] == []

    def test_defaults_added_yes_changed_and_removed_no(self):
        cur = _pool([_sec("项目经历", _blk("旧项目"), _blk("改的", ["a"]))])
        new = _pool([_sec("项目经历", _blk("改的", ["b"]), _blk("新项目"))])
        got = {b["title"]: b["accept_default"] for b in diff_pools(cur, new)["sections"][0]["blocks"]}
        assert got == {"新项目": True, "改的": False, "旧项目": False}, \
            "覆盖和删除必须默认不选——那是最该被看一眼的两种"


class TestApplySelection:
    def test_nothing_selected_changes_nothing(self):
        cur = _pool([_sec("教育经历", _blk("甲大学", ["旧"]))], name="张三")
        new = _pool([_sec("教育经历", _blk("甲大学", ["新"]))], name="李四")
        assert apply_selection(cur, new, []) == {**cur, "self_description": ""}

    def test_selected_addition_lands(self):
        cur = _pool([_sec("教育经历", _blk("甲大学"))])
        new = _pool([_sec("教育经历", _blk("甲大学"), _blk("乙大学"))])
        out = apply_selection(cur, new, [block_key("教育经历", "乙大学")])
        assert [b["title"] for b in out["sections"][0]["blocks"]] == ["甲大学", "乙大学"]

    def test_selected_change_overwrites_in_place(self):
        cur = _pool([_sec("教育经历", _blk("甲大学", ["旧"]), _blk("乙大学"))])
        new = _pool([_sec("教育经历", _blk("甲大学", ["新"]))])
        out = apply_selection(cur, new, [block_key("教育经历", "甲大学")])
        assert out["sections"][0]["blocks"][0]["bullets"] == ["新"]
        assert [b["title"] for b in out["sections"][0]["blocks"]] == ["甲大学", "乙大学"], \
            "顺序要稳，没动的块不该被挪位"

    def test_unmentioned_content_survives_a_rewrite_proposal(self):
        """**整个文件最重要的一条。**

        `build_pool` 让 LLM 整体重写，它可能压根不提某个分区/块。如果落盘时从提案
        出发（删掉没勾的），那些内容会**悄无声息地消失**——而它们从来没被摆到人面前
        确认过。所以实现必须从当前池出发逐项打补丁。
        """
        cur = _pool([_sec("教育经历", _blk("甲大学")),
                     _sec("游戏经历", _blk("某游戏项目"))])
        new = _pool([_sec("教育经历", _blk("甲大学", ["补充"]))])  # 提案完全没提游戏经历
        out = apply_selection(cur, new, [block_key("教育经历", "甲大学")])
        assert [s["name"] for s in out["sections"]] == ["教育经历", "游戏经历"]
        assert out["sections"][1]["blocks"][0]["title"] == "某游戏项目"

    def test_removal_only_happens_when_explicitly_selected(self):
        cur = _pool([_sec("项目经历", _blk("甲项目"), _blk("乙项目"))])
        new = _pool([_sec("项目经历", _blk("甲项目"))])  # 提案主张删掉乙项目

        kept = apply_selection(cur, new, [])
        assert [b["title"] for b in kept["sections"][0]["blocks"]] == ["甲项目", "乙项目"]

        dropped = apply_selection(cur, new, [block_key("项目经历", "乙项目")])
        assert [b["title"] for b in dropped["sections"][0]["blocks"]] == ["甲项目"]

    def test_selected_basic_info_only(self):
        cur = _pool(name="张三", phone="123")
        new = _pool(name="李四", phone="999")
        out = apply_selection(cur, new, ["basic_info␟name"])
        assert out["basic_info"] == {"name": "李四", "phone": "123"}

    def test_new_section_is_appended(self):
        cur = _pool([_sec("教育经历", _blk("甲大学"))])
        new = _pool([_sec("获奖情况", _blk("某奖项"))])
        out = apply_selection(cur, new, [block_key("获奖情况", "某奖项")])
        assert [s["name"] for s in out["sections"]] == ["教育经历", "获奖情况"]

    def test_empty_sections_are_dropped(self):
        cur = _pool([_sec("项目经历", _blk("唯一项目"))])
        new = _pool([_sec("项目经历")])
        out = apply_selection(cur, new, [block_key("项目经历", "唯一项目")])
        assert out["sections"] == []


class TestRoundTrip:
    def test_accepting_everything_reproduces_the_proposal_content(self):
        """全勾之后，提案里的内容应该都在池里（池是超集，可能还多出没被提及的）。"""
        cur = _pool([_sec("教育经历", _blk("甲大学", ["旧"]))], name="张三")
        new = _pool([_sec("教育经历", _blk("甲大学", ["新"]), _blk("乙大学"))], name="李四")
        d = diff_pools(cur, new)
        keys = [b["key"] for b in d["basic_info"]]
        keys += [b["key"] for s in d["sections"] for b in s["blocks"]]
        out = apply_selection(cur, new, keys)

        assert out["basic_info"]["name"] == "李四"
        titles = {b["title"]: b for b in out["sections"][0]["blocks"]}
        assert titles["甲大学"]["bullets"] == ["新"]
        assert "乙大学" in titles


class TestDiffAndApplyAgree:
    """**diff 里能勾的，apply 必须能落。**

    2026-08-15 用真实池数据跑出来的 bug：提案完全没提某个分区时，diff 把它的块显示成
    「删除」并给了勾选框，但 apply 里有一句"这个分区提案没提，整个跳过"，于是勾了没反应。
    UI 摆一个点了没用的框比不摆更糟——人会以为自己已经决定了。
    """

    def _keys(self, d):
        return [b["key"] for b in d["basic_info"]] + \
               [b["key"] for s in d["sections"] for b in s["blocks"]]

    def test_every_key_the_diff_offers_can_actually_be_applied(self):
        cur = _pool([_sec("教育经历", _blk("甲大学", ["旧"])),
                     _sec("游戏经历", _blk("某游戏项目"))],
                    name="张三")
        # 提案：改一块、加一块、整个不提游戏经历（模拟 LLM 重写漏掉）
        new = _pool([_sec("教育经历", _blk("甲大学", ["新"]), _blk("某培训"))], name="李四")

        d = diff_pools(cur, new)
        out = apply_selection(cur, new, self._keys(d))

        titles = {s["name"]: [b["title"] for b in s["blocks"]] for s in out["sections"]}
        assert titles["教育经历"] == ["甲大学", "某培训"]
        assert "游戏经历" not in titles, "diff 说它会被删，全勾之后就该真的被删"
        assert out["sections"][0]["blocks"][0]["bullets"] == ["新"]
        assert out["basic_info"]["name"] == "李四"

    def test_unmentioned_section_still_survives_when_not_ticked(self):
        """默认保留靠"没勾就不删"，不靠跳过某些分区——两条行为要同时成立。"""
        cur = _pool([_sec("教育经历", _blk("甲大学")), _sec("游戏经历", _blk("某游戏项目"))])
        new = _pool([_sec("教育经历", _blk("甲大学", ["补充"]))])
        out = apply_selection(cur, new, [block_key("教育经历", "甲大学")])
        assert [s["name"] for s in out["sections"]] == ["教育经历", "游戏经历"]
