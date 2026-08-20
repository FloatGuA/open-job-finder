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




class TestPlanBuckets:
    def test_returns_the_planned_buckets(self):
        model = _FakeRouter([
            {"dimension": "岗位类别", "option": "青云课题", "why": "AI 方向", "targets": ["AI NATIVE"]},
            {"dimension": "岗位类别", "option": "技术", "why": "开发岗在这里", "targets": ["开发"]},
        ])
        out = _run(plan_buckets(MANUAL, QUOTAS, "只看深圳", router=model))
        assert [b["option"] for b in out] == ["青云课题", "技术"]
        assert out[0]["targets"] == ["AI NATIVE"]

    def test_an_option_not_in_the_manual_is_dropped(self):
        """LLM 编一个手册里没有的选项，代码照着去点必然点空——而"点空"表现为
        "这个桶没有岗位"，跟真的没岗位分不开。在这里就丢掉。"""
        model = _FakeRouter([
            {"dimension": "岗位类别", "option": "量子计算", "why": "编的", "targets": ["开发"]},
            {"dimension": "岗位类别", "option": "技术", "why": "真的", "targets": ["开发"]},
        ])
        out = _run(plan_buckets(MANUAL, QUOTAS, "", router=model))
        assert [b["option"] for b in out] == ["技术"]

    def test_a_dimension_not_in_the_manual_is_dropped(self):
        model = _FakeRouter([
            {"dimension": "学历要求", "option": "本科", "why": "编的", "targets": ["开发"]},
        ])
        assert _run(plan_buckets(MANUAL, QUOTAS, "", router=model)) == []

    def test_targets_outside_the_quota_table_are_dropped(self):
        model = _FakeRouter([
            {"dimension": "岗位类别", "option": "技术", "why": "x", "targets": ["开发", "机器学习"]},
        ])
        out = _run(plan_buckets(MANUAL, QUOTAS, "", router=model))
        assert out[0]["targets"] == ["开发"]

    def test_a_bucket_with_no_valid_target_is_dropped(self):
        """一个桶如果对不上任何目标类别，扫它就是纯浪费预算。"""
        model = _FakeRouter([
            {"dimension": "岗位类别", "option": "职能", "why": "x", "targets": ["行政"]},
        ])
        assert _run(plan_buckets(MANUAL, QUOTAS, "", router=model)) == []

    def test_unparseable_response_raises(self):
        model = _FakeRouter("我不知道")
        with pytest.raises(ValueError):
            _run(plan_buckets(MANUAL, QUOTAS, "", router=model))

    def test_empty_plan_is_a_valid_result(self):
        """站上确实没有相关的桶，是合法结论。返回空列表，**不抛**。"""
        model = _FakeRouter([])
        assert _run(plan_buckets(MANUAL, QUOTAS, "", router=model)) == []

    def test_a_dimension_missing_name_never_matches_an_entry_missing_dimension(self):
        """手册里某个 dim 缺 name、LLM 响应里某条 entry 又缺 dimension——两个畸形
        分别取 `.get()` 都会得到 None。如果 valid_options 里留了 None 这个 key，
        两者就会意外匹配通过。这个模块存在的全部意义就是挡住 LLM 编出来的东西，
        不能被这种巧合绕过。"""
        model = _FakeRouter([
            {"option": "神秘选项", "why": "编的", "targets": ["开发"]},
        ])
        out = _run(plan_buckets(MANUAL_WITH_UNNAMED_DIM, QUOTAS, "", router=model))
        assert out == []

    def test_prompt_carries_the_manual_dimensions_and_the_quotas(self):
        model = _FakeRouter([])
        _run(plan_buckets(MANUAL, QUOTAS, "只看深圳", router=model))
        blob = str(model.prompts)
        assert "青云课题" in blob and "AI NATIVE" in blob and "只看深圳" in blob


class TestPlanBucketsLoadsPromptThroughPromptManager:
    """FIX-2：用户在设置页编辑 `layer1_plan_buckets`，写进
    `data/prompts_override/layer1_plan_buckets.md`；只有 `PromptManager.load()`
    会去看那个目录。之前这里直接 `_PROMPT_PATH.read_text()`，覆盖层形同虚设——
    用户保存成功、页面显示"已修改"，但运行时用的还是 git 默认值。"""

    def test_override_file_is_used_instead_of_the_default(self, tmp_path, monkeypatch):
        import multisite.bucket_plan as bucket_plan_mod
        from services.prompt_manager import PromptManager

        pm = PromptManager(override_dir=tmp_path)
        pm.save_override(
            "layer1_plan_buckets",
            pm.get_default("layer1_plan_buckets").replace(
                "{{constraints}}", "【override 标记】{{constraints}}"),
        )
        monkeypatch.setattr(bucket_plan_mod, "PromptManager",
                            lambda *a, **k: PromptManager(override_dir=tmp_path))

        model = _FakeRouter([])
        _run(plan_buckets(MANUAL, QUOTAS, "只看深圳", router=model))

        assert "【override 标记】" in str(model.prompts)


class _FakeRouter:
    """假 ModelRouter：`complete(prompt=..., capability=...)` 返回 `(text, provider)`，
    跟 `services/llm_client.py` 的真接口同形（`info_pool` / `resume_tailor` 就是这么调的）。"""

    def __init__(self, payload):
        self.payload = payload
        self.calls = []
        # 老测试靠它检查渲染出来的 prompt 正文；`calls` 记的是完整调用参数。
        self.prompts = []

    def complete(self, prompt, system="", capability="balanced", **kw):
        self.calls.append({"prompt": prompt, "capability": capability})
        self.prompts.append(prompt)
        text = self.payload if isinstance(self.payload, str) else json.dumps(
            self.payload, ensure_ascii=False)
        return text, "fake-provider"


class TestPlanBucketsGoesThroughTheModelRouter:
    """`plan_buckets` 走项目统一的 `ModelRouter`，不再自己 new 一个写死的 DeepSeek。

    **收益不是"更整洁"**：多站点这条线此前完全绕开 `FallbackChain`——DeepSeek 打个嗝
    就是一次废跑，而且设置页换模型对它毫无作用。走 balanced 链之后，它跟 W1/W2 的
    `score_job` / `analyze_intent` / `info_pool` 用同一条链、同一套兜底。

    capability 选 `balanced` 而不是 `fast`/`powerful`：balanced 是这个项目里唯一
    真正有生产调用方的档（见 config.yaml 里 `llm.capabilities` 的注释）。
    """

    def test_it_calls_the_router_with_the_balanced_capability(self):
        # 维度/选项/目标类别都必须是 MANUAL 和 QUOTAS 里真实存在的——
        # 校验层会把编出来的整条丢掉，用假值等于在测校验层而不是测这条链路。
        router = _FakeRouter([
            {"dimension": "\u5c97\u4f4d\u7c7b\u522b", "option": "\u6280\u672f",
             "why": "", "targets": ["\u5f00\u53d1"]},
        ])
        out = _run(plan_buckets(MANUAL, QUOTAS, "", router=router))
        assert out, out
        assert len(router.calls) == 1
        assert router.calls[0]["capability"] == "balanced"

    def test_the_rendered_prompt_still_reaches_the_model(self):
        """换接缝不能把 prompt 弄丢——渲染出来的正文必须原样送进 router。"""
        router = _FakeRouter([])
        _run(plan_buckets(MANUAL, QUOTAS, "\u53ea\u770b\u6df1\u5733", router=router))
        assert "\u53ea\u770b\u6df1\u5733" in router.calls[0]["prompt"]
