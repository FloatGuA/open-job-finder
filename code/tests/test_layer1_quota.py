"""选岗配额（Checkpoint 1 前半段）的测试。

**为什么这组测试值得存在**：v2.22.0 真机跑回来 5 个岗位全是"运营"，产品/开发/
日常实习一个都没有——而每一条单看都符合条件，所以从结果里完全看不出失败。配额
就是为了让这种偏斜变得可见且可控，而配额算术本身是纯函数、跑不到真浏览器也能测。

守三件事：
1. 名额满了必须**拒绝**，不是记下来再截断（截断按记录顺序，会悄悄砍掉别的类别）；
2. 类别必须走枚举，agent 报一个新名字不能绕过配额；
3. 进度播报里要有"还差什么"——那是 agent 的主要导航信号，不是日志。
"""
import asyncio

import pytest

from multisite.layer1_agent import (
    FoundJob,
    describe_progress,
    make_record_job_tool,
    remaining_quota,
)

QUOTAS = {"产品": 2, "开发": 3}


def _run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


def _tool(sink, quotas=None):
    return make_record_job_tool(sink, quotas if quotas is not None else QUOTAS)


def _call(tool, url, category, title=""):
    return _run(tool.ainvoke({"url": url, "category": category, "title": title}))


class TestRemainingQuota:
    def test_empty_sink_means_everything_remains(self):
        assert remaining_quota(QUOTAS, []) == {"产品": 2, "开发": 3}

    def test_counts_only_matching_category(self):
        sink = [FoundJob(url="http://a", category="产品")]
        assert remaining_quota(QUOTAS, sink) == {"产品": 1, "开发": 3}

    def test_unknown_category_in_sink_does_not_crash(self):
        # 理论上进不来（record_job 拦了），但 remaining_quota 是纯函数，
        # 被别处复用时不该因为一条脏数据炸掉。
        sink = [FoundJob(url="http://a", category="不存在的类")]
        assert remaining_quota(QUOTAS, sink) == {"产品": 2, "开发": 3}


class TestRecordJobQuota:
    def test_records_within_quota(self):
        sink = []
        result = _call(_tool(sink), "https://x/1", "产品", "产品经理")
        assert "已记录" in result
        assert len(sink) == 1
        assert sink[0].category == "产品"

    def test_refuses_when_category_full(self):
        sink = []
        tool = _tool(sink)
        _call(tool, "https://x/1", "产品")
        _call(tool, "https://x/2", "产品")
        result = _call(tool, "https://x/3", "产品")

        assert "名额已经满" in result
        assert len(sink) == 2, "满额之后不能再进 sink——截断兜不住，会砍错类别"

    def test_full_category_does_not_block_other_categories(self):
        sink = []
        tool = _tool(sink)
        _call(tool, "https://x/1", "产品")
        _call(tool, "https://x/2", "产品")
        result = _call(tool, "https://x/3", "开发")

        assert "已记录" in result
        assert len(sink) == 3

    @pytest.mark.parametrize("bogus", ["运营", "", "  ", "产品经理"])
    def test_rejects_category_outside_the_enum(self, bogus):
        # agent 报一个没配置的类别就能凭空造出名额——配额必须是封闭集合。
        sink = []
        result = _call(_tool(sink), "https://x/1", bogus)
        assert "不是有效类别" in result
        assert sink == []

    def test_rejects_non_http_url(self):
        sink = []
        assert "记录失败" in _call(_tool(sink), "/campus/position/1", "产品")
        assert sink == []

    def test_duplicate_url_is_not_recorded_twice(self):
        sink = []
        tool = _tool(sink)
        _call(tool, "https://x/1", "产品")
        result = _call(tool, "https://x/1", "开发")
        assert len(sink) == 1
        assert "已经记过" in result

    def test_tool_description_lists_the_allowed_categories(self):
        # agent 是从 description 里知道能填哪些 category 的；漏了它只能瞎猜，
        # 然后每次都撞"不是有效类别"，白烧步数。
        desc = _tool([]).description
        assert "产品" in desc and "开发" in desc


class TestDescribeProgress:
    def test_reports_what_is_still_missing(self):
        sink = [FoundJob(url="https://x/1", category="产品")]
        text = describe_progress(QUOTAS, sink)
        assert "产品 1/2" in text
        assert "还差" in text and "开发 3 个" in text

    def test_tells_agent_to_stop_when_all_quotas_are_full(self):
        """终止条件靠这句话传达。

        没有它，agent 只能靠"翻够 N 页"停——那是跟目标无关的代理指标，上一版
        就是这么在翻页之间来回跳到撞上 recursion limit 的。
        """
        sink = [
            FoundJob(url="https://x/1", category="产品"),
            FoundJob(url="https://x/2", category="产品"),
            FoundJob(url="https://x/3", category="开发"),
            FoundJob(url="https://x/4", category="开发"),
            FoundJob(url="https://x/5", category="开发"),
        ]
        text = describe_progress(QUOTAS, sink)
        assert "所有名额已满" in text
        assert "立刻停止" in text
        assert "还差" not in text


class TestKnownUrlsDoNotConsumeQuota:
    """**agent 跨 run 没有记忆**，重跑同一个站必然重新找到上次那批岗位。

    2026-08-14 第三次真机跑抬到了：找回 10 个、其中 5 个已在库里，
    「开发 5/5」里 3 个名额花在已经躺在审批队列的岗位上，真正的新岗位
    反而被配额挡在门外——**每跑一次，能发现的新东西就少一截**。
    """

    def test_known_url_is_refused_without_consuming_quota(self):
        sink = []
        tool = make_record_job_tool(sink, QUOTAS, known_urls={"https://x/old"})
        result = _call(tool, "https://x/old", "产品")

        assert "已经收录过了，不占名额" in result
        assert sink == []
        assert remaining_quota(QUOTAS, sink)["产品"] == 2, "名额一个都不能被吃掉"

    def test_new_urls_still_record_normally(self):
        sink = []
        tool = make_record_job_tool(sink, QUOTAS, known_urls={"https://x/old"})
        assert "已记录" in _call(tool, "https://x/new", "产品")
        assert len(sink) == 1

    def test_known_url_check_runs_before_the_quota_check(self):
        """名额满了之后，已收录的岗位应该还是报“已收录”而不是“名额满”——
        后者会让 agent 以为这一类已经收齐了。"""
        sink = []
        tool = make_record_job_tool(sink, QUOTAS, known_urls={"https://x/old"})
        _call(tool, "https://x/a", "产品")
        _call(tool, "https://x/b", "产品")  # 产品 2/2 满
        assert "已经收录过了，不占名额" in _call(tool, "https://x/old", "产品")

    def test_defaults_to_no_known_urls(self):
        sink = []
        assert "已记录" in _call(make_record_job_tool(sink, QUOTAS), "https://x/1", "产品")
