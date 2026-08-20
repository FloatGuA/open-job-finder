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


class TestClassifyJobsExtractsTitleAndCompany:
    """修复轮 1：harvest_page（多站点抓取）拿不到干净标题，塞进输入 `title` 的
    其实是整行卡片文本。既然模型要读这段文本才能分类，顺手把标题/公司名择出来
    是免费的——设计稿 §3.7 的原意，Task 4 首版漏接了这一步。"""

    def test_output_includes_title_and_company(self):
        model = _FakeModel([
            {"index": 0, "category": "AI NATIVE", "why": "x",
             "title": "AI算法工程师", "company": "腾讯"},
            {"index": 1, "category": "运营", "why": "y",
             "title": "服务运营", "company": ""},
        ])
        out = _run(classify_jobs(ITEMS, QUOTAS, model=model))
        assert out[0]["title"] == "AI算法工程师"
        assert out[0]["company"] == "腾讯"
        # 读不出公司名是模型的合法答案（不是缺陷），空串要如实覆盖，不能被
        # 当成"没回答"而退回到别的什么值。
        assert out[1]["company"] == ""

    def test_extracted_title_is_not_the_whole_raw_row_text(self):
        """守门测试：`harvest_page` 抓到的候选没有干净标题，只有整行卡片文本
        （通过适配闭包塞进了 `title` 这个输入字段）。分类模型必须从里面择出
        真正的标题——**代码不能偷懒退回整段原文**，模型偷懒把整段原样返回
        也要能在这条测试里现出原形（因为 `_FakeModel` 明确回了一个不同于原文
        的干净标题，断言的是"用了模型给的值"，不是"输出非空"这种弱断言）。
        """
        raw_blob = ("AI全栈工程师 技术 ｜ 应届毕业生 ｜ CDG CSIG IEG PCG TEG WXG "
                   "工作地点： 深圳总部 北京 上海 广州 成都 杭州")
        items = [{"title": raw_blob, "jd": "", "site_category": "技术"}]
        model = _FakeModel([{"index": 0, "category": "开发", "why": "x",
                             "title": "AI全栈工程师", "company": "腾讯"}])

        out = _run(classify_jobs(items, QUOTAS, model=model))

        assert out[0]["title"] == "AI全栈工程师"
        assert out[0]["title"] != raw_blob

    def test_model_omitting_title_key_falls_back_to_the_original_input(self):
        """跟"给了空串"不同：`title` 这个 key 压根没出现在响应里，说明模型没
        回答这一项（不是老实说"提不出标题"），这时保留原样透传，不强行清空。"""
        model = _FakeModel([{"index": 0, "category": "AI NATIVE", "why": "x"}])
        out = _run(classify_jobs(ITEMS, QUOTAS, model=model))
        assert out[0]["title"] == "AI算法工程师"
