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

    def test_container_per_row_is_rejected_as_unimplemented(self):
        """`container_per_row` 在闭集里（ROW_SPLITS），但没有对应的执行器
        （`executors.split_rows` 一碰它就 `NotImplementedError`）。闭集的全部意义是
        "过了 from_dict 就代表代码能执行它"——所以 from_dict 必须挡在这里，而不是让
        计划 B 的 LLM 选中它之后运行中途才崩溃。这是设计变更：`container_per_row` 从
        "接受"改成"拒绝并说明原因"。"""
        d = _valid()
        d["row_split"] = "container_per_row"
        d["row_anchor"] = ""
        with pytest.raises(ManualError, match="执行器"):
            SiteManual.from_dict(d)


class TestIdTemplateRequiresATemplate:
    def test_id_template_without_url_template_raises(self):
        d = _valid()
        d["job_url_source"] = "id_template"
        with pytest.raises(ManualError, match="url_template"):
            SiteManual.from_dict(d)

    def test_id_template_without_placeholder_raises(self):
        """`url_template` 非空但没有 `{id}` 占位符——`job_url_offline` 是
        `url_template.replace("{id}", ...)`，没有占位符时 `.replace` 静默无操作，
        所有岗位会拿到完全相同的 URL。这一格必须在 from_dict 就拦住。"""
        d = _valid()
        d["job_url_source"] = "id_template"
        d["url_template"] = "https://example.com/detail?id=fixed"
        with pytest.raises(ManualError, match=r"\{id\}"):
            SiteManual.from_dict(d)


class TestTotalCountLocatorMustBeValidRegex:
    """`total_count_locator` 是可选字段（空＝这个站没有计数），但**非空时**必须能
    `re.compile` 且带捕获组——否则 `read_total_count` 永远返回 None，而 `validate_manual`
    的判据①会把这个原因误诊成"站点可能已改版"，每轮白付一次全量重探。"""

    def test_empty_locator_is_allowed(self):
        d = _valid()
        d["total_count_locator"] = ""
        assert SiteManual.from_dict(d).total_count_locator == ""

    def test_invalid_regex_raises(self):
        d = _valid()
        d["total_count_locator"] = r"共(\d+个岗位"  # 少了右括号
        with pytest.raises(ManualError, match="正则"):
            SiteManual.from_dict(d)

    def test_regex_without_capture_group_raises(self):
        d = _valid()
        d["total_count_locator"] = r"共\d+个岗位"
        with pytest.raises(ManualError, match="捕获组"):
            SiteManual.from_dict(d)


class TestDimensionsMustHaveOptions:
    """判据②是 `manual.dimensions[0].get("options") or []`。少写一个 `options` 键，
    判据就静默变成永远通过——`from_dict` 必须在手册进入系统前挡住这种形状。"""

    def test_empty_dimensions_is_allowed(self):
        d = _valid()
        d["dimensions"] = []
        assert SiteManual.from_dict(d).dimensions == []

    def test_dimension_missing_options_key_raises(self):
        d = _valid()
        d["dimensions"] = [{"name": "应聘项目", "multi_select": True}]
        with pytest.raises(ManualError, match="options"):
            SiteManual.from_dict(d)

    def test_dimension_options_not_a_list_raises(self):
        d = _valid()
        d["dimensions"] = [{"name": "应聘项目", "options": "2027校园招聘"}]
        with pytest.raises(ManualError, match="options"):
            SiteManual.from_dict(d)
