"""`filter_interaction` 从手册里删掉了。

**为什么删**：它**没有任何执行器消费方**——唯一的读者是扫桶 prompt 里那句
「按 `filter_interaction` 指定的方式把筛选器切到这个桶」。而 `set_filter_option`
现在会在运行时给出永远正确的指引（"找不到→先展开分组"，真机证明能把 agent
一步步引导到成功）。**同一个决定有两套机制，其中一套还可能是错的。**

而且单值字段**结构上**表达不了真实形态：join.qq.com 的「应聘项目」选项直接可点、
「工作城市」要展开两层。旧 prompt 甚至明写着"没有遇到报错就说明这个站不需要展开"
——agent 测了直接可点的那个维度，就把整站判成 `direct_click`，完全照做。

**老手册里还带着这个 key**，删字段之后必须照样加载得动：库里存着的手册不会因为
一次代码改动就全部失效（那等于强制全站重探）。
"""
import pytest

from multisite.site_manual import SiteManual, ManualError


BASE = {
    "job_url_source": "new_tab_on_click",
    "url_template": "",
    "pagination": "next_button",
    "filters_survive_reload": False,
    "total_count_locator": "",
    "row_split": "anchor_text",
    "row_anchor": "工作地点：",
    "dimensions": [],
    "important_notes": "",
}


class TestFilterInteractionIsGone:
    def test_a_manual_without_it_loads(self):
        m = SiteManual.from_dict(dict(BASE))
        assert not hasattr(m, "filter_interaction")

    def test_an_old_manual_that_still_has_it_loads_too(self):
        """库里存着的手册都带这个 key。删字段不能让它们全部失效——
        那等于强制每个站重探一遍。"""
        old = dict(BASE, filter_interaction="direct_click")
        m = SiteManual.from_dict(old)
        assert m.row_split == "anchor_text"
        assert not hasattr(m, "filter_interaction")

    def test_an_old_manual_with_a_now_meaningless_value_still_loads(self):
        """连取值都不再校验了——这个字段已经没有语义，挡它没有意义。"""
        m = SiteManual.from_dict(dict(BASE, filter_interaction="whatever"))
        assert m.row_split == "anchor_text"

    def test_it_is_not_in_the_serialized_form(self):
        assert "filter_interaction" not in SiteManual.from_dict(dict(BASE)).to_dict()

    def test_the_other_closed_sets_still_bite(self):
        """删一个字段不能顺手把别的校验也弄松了。"""
        with pytest.raises(ManualError, match="row_split"):
            SiteManual.from_dict(dict(BASE, row_split="nonsense"))
