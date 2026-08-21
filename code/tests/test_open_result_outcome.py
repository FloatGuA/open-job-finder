"""导航 agent 汇报"表单为什么没打开"，而不只是"没打开"。

真机 id=72（用户已手动投过）那次：agent 正确认出页面上的「已投递」、正确地没去投，
但结构化字段里留下的是 `form_opened=false` + `successful` + `run_end: done`——
**跟"根本找不到申请入口"长得一模一样**。前者是干得对，后者是干不了活儿，
而看日志的人无法区分。属于「谎报成功」那一族。

**枚举取代布尔，不是并列。** 同时留 `form_opened` 和 `outcome` 就是给同一件事
留两个真相源，agent 迟早会报出 `form_opened=true` + `outcome=no_entry` 这种
自相矛盾的组合——本项目已经栽过五次同一契约两份实现。
"""
import asyncio

import pytest

from multisite.layer1_agent import (
    OpenApplicationOutput,
    _summarize_open_application,
    make_record_open_result_tool,
)


def _call(sink: dict, **kwargs) -> str:
    tool = make_record_open_result_tool(sink)
    return asyncio.run(tool.ainvoke(kwargs))


class TestTheAgentReportsAReason:
    def test_opened_is_the_only_outcome_that_means_the_form_opened(self):
        sink: dict = {}
        _call(sink, outcome="opened", resume_uploaded=True)
        assert sink["outcome"] == "opened"
        assert OpenApplicationOutput(**sink).form_opened is True

    @pytest.mark.parametrize("outcome", ["already_applied", "no_entry", "blocked"])
    def test_every_other_outcome_means_it_did_not(self, outcome):
        sink: dict = {}
        _call(sink, outcome=outcome, resume_uploaded=False)
        assert OpenApplicationOutput(**sink).form_opened is False

    def test_already_applied_is_distinguishable_from_no_entry(self):
        """**这就是这条缺口的全部**：两者都是"表单没打开"，但一个是干得对、
        一个是干不了活儿。以前它们在结构化字段里完全一样。"""
        did_apply: dict = {}
        no_entry: dict = {}
        _call(did_apply, outcome="already_applied", resume_uploaded=False)
        _call(no_entry, outcome="no_entry", resume_uploaded=False)

        a, b = OpenApplicationOutput(**did_apply), OpenApplicationOutput(**no_entry)
        assert a.form_opened == b.form_opened          # 老字段确实分不开
        assert a.outcome != b.outcome                  # 新字段分得开

    def test_form_opened_cannot_contradict_the_outcome(self):
        """`form_opened` 是**派生**的，不是 agent 报上来的第二个字段——
        所以它不可能跟 outcome 打架。

        这里连"硬塞一个 form_opened 进去"都试了：它进不了 sink，派生值照样
        跟着 outcome 走。agent 想让这两个字段自相矛盾都做不到。"""
        sink: dict = {}
        _call(sink, outcome="no_entry", resume_uploaded=False, form_opened=True)

        assert "form_opened" not in sink
        assert OpenApplicationOutput(**sink).form_opened is False


class TestWhenTheAgentSaysNothing:
    def test_not_reporting_is_its_own_outcome(self):
        """agent 没调这个工具，跟它报了 no_entry 是两回事。把没汇报塞进
        no_entry 是替它编一个它没说过的结论。"""
        assert OpenApplicationOutput().outcome == "unknown"
        assert OpenApplicationOutput().form_opened is False


class TestItReachesTheLog:
    def test_summary_carries_the_reason(self):
        """枚举只有进了 run 日志才算真的能区分——这是唯一的消费方。"""
        out = {"open_result": OpenApplicationOutput(outcome="already_applied")}
        assert _summarize_open_application(out)["outcome"] == "already_applied"

    def test_summary_survives_a_missing_result(self):
        assert _summarize_open_application({})["outcome"] == "unknown"
