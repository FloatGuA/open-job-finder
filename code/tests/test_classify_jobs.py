"""岗位分类：批量、纯判断、可测。

**不走 ReAct 循环**是刻意的（spec §2.1 同理）：它不需要"看一眼再决定下一步"，
输入是文本、输出是标签。做成普通 LLM 调用换来的是**可单测 + 可 eval**。
"""
import asyncio
import json

import pytest

from multisite.classify import classify_jobs


def _run(c):
    return asyncio.run(c)

ITEMS = [
    {"title": "AI算法工程师", "jd": "职责：LLM 应用、Agent 工具开发", "site_category": "技术"},
    {"title": "服务运营 - 数据分析", "jd": "职责：售后数据看板", "site_category": "市场"},
]
QUOTAS = {"AI NATIVE": 3, "开发": 5, "运营": 3}


class _FakeModel:
    """按脚本回话的假模型。真实调用会走 langchain 的 `.ainvoke`。"""

    def __init__(self, payload):
        self.payload = payload
        self.prompts = []

    async def ainvoke(self, messages):
        self.prompts.append(messages)

        class _R:
            content = self.payload if isinstance(self.payload, str) else json.dumps(
                self.payload, ensure_ascii=False)
        return _R()


class TestClassifyJobs:
    def test_assigns_a_category_to_each_item(self):
        model = _FakeModel([{"index": 0, "category": "AI NATIVE", "why": "LLM/Agent"},
                            {"index": 1, "category": "运营", "why": "数据看板"}])
        out = _run(classify_jobs(ITEMS, QUOTAS, model=model))
        assert [o["category"] for o in out] == ["AI NATIVE", "运营"]
        assert out[0]["why"]

    def test_keeps_the_original_fields(self):
        model = _FakeModel([{"index": 0, "category": "AI NATIVE", "why": "x"},
                            {"index": 1, "category": "运营", "why": "y"}])
        out = _run(classify_jobs(ITEMS, QUOTAS, model=model))
        assert out[0]["title"] == "AI算法工程师"
        assert out[0]["jd"].startswith("职责")

    def test_a_category_outside_the_quota_table_is_rejected(self):
        """类别必须来自配额表。放任 LLM 自造类别名，配额就形同虚设
        （它报一个新名字就绕过了上限）。"""
        model = _FakeModel([{"index": 0, "category": "机器学习", "why": "x"},
                            {"index": 1, "category": "运营", "why": "y"}])
        out = _run(classify_jobs(ITEMS, QUOTAS, model=model))
        assert out[0]["category"] == ""
        assert "机器学习" in out[0]["why"]

    def test_a_missing_index_leaves_that_item_unclassified(self):
        """LLM 少回一条时，**不能让后面的答案错位顶上**——那会给岗位安错标签，
        而结果看起来完全正常。按 index 对齐，缺的就是空。"""
        model = _FakeModel([{"index": 1, "category": "运营", "why": "y"}])
        out = _run(classify_jobs(ITEMS, QUOTAS, model=model))
        assert out[0]["category"] == ""
        assert out[1]["category"] == "运营"

    def test_unparseable_response_raises(self):
        """整段回不成 JSON 是**失败**，不是"都没分上类"。
        静默返回全空会让上层把它当成"这一页没有符合的岗位"。"""
        model = _FakeModel("对不起我不会")
        with pytest.raises(ValueError):
            _run(classify_jobs(ITEMS, QUOTAS, model=model))

    def test_empty_input_does_not_call_the_model(self):
        model = _FakeModel([])
        assert _run(classify_jobs([], QUOTAS, model=model)) == []
        assert model.prompts == []

    def test_prompt_carries_title_jd_and_site_category(self):
        """三样都要进 prompt：只给标题的话，「职责里出现 LLM/Agent 就归 AI NATIVE」
        那条核心规则一个字都执行不了。"""
        model = _FakeModel([{"index": 0, "category": "AI NATIVE", "why": "x"},
                            {"index": 1, "category": "运营", "why": "y"}])
        _run(classify_jobs(ITEMS, QUOTAS, model=model))
        blob = str(model.prompts)
        assert "AI算法工程师" in blob and "Agent 工具开发" in blob and "技术" in blob
