"""Layer 1 安全边界的守门测试。

这是**整个多站点模块里最不能出错的一处**：Layer 1 改成 agent 自主导航后，`click`
成了一个 agent 可以任意调用的工具，而"提交"在投递页上就是个普通按钮。误点一次 =
对真实企业投出一份没人审过的申请，不可撤销。所以这里既测"该拦的拦住了"，也测
"不该拦的没误伤"——后者同样重要：把入口按钮也拦掉的话，Layer 1 连表单都进不去，
表现为"什么都识别不到"，比拦不住更难查。

快照 fixture 复用 tests/test_layer1_agent.py 里那份真机抓的拓竹申请表快照，
其中 uid=2_59 是页面上真实的提交按钮。
"""
import asyncio

import pytest

from multisite.safe_tools import label_for_uid, looks_like_submit, make_guarded_click
from tests.test_layer1_agent import REAL_FORM_SNAPSHOT


class TestLooksLikeSubmit:
    @pytest.mark.parametrize("label", [
        "提交", "提交申请", "确认提交", "Submit", "SUBMIT",
        "下一步", "Next Step", "确认投递", "立即投递", "投递简历",
        "确认申请", "完成投递", "保存并提交", "Send Application",
    ])
    def test_terminal_actions_are_blocked(self, label):
        assert looks_like_submit(label) is True

    @pytest.mark.parametrize("label", [
        # 入口按钮：必须放行，否则 Layer 1 进不了表单。
        "申请职位", "立即申请", "我要投递", "Apply", "Apply Now", "报名",
        # 普通表单元素/导航，跟提交无关。
        "姓名", "上传简历", "选择文件", "返回", "取消", "首页", "第 2 页",
    ])
    def test_entry_and_neutral_actions_are_allowed(self, label):
        assert looks_like_submit(label) is False

    def test_empty_label_is_not_submit(self):
        # 空标签意味着"这个元素没有 accessible name"，不是"它是提交按钮"。
        assert looks_like_submit("") is False
        assert looks_like_submit("   ") is False


class TestLabelForUid:
    def test_reads_real_submit_button_label(self):
        # 真机上这个按钮写的是「提交简历」而不是光「提交」——关键词表用的是子串
        # 匹配，所以照样命中。断言写真实值，不写我以为的值。
        assert label_for_uid(REAL_FORM_SNAPSHOT, "2_59") == "提交简历"

    def test_real_submit_button_is_actually_blocked(self):
        # 端到端确认这份真机快照里的提交按钮确实会被拦——纯字符串单元测试
        # 覆盖不到"真实页面上的措辞和关键词表对不对得上"这件事。
        assert looks_like_submit(label_for_uid(REAL_FORM_SNAPSHOT, "2_59")) is True

    def test_real_upload_buttons_are_not_blocked(self):
        # 同一份快照里的两个上传按钮必须放行，否则 Layer 1 传不了简历。
        for uid in ("2_21", "2_22"):
            assert looks_like_submit(label_for_uid(REAL_FORM_SNAPSHOT, uid)) is False

    def test_missing_uid_returns_none_not_empty_string(self):
        # None（快照里没这个 uid，无从判断）和 ""（有这个元素但没名字）语义不同，
        # 守门逻辑对两者都放行但原因不同，不能合并成一个返回值。
        assert label_for_uid(REAL_FORM_SNAPSHOT, "nonexistent_uid") is None


class _FakeClick:
    """记录被真正放行的点击。"""
    name = "click"

    def __init__(self):
        self.calls = []

    async def ainvoke(self, args):
        self.calls.append(args)
        return "clicked"


def _run(coro):
    return asyncio.run(coro)


class TestGuardedClick:
    def test_blocks_real_submit_button_and_does_not_call_through(self):
        fake = _FakeClick()
        guarded = make_guarded_click(fake, lambda: REAL_FORM_SNAPSHOT)

        result = _run(guarded.ainvoke({"uid": "2_59"}))

        assert "REFUSED" in result
        # 关键断言：底层 click 一次都没被调用。只检查返回值不够——如果实现里
        # 先点了再返回拒绝文本，测试照样绿，而真实后果已经发生了。
        assert fake.calls == []

    def test_allows_normal_element(self):
        fake = _FakeClick()
        guarded = make_guarded_click(fake, lambda: REAL_FORM_SNAPSHOT)

        result = _run(guarded.ainvoke({"uid": "2_22"}))  # "选择文件"，上传按钮

        assert result == "clicked"
        assert fake.calls == [{"uid": "2_22", "dblClick": False}]

    def test_allows_uid_missing_from_snapshot_fail_open(self):
        # 刻意的 fail-open：大量可交互元素没有 accessible name，fail-closed 会让
        # agent 寸步难行。取舍写在 make_guarded_click 的 docstring 里，这个测试
        # 是它的守门——如果有人"顺手改成更安全的 fail-closed"，这里会红。
        fake = _FakeClick()
        guarded = make_guarded_click(fake, lambda: REAL_FORM_SNAPSHOT)

        result = _run(guarded.ainvoke({"uid": "totally_unknown"}))

        assert result == "clicked"

    def test_tool_is_still_named_click(self):
        # agent 那边的 prompt 和工具选择都按 "click" 这个名字来，包装之后名字
        # 变了的话 agent 会找不到工具（而且报错发生在很远的地方）。
        guarded = make_guarded_click(_FakeClick(), lambda: "")
        assert guarded.name == "click"


class TestAgentToolsetWiring:
    """守"守法有没有真的接到 agent 手上"。

    make_guarded_click 自己的行为在上面测过了，但那不能保证 build_agent_toolset
    真的用了它——如果有人把那一行改回透传原始 click，上面所有测试照样全绿，而
    agent 就拿到了一个能点提交的工具。这一组就是为了让那种改动变红。
    """

    @staticmethod
    def _fake_mcp_tools():
        from langchain_core.tools import StructuredTool

        async def _noop(**kw):
            return "RAW-CLICK-RAN"

        names = ["navigate_page", "take_snapshot", "click", "upload_file", "wait_for", "fill"]
        return [StructuredTool.from_function(coroutine=_noop, name=n, description=n) for n in names]

    def _toolset(self):
        from multisite.layer1_agent import build_agent_toolset

        async def _snap():
            return REAL_FORM_SNAPSHOT

        return build_agent_toolset(
            self._fake_mcp_tools(),
            snapshot_provider=lambda: REAL_FORM_SNAPSHOT,
            snapshot_taker=_snap,
        )

    def test_click_in_agent_toolset_refuses_submit(self):
        click = next(t for t in self._toolset() if t.name == "click")
        result = _run(click.ainvoke({"uid": "2_59"}))  # 真机快照里的「提交简历」
        assert "REFUSED" in result
        assert "RAW-CLICK-RAN" not in result

    def test_click_in_agent_toolset_still_passes_normal_elements(self):
        click = next(t for t in self._toolset() if t.name == "click")
        assert _run(click.ainvoke({"uid": "2_22"})) == "RAW-CLICK-RAN"

    def test_no_duplicate_click_or_snapshot_tools(self):
        # 透传时忘了排除原始 click 的话，工具集里会有两个同名工具，agent 可能
        # 挑到没守法的那个——而且这种重复不会报错，只会静默失效。
        names = [t.name for t in self._toolset()]
        assert names.count("click") == 1
        assert names.count("take_snapshot") == 1

    def test_other_tools_are_passed_through(self):
        names = {t.name for t in self._toolset()}
        for expected in ("navigate_page", "upload_file", "wait_for", "fill"):
            assert expected in names
