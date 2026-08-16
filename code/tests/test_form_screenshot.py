"""Checkpoint 2 的表单截图：拍全 + 拍完把页面还原。

背景（2026-08-17 真机）：拓竹申请表的三张截图尺寸一模一样（1209x1269），
正好等于视口。原因不是 fullPage 没传——传了，而是这个站把表单放在一个内部
滚动容器里（`section.atsx-layout`，clientHeight 1269 / scrollHeight 2403），
`document.documentElement.scrollHeight` 因此一直等于视口高度，fullPage 拍出来
就只有一半。审批人要核对的「学校名称」「起止时间」全在被裁掉的那一半里。
"""
import asyncio

import pytest

from multisite import layer1_agent


class FakeTool:
    def __init__(self, name, calls, result=None, raises=None, writes_file=False):
        self.name = name
        self._calls = calls
        self._result = result
        self._raises = raises
        self._writes_file = writes_file

    async def ainvoke(self, args):
        self._calls.append((self.name, args))
        if self._raises is not None:
            raise self._raises
        if self._writes_file:
            from pathlib import Path
            Path(args["filePath"]).write_bytes(b"\x89PNG fake")
        return self._result


def _tools(calls, *, shot_raises=None, eval_raises=None):
    return [
        FakeTool("evaluate_script", calls, result="{}", raises=eval_raises),
        FakeTool("take_screenshot", calls, raises=shot_raises, writes_file=True),
    ]


def _run(tools, dest_dir):
    return asyncio.run(layer1_agent.capture_form_screenshot(tools, dest_dir=dest_dir))


def _script_of(call):
    return call[1].get("function", "")


class TestCapturesTheWholeForm:
    def test_inner_scroll_containers_are_unlocked_before_the_shot(self, tmp_path):
        """光靠 fullPage 不够：文档本身不滚动时它等于视口截图。"""
        calls = []
        _run(_tools(calls), tmp_path)

        names = [c[0] for c in calls]
        assert names.index("evaluate_script") < names.index("take_screenshot")
        unlock = _script_of(calls[0])
        # 判据是"按 overflow 找真正在滚的元素"，不是写死某个站点的 class 名——
        # 拓竹叫 atsx-layout，下一个站不会叫这个。
        assert "overflowY" in unlock
        assert "scrollHeight" in unlock

    def test_full_page_is_still_requested(self, tmp_path):
        """解锁让文档变长，fullPage 才有东西可拍——两者缺一不可。"""
        calls = []
        _run(_tools(calls), tmp_path)

        shot = next(c for c in calls if c[0] == "take_screenshot")
        assert shot[1]["fullPage"] is True

    def test_returns_the_saved_file_name(self, tmp_path):
        calls = []
        name = _run(_tools(calls), tmp_path)

        assert name.endswith("_form.png")
        assert (tmp_path / name).is_file()


class TestPageIsRestored:
    def test_restored_after_a_successful_shot(self, tmp_path):
        """样式覆盖是临时的：留在页面上会让后续 agent 操作面对一个变形的表单。"""
        calls = []
        _run(_tools(calls), tmp_path)

        assert [c[0] for c in calls] == [
            "evaluate_script", "take_screenshot", "evaluate_script"]
        assert "remove" in _script_of(calls[-1])

    def test_restored_even_when_the_screenshot_fails(self, tmp_path):
        """截图失败不该把页面留在解锁状态——这才是 finally 的意义。"""
        calls = []
        name = _run(_tools(calls, shot_raises=RuntimeError("boom")), tmp_path)

        assert name == ""
        assert [c[0] for c in calls] == [
            "evaluate_script", "take_screenshot", "evaluate_script"]
        assert "remove" in _script_of(calls[-1])


class TestNoMisleadingHalfShot:
    def test_unlock_failure_yields_no_screenshot_at_all(self, tmp_path):
        """解锁失败就别拍。

        半截图比没有截图更糟：审批人看到一张图，会以为「表单就这些字段」，
        而真正要核对的那些正好在被裁掉的下半页——这正是 2026-08-17 那次的现象。
        """
        calls = []
        name = _run(_tools(calls, eval_raises=RuntimeError("csp blocked")), tmp_path)

        assert name == ""
        assert "take_screenshot" not in [c[0] for c in calls]
