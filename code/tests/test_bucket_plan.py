"""桶计划：这一轮该去站点的哪几个桶，每个桶指望捞哪几个目标类别。

**不走 ReAct 循环**是刻意的（spec §2.1 同理）：它不碰浏览器，输入是手册和求职条件，
输出是一份清单，没有"观察→行动"的循环可言。做成普通 LLM 调用换来的是可单测、可 eval。
"""
import asyncio
import json

import pytest

from multisite.bucket_plan import plan_buckets
from multisite.site_manual import SiteManual


def _run(c):
    return asyncio.run(c)


MANUAL = SiteManual.from_dict({
    "job_url_source": "new_tab_on_click", "url_template": "", "pagination": "next_button",
    "filter_interaction": "expand_group_then_click", "filters_survive_reload": False,
    "total_count_locator": r"共(\d+)个岗位", "row_split": "anchor_text",
    "row_anchor": "工作地点：", "important_notes": "",
    "dimensions": [
        {"name": "岗位类别", "options": ["青云课题", "技术", "产品", "设计", "市场", "职能"],
         "multi_select": True},
        {"name": "工作城市", "options": ["深圳", "北京", "上海"], "multi_select": True},
    ],
})
QUOTAS = {"AI NATIVE": 3, "开发": 5, "产品": 3}

MANUAL_WITH_UNNAMED_DIM = SiteManual.from_dict({
    "job_url_source": "new_tab_on_click", "url_template": "", "pagination": "next_button",
    "filter_interaction": "expand_group_then_click", "filters_survive_reload": False,
    "total_count_locator": r"共(\d+)个岗位", "row_split": "anchor_text",
    "row_anchor": "工作地点：", "important_notes": "",
    "dimensions": [
        {"options": ["神秘选项"], "multi_select": True},  # 缺 name（SiteManual 不挡这个）
        {"name": "岗位类别", "options": ["技术", "产品"], "multi_select": True},
    ],
})


class _FakeModel:
    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    async def ainvoke(self, messages):
        self.prompts.append(messages)

        class _R:
            content = self.payload if isinstance(self.payload, str) else json.dumps(
                self.payload, ensure_ascii=False)
        return _R()


class TestPlanBuckets:
    def test_returns_the_planned_buckets(self):
        model = _FakeModel([
            {"dimension": "岗位类别", "option": "青云课题", "why": "AI 方向", "targets": ["AI NATIVE"]},
            {"dimension": "岗位类别", "option": "技术", "why": "开发岗在这里", "targets": ["开发"]},
        ])
        out = _run(plan_buckets(MANUAL, QUOTAS, "只看深圳", model=model))
        assert [b["option"] for b in out] == ["青云课题", "技术"]
        assert out[0]["targets"] == ["AI NATIVE"]

    def test_an_option_not_in_the_manual_is_dropped(self):
        """LLM 编一个手册里没有的选项，代码照着去点必然点空——而"点空"表现为
        "这个桶没有岗位"，跟真的没岗位分不开。在这里就丢掉。"""
        model = _FakeModel([
            {"dimension": "岗位类别", "option": "量子计算", "why": "编的", "targets": ["开发"]},
            {"dimension": "岗位类别", "option": "技术", "why": "真的", "targets": ["开发"]},
        ])
        out = _run(plan_buckets(MANUAL, QUOTAS, "", model=model))
        assert [b["option"] for b in out] == ["技术"]

    def test_a_dimension_not_in_the_manual_is_dropped(self):
        model = _FakeModel([
            {"dimension": "学历要求", "option": "本科", "why": "编的", "targets": ["开发"]},
        ])
        assert _run(plan_buckets(MANUAL, QUOTAS, "", model=model)) == []

    def test_targets_outside_the_quota_table_are_dropped(self):
        model = _FakeModel([
            {"dimension": "岗位类别", "option": "技术", "why": "x", "targets": ["开发", "机器学习"]},
        ])
        out = _run(plan_buckets(MANUAL, QUOTAS, "", model=model))
        assert out[0]["targets"] == ["开发"]

    def test_a_bucket_with_no_valid_target_is_dropped(self):
        """一个桶如果对不上任何目标类别，扫它就是纯浪费预算。"""
        model = _FakeModel([
            {"dimension": "岗位类别", "option": "职能", "why": "x", "targets": ["行政"]},
        ])
        assert _run(plan_buckets(MANUAL, QUOTAS, "", model=model)) == []

    def test_unparseable_response_raises(self):
        model = _FakeModel("我不知道")
        with pytest.raises(ValueError):
            _run(plan_buckets(MANUAL, QUOTAS, "", model=model))

    def test_empty_plan_is_a_valid_result(self):
        """站上确实没有相关的桶，是合法结论。返回空列表，**不抛**。"""
        model = _FakeModel([])
        assert _run(plan_buckets(MANUAL, QUOTAS, "", model=model)) == []

    def test_a_dimension_missing_name_never_matches_an_entry_missing_dimension(self):
        """手册里某个 dim 缺 name、LLM 响应里某条 entry 又缺 dimension——两个畸形
        分别取 `.get()` 都会得到 None。如果 valid_options 里留了 None 这个 key，
        两者就会意外匹配通过。这个模块存在的全部意义就是挡住 LLM 编出来的东西，
        不能被这种巧合绕过。"""
        model = _FakeModel([
            {"option": "神秘选项", "why": "编的", "targets": ["开发"]},
        ])
        out = _run(plan_buckets(MANUAL_WITH_UNNAMED_DIM, QUOTAS, "", model=model))
        assert out == []

    def test_prompt_carries_the_manual_dimensions_and_the_quotas(self):
        model = _FakeModel([])
        _run(plan_buckets(MANUAL, QUOTAS, "只看深圳", model=model))
        blob = str(model.prompts)
        assert "青云课题" in blob and "AI NATIVE" in blob and "只看深圳" in blob
