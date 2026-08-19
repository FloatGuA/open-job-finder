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
from multisite.site_manual import SiteManual

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


class TestContainerPerRowIsNotImplementedYet:
    def test_it_raises_instead_of_silently_returning_nothing(self):
        """还没有哪个真实站点需要它。**抛，不要返回空列表**——返回空等于
        谎报"这一页没有岗位"，是本项目反复吃亏的那类假信号。"""
        import pytest
        with pytest.raises(NotImplementedError, match="container_per_row"):
            split_rows(SNAPSHOT, _manual(row_split="container_per_row", row_anchor=""))
