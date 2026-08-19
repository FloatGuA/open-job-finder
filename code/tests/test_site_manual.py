"""手册的每个闭集字段拿到未知值必须当场抛。

**为什么必须 fail fast**：这些字段是代码分派的依据（`match manual.job_url_source`）。
一个未知值如果被兜底成默认值，表现是 harvest 按错误方式抓回一堆垃圾——而那看起来
跟"这个站没岗位"一模一样，是本项目反复吃亏的那类假信号。
"""
import pytest

from multisite.site_manual import ManualError, SiteManual


def _valid() -> dict:
    return {
        "job_url_source": "new_tab_on_click",
        "url_template": "",
        "pagination": "next_button",
        "filter_interaction": "expand_group_then_click",
        "filters_survive_reload": False,
        "total_count_locator": r"共(\d+)个岗位",
        "row_split": "anchor_text",
        "row_anchor": "工作地点：",
        "dimensions": [{"name": "应聘项目", "options": ["2027校园招聘"], "multi_select": True}],
        "important_notes": "",
    }


class TestEnumsAreClosed:
    @pytest.mark.parametrize("field,bad", [
        ("job_url_source", "scrape_the_api"),
        ("pagination", "magic"),
        ("filter_interaction", "just_click_harder"),
        ("row_split", "vibes"),
    ])
    def test_unknown_enum_value_raises(self, field, bad):
        d = _valid()
        d[field] = bad
        with pytest.raises(ManualError, match=field):
            SiteManual.from_dict(d)

    def test_a_valid_manual_round_trips(self):
        d = _valid()
        assert SiteManual.from_dict(d).to_dict() == d


class TestAnchorTextRequiresAnAnchor:
    def test_anchor_text_without_row_anchor_raises(self):
        """`row_split=anchor_text` 而 `row_anchor` 为空 = 一份不可执行的手册。
        让它在构造时炸，而不是等 harvest 切出 0 行、报「这一页没有岗位」。"""
        d = _valid()
        d["row_anchor"] = ""
        with pytest.raises(ManualError, match="row_anchor"):
            SiteManual.from_dict(d)

    def test_container_per_row_does_not_need_an_anchor(self):
        d = _valid()
        d["row_split"] = "container_per_row"
        d["row_anchor"] = ""
        assert SiteManual.from_dict(d).row_anchor == ""


class TestIdTemplateRequiresATemplate:
    def test_id_template_without_url_template_raises(self):
        d = _valid()
        d["job_url_source"] = "id_template"
        with pytest.raises(ManualError, match="url_template"):
            SiteManual.from_dict(d)
