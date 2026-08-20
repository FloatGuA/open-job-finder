"""勾一个筛选选项：点标签、回读 checked 确认。

**真机根因（2026-08-21，join.qq.com）**：a11y 树里的 `checkbox "深圳"` 是一个
**0×0、opacity:0 的隐藏 `<input>`**（Element UI 的 `el-checkbox__original`），
Puppeteer 的 click 会等它"可交互"，必然超时：

```
INPUT.el-checkbox__original  0x0     ← a11y 树暴露成 checkbox 节点
  └ SPAN.el-checkbox__input  16x18
    └ LABEL.el-checkbox      178x40  ← 真正的点击区
```

可见的点击区在外层 LABEL 上，而 a11y 树把标签文字暴露成**紧跟其后的同名
`StaticText` 兄弟节点**。点它 → `checked` 立刻出现、总数 943→542。

**这是 Element UI / Ant Design 这类组件库的通用形态，不是某个站特有的**，
所以放执行器而不是 prompt：写一次全站通用，而且能强制"回读确认"。

**验证必须看 `checked`，不能看岗位总数**：实测总数是滞后的（勾上北京之后
总数纹丝不动，但 `checked` 立刻就有了）。拿滞后的量做判据会误报失败。
"""
import asyncio

import pytest
from langchain_core.tools import StructuredTool

from multisite.executors import set_filter_option


def _run(c):
    return asyncio.run(c)


BEFORE = ('## Latest page snapshot\n'
          'uid=2_0 tab "工作城市" expandable expanded\n'
          '  uid=3_0 checkbox "深圳"\n'
          '  uid=3_1 StaticText "深圳"\n'
          '  uid=3_2 checkbox "北京"\n'
          '  uid=3_3 StaticText "北京"\n')
AFTER = BEFORE.replace('uid=3_0 checkbox "深圳"', 'uid=3_0 checkbox "深圳" checked')


def _tools(snapshots, click_result="Successfully clicked on the element"):
    """`take_snapshot` 依次返回 snapshots，用完停在最后一张。"""
    calls = []
    state = {"n": 0}

    async def take_snapshot():
        i = min(state["n"], len(snapshots) - 1)
        state["n"] += 1
        return snapshots[i]

    async def click(uid: str):
        calls.append(("click", uid))
        return click_result

    tools = [StructuredTool.from_function(coroutine=f, name=n, description=n)
             for f, n in ((take_snapshot, "take_snapshot"), (click, "click"))]
    return tools, calls


class TestSetFilterOption:
    def test_clicks_the_label_not_the_hidden_checkbox(self):
        """点 `checkbox` 节点永远超时（0×0 隐藏 input）。必须点紧跟其后的同名
        `StaticText`——那才对应可见的 LABEL。"""
        tools, calls = _tools([BEFORE, AFTER])
        ok, why = _run(set_filter_option("深圳", tools))
        assert ok, why
        assert calls == [("click", "3_1")], f"点错了目标：{calls}"

    def test_confirms_by_reading_back_checked(self):
        """点完报 OK 不等于设上了——真机上点 StaticText 会返回
        "Successfully clicked" 而筛选并没生效过。必须回读 `checked`。"""
        tools, _ = _tools([BEFORE, BEFORE])   # 点了但状态没变
        ok, why = _run(set_filter_option("深圳", tools))
        assert not ok
        assert "深圳" in why and "checked" in why.lower()

    def test_already_checked_is_a_no_op(self):
        """已经是想要的状态就别点——再点一次是取消，会把设好的筛选弄丢。"""
        tools, calls = _tools([AFTER])
        ok, why = _run(set_filter_option("深圳", tools))
        assert ok
        assert calls == [], f"已经勾上了还去点：{calls}"

    def test_can_uncheck(self):
        tools, calls = _tools([AFTER, BEFORE])
        ok, _ = _run(set_filter_option("深圳", tools, checked=False))
        assert ok
        assert calls == [("click", "3_1")]

    def test_missing_option_says_so(self):
        tools, calls = _tools([BEFORE])
        ok, why = _run(set_filter_option("杭州", tools))
        assert not ok
        assert "杭州" in why
        assert calls == [], "找不到就不该乱点"

    def test_duplicate_names_fail_fast_instead_of_guessing(self):
        """「工作城市」和「面试地点」都可能有"深圳"。两个分组同时展开时无法确定
        是哪个——**猜错就是设错筛选，而且完全看不出来**。诚实失败，让 agent
        先收起另一个分组。"""
        dup = BEFORE + '  uid=4_0 checkbox "深圳"\n  uid=4_1 StaticText "深圳"\n'
        tools, calls = _tools([dup])
        ok, why = _run(set_filter_option("深圳", tools))
        assert not ok
        assert "深圳" in why
        assert calls == []

    def test_falls_back_to_the_checkbox_when_there_is_no_label_sibling(self):
        """不是所有站都用组件库——普通的 `<input type=checkbox>` 本身就可点，
        a11y 树里也不会有那个同名 StaticText 兄弟。这时点 checkbox 本身。"""
        plain = ('## Latest page snapshot\n'
                 '  uid=3_0 checkbox "深圳"\n'
                 '  uid=3_2 checkbox "北京"\n')
        plain_after = plain.replace('uid=3_0 checkbox "深圳"',
                                    'uid=3_0 checkbox "深圳" checked')
        tools, calls = _tools([plain, plain_after])
        ok, why = _run(set_filter_option("深圳", tools))
        assert ok, why
        assert calls == [("click", "3_0")]

    def test_a_click_error_is_reported_not_swallowed(self):
        """chrome-devtools-mcp 把执行错误当正常内容返回（isError=False），
        不是异常路径——不显式检查就会当成点成功了。"""
        tools, _ = _tools(
            [BEFORE, BEFORE],
            click_result="Error: Failed to interact with the element with uid 3_1. "
                         "The element did not become interactive within the configured timeout.")
        ok, why = _run(set_filter_option("深圳", tools))
        assert not ok
        assert "interactive" in why or "Error" in why
