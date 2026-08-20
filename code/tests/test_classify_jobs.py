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
        回答这一项（不是老实说"提不出标题"）。这里的兜底是**截断过的原文**
        （FIX-5），只是 ITEMS[0] 的原始 title 本来就很短（8 个字），截断是
        无操作，所以看起来跟"原样透传"一样。"""
        model = _FakeModel([{"index": 0, "category": "AI NATIVE", "why": "x"}])
        out = _run(classify_jobs(ITEMS, QUOTAS, model=model))
        assert out[0]["title"] == "AI算法工程师"


class TestClassifyJobsNeverLeaksTheRawRowTextAsTitle:
    """Ruling 10 的修复只覆盖了 happy path（模型给了干净 title 就用它）。
    两条生产路径仍会让 `title` 变成整行原文，无长度上限：
      ① 模型跳过某个 index（`entry is None`）；
      ② 模型回的条目里没有 `title` 键。
    旧的 `text[:200]` 兜底已经删了，退回"保留原样透传"就是退回整行原文——
    一路落进 `pending_jobs.title`，还会改变 `resume_matcher.pick_for_job`
    实际选中的简历（title 权重 3）。

    生产里 `title` 这个 key 永远存在（`scan_buckets._classify` 把
    `it.get("text", "")` 映到 `title`），值是整行卡片文本——这里必须用同样
    的真实形状，不能像旧测试那样传一个已经很干净的短字符串（否则测不出
    截断兜底有没有真的生效）。"""

    RAW_ROW_TEXT = ("AI全栈工程师 技术 ｜ 应届毕业生 ｜ CDG CSIG IEG PCG TEG WXG "
                    "工作地点： 深圳总部 北京 上海 广州 成都 杭州 " * 3)

    def test_llm_skipping_the_index_does_not_leak_raw_text(self):
        items = [{"title": self.RAW_ROW_TEXT, "jd": "", "site_category": "技术"}]
        model = _FakeModel([])  # 没回任何一条，index 0 缺失
        out = _run(classify_jobs(items, QUOTAS, model=model))
        assert out[0]["title"] != self.RAW_ROW_TEXT
        assert len(out[0]["title"]) < len(self.RAW_ROW_TEXT)

    def test_llm_response_missing_the_title_key_does_not_leak_raw_text(self):
        items = [{"title": self.RAW_ROW_TEXT, "jd": "", "site_category": "技术"}]
        model = _FakeModel([{"index": 0, "category": "开发", "why": "x"}])  # 没给 title
        out = _run(classify_jobs(items, QUOTAS, model=model))
        assert out[0]["title"] != self.RAW_ROW_TEXT
        assert len(out[0]["title"]) < len(self.RAW_ROW_TEXT)


class TestClassifyJobsLoadsPromptThroughPromptManager:
    """FIX-2：用户在设置页编辑 `layer1_classify_jobs`，写进
    `data/prompts_override/layer1_classify_jobs.md`；只有 `PromptManager.load()`
    会去看那个目录。之前这里直接 `_PROMPT_PATH.read_text()`，覆盖层形同虚设——
    用户保存成功、页面显示"已修改"，但运行时用的还是 git 默认值。"""

    def test_override_file_is_used_instead_of_the_default(self, tmp_path, monkeypatch):
        import multisite.classify as classify_mod
        from services.prompt_manager import PromptManager

        pm = PromptManager(override_dir=tmp_path)
        pm.save_override(
            "layer1_classify_jobs",
            pm.get_default("layer1_classify_jobs").replace(
                "{{quota_table}}", "【override 标记】{{quota_table}}"),
        )
        monkeypatch.setattr(classify_mod, "PromptManager",
                            lambda *a, **k: PromptManager(override_dir=tmp_path))

        model = _FakeModel([{"index": 0, "category": "AI NATIVE", "why": "x"}])
        _run(classify_jobs(ITEMS[:1], QUOTAS, model=model))

        assert "【override 标记】" in str(model.prompts)


class TestClassifyJobsGoldenExamples:
    """FIX-4：人工纠正必须能教回分类 prompt，否则用户在审批页标的 golden 就是
    白标——`preferences.render_golden_examples` 早就写好了，只是没人传进来。"""

    def test_golden_examples_are_rendered_into_the_prompt(self):
        model = _FakeModel([{"index": 0, "category": "AI NATIVE", "why": "x"},
                            {"index": 1, "category": "运营", "why": "y"}])
        _run(classify_jobs(ITEMS, QUOTAS, model=model,
                           golden_examples="「某某岗」归类为「开发」是错的，应该归「AI NATIVE」"))
        blob = str(model.prompts)
        assert "某某岗" in blob and "应该归「AI NATIVE」" in blob

    def test_no_golden_examples_falls_back_to_the_placeholder_text(self):
        model = _FakeModel([{"index": 0, "category": "AI NATIVE", "why": "x"},
                            {"index": 1, "category": "运营", "why": "y"}])
        _run(classify_jobs(ITEMS, QUOTAS, model=model))
        assert "本次未提供历史纠正样例" in str(model.prompts)
