"""把平铺的快照切成一行一个岗位。

**为什么按锚点切而不是找标题**：join.qq.com 的岗位卡片在 a11y 快照里没有容器节点，
整页是一串平铺的 StaticText。而列表区开头还夹着推广文案（「不确定适合哪个岗位？…」
三条），按"第一个文本节点即标题"会直接抓错。

锚点＝每个岗位行里必现且仅现一次的文本（本站是「工作地点：」）。真机验证过：
**click 锚点节点会打开它所在那一行的岗位**（事件冒泡到卡片 onClick），
所以切行不需要精确定位标题——标题交给本来就要读这一段的分类 LLM。
"""
from pathlib import Path

from multisite.executors import split_rows
from multisite.site_manual import SiteManual, IMPLEMENTED_ROW_SPLITS

SNAPSHOT = (Path(__file__).parent / "fixtures" / "joinqq_post_list.txt").read_text(encoding="utf-8")


def _manual(**over) -> SiteManual:
    d = {"job_url_source": "new_tab_on_click", "pagination": "next_button",
         "filter_interaction": "expand_group_then_click", "row_split": "anchor_text",
         "row_anchor": "工作地点：", "total_count_locator": r"共(\d+)个岗位"}
    d.update(over)
    return SiteManual.from_dict({**d, "url_template": "", "filters_survive_reload": False,
                                 "dimensions": [], "important_notes": ""})


class TestSplitRowsByAnchor:
    def test_finds_every_job_row(self):
        # 真机这一页恰好 10 个岗位，锚点也恰好 10 个。
        assert len(split_rows(SNAPSHOT, _manual())) == 10

    def test_each_row_carries_the_anchor_uid_to_click(self):
        rows = split_rows(SNAPSHOT, _manual())
        # 真机实测：锚点等距分布，周期 9。
        assert [r.anchor_uid for r in rows][:4] == ["1_78", "1_87", "1_96", "1_105"]

    def test_row_text_contains_the_job_title(self):
        """行文本要覆盖到标题——分类 LLM 要从这段里读出岗位叫什么。"""
        rows = split_rows(SNAPSHOT, _manual())
        assert "Agent开发工程师" in rows[1].text

    def test_promo_text_is_not_a_row(self):
        """列表区开头的推广文案不是岗位。按锚点切天然排除它——但要断言，
        因为"多切出一行垃圾"会一路流到分类和落库。"""
        rows = split_rows(SNAPSHOT, _manual())
        assert not any("知识库" in r.text for r in rows)

    def test_an_anchor_that_matches_nothing_yields_no_rows(self):
        """锚点选错了要表现为"切出 0 行"，而不是切出一堆错的。
        0 行会被上层当成"这一页没岗位"——所以调用方必须自己区分，见 Task 8 的轻校验。"""
        assert split_rows(SNAPSHOT, _manual(row_anchor="这个文本不存在")) == []


class TestExactlyOneAnchor:
    """`span`（相邻锚点间距）需要至少 2 个锚点才能求出来；0 个锚点在
    `_anchor_row_windows` 里提前 return 掉了，所以"恰好 1 个"是唯一会触发
    `_SINGLE_ANCHOR_SPAN_FALLBACK` 回退值的情况——之前只覆盖了 0 个和 10 个
    两端，这里补上中间这一档。"""

    SINGLE_ANCHOR_SNAPSHOT = (
        '## Latest page snapshot\n'
        'uid=1_0 RootWebArea "岗位列表"\n'
        'uid=1_1 StaticText "推广文案A"\n'
        'uid=1_2 StaticText "推广文案B"\n'
        'uid=1_3 StaticText "唯一岗位标题"\n'
        'uid=1_4 StaticText "工作地点："\n'
        'uid=1_5 StaticText "深圳"\n'
        'uid=1_6 StaticText "全职"\n'
    )

    def test_yields_exactly_one_row(self):
        manual = _manual(row_anchor="工作地点：")
        rows = split_rows(self.SINGLE_ANCHOR_SNAPSHOT, manual)
        assert len(rows) == 1

    def test_the_row_covers_the_title_and_the_node_right_after_the_anchor(self):
        """回退窗口用 `_SINGLE_ANCHOR_SPAN_FALLBACK` 往前回切、`+2` 往后扩——
        标题在锚点前几个节点，`+2` 之后的「深圳」也该在窗口内。"""
        manual = _manual(row_anchor="工作地点：")
        rows = split_rows(self.SINGLE_ANCHOR_SNAPSHOT, manual)
        assert "唯一岗位标题" in rows[0].text
        assert "深圳" in rows[0].text


class TestContainerPerRowIsNotImplementedYet:
    def test_it_raises_instead_of_silently_returning_nothing(self):
        """还没有哪个真实站点需要它。`from_dict` 现在已经把 `container_per_row` 挡在
        构造边界之外（见 test_site_manual.py
        `TestAnchorTextRequiresAnAnchor::test_container_per_row_is_rejected_as_unimplemented`），
        所以这里绕过 `from_dict`、直接用 dataclass 构造函数，只测 `split_rows` 自己那道
        兜底还在——万一将来别的路径绕开 `from_dict` 送进来这个值，也不能悄悄返回空列表。
        **抛，不要返回空列表**——返回空等于谎报"这一页没有岗位"，是本项目反复吃亏的
        那类假信号。"""
        import pytest
        assert "container_per_row" not in IMPLEMENTED_ROW_SPLITS, \
            "这条测试的前提是 container_per_row 还没有执行器；一旦实现了，这条测试连同" \
            "本类都该删掉，改为像 anchor_text 一样走 from_dict 的正常路径测试"
        manual = SiteManual(job_url_source="new_tab_on_click", pagination="next_button",
                            filter_interaction="expand_group_then_click",
                            row_split="container_per_row", row_anchor="")
        with pytest.raises(NotImplementedError, match="container_per_row"):
            split_rows(SNAPSHOT, manual)
