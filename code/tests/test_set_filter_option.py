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
from pydantic import BaseModel, Field

from multisite.executors import set_filter_option


def _run(c):
    return asyncio.run(c)


class _EvalArgs(BaseModel):
    """跟 chrome-devtools-mcp 的 `evaluate_script` 声明一致：`function` + `args`。"""

    function: str
    args: list = Field(default_factory=list)


BEFORE = ('## Latest page snapshot\n'
          'uid=2_0 tab "工作城市" expandable expanded\n'
          '  uid=3_0 checkbox "深圳"\n'
          '  uid=3_1 StaticText "深圳"\n'
          '  uid=3_2 checkbox "北京"\n'
          '  uid=3_3 StaticText "北京"\n')
AFTER = BEFORE.replace('uid=3_0 checkbox "深圳"', 'uid=3_0 checkbox "深圳" checked')


def _tools(snapshots, click_result="Script ran on page and returned:\n```json\n\"label\"\n```"):
    """`take_snapshot` 依次返回 snapshots，用完停在最后一张。"""
    calls = []
    state = {"n": 0}

    async def take_snapshot():
        i = min(state["n"], len(snapshots) - 1)
        state["n"] += 1
        return snapshots[i]

    async def evaluate_script(**kw):
        calls.append(("js", (kw.get("args") or [None])[0]))
        return click_result

    async def click(uid: str):
        calls.append(("click", uid))
        return "Successfully clicked on the element"

    tools = [StructuredTool.from_function(coroutine=f, name=n, description=n)
             for f, n in ((take_snapshot, "take_snapshot"), (click, "click"))]
    # **显式给 schema**：真实 `evaluate_script` 的参数名是 `function` / `args`
    # （核对过 chrome-devtools-mcp 的声明）。让 StructuredTool 从函数签名推断的话，
    # pydantic 会把名为 `args` 的字段改写成 `v__args`，假替身就跟真工具对不上了
    # ——那正是 `pageIdx` 那次踩过的坑：假工具和生产代码互相印证，只有真实世界不同意。
    tools.append(StructuredTool(
        name="evaluate_script", description="evaluate_script",
        args_schema=_EvalArgs, coroutine=evaluate_script))
    return tools, calls


class TestSetFilterOption:
    def test_clicks_the_enclosing_label_via_script(self):
        """`click` 那个 checkbox 节点永远超时（0×0 隐藏 input）。改用
        `evaluate_script` 点它的 `<label>` 祖先——**一条路径同时覆盖两种形态**
        （叶子选项和分组标题，见 `TestGroupHeaderCheckbox`）。"""
        tools, calls = _tools([BEFORE, AFTER])
        ok, why = _run(set_filter_option("深圳", tools))
        assert ok, why
        assert calls == [("js", "3_0")], f"点错了目标或用错了工具：{calls}"
        assert not any(c[0] == "click" for c in calls), "不能用 click 点隐藏的 checkbox"

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
        assert calls == [("js", "3_0")]

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

    def test_a_plain_checkbox_with_no_label_still_works(self):
        """不是所有站都用组件库。普通的 `<input type=checkbox>` 没有 `<label>`
        祖先，脚本里 `closest('label')` 返回 null 就点元素自己——**同一段脚本，
        不是第二条代码路径**。"""
        plain = ('## Latest page snapshot\n'
                 '  uid=3_0 checkbox "深圳"\n'
                 '  uid=3_2 checkbox "北京"\n')
        plain_after = plain.replace('uid=3_0 checkbox "深圳"',
                                    'uid=3_0 checkbox "深圳" checked')
        tools, calls = _tools([plain, plain_after])
        ok, why = _run(set_filter_option("深圳", tools))
        assert ok, why
        assert calls == [("js", "3_0")]

    def test_a_click_error_is_reported_not_swallowed(self):
        """chrome-devtools-mcp 把执行错误当正常内容返回（isError=False），
        不是异常路径——不显式检查就会当成点成功了。"""
        tools, _ = _tools(
            [BEFORE, BEFORE],
            click_result="Error: Cannot read properties of null (reading 'click')")
        ok, why = _run(set_filter_option("深圳", tools))
        assert not ok
        assert "Error" in why


class TestGroupHeaderCheckbox:
    """**分组标题上也有 checkbox，而它没有同名 `StaticText` 兄弟。**

    真机（join.qq.com「岗位类别」展开后）：

    ```
    uid=2_3 tab "技术" description="软件开发类 技术运营类 …"
      uid=2_4 button "技术"        ← 点它是**展开分组**，不是勾选
        uid=2_5 checkbox "技术"    ← 0×0 隐藏 input
    ```

    祖先链跟叶子选项同构（`LABEL.el-checkbox` 52×48 可点），但 a11y 树里
    **没有可点的同名节点**。第一版按"找紧跟其后的同名 StaticText，找不到就点
    checkbox 本身"写，对这种形态**必然超时**——真机 `filter_failures` 里
    「技术」就是这么失败的，整轮 `found: 0`。

    改用 `evaluate_script` 点 `closest('label')` 之后，一条路径同时覆盖两种形态：
    实测分组标题「技术」943→152、叶子「深圳」152→99，两个都 `checked=True`。
    """

    SNAP = ('## Latest page snapshot\n'
            '  uid=2_3 tab "技术" description="软件开发类 技术运营类"\n'
            '    uid=2_4 button "技术"\n'
            '      uid=2_5 checkbox "技术"\n')
    SNAP_ON = SNAP.replace('uid=2_5 checkbox "技术"', 'uid=2_5 checkbox "技术" checked')

    def test_it_sets_a_group_header_checkbox(self):
        tools, calls = _tools([self.SNAP, self.SNAP_ON])
        ok, why = _run(set_filter_option("技术", tools))
        assert ok, why
        assert calls == [("js", "2_5")]

    def test_the_script_targets_the_label_ancestor(self):
        """**脚本体的行为是真机验的，不是单测验的**——脚本在浏览器里执行，
        单测观测不到它选中了哪个元素（把 `closest('label')` 换成 `null` 时
        本文件一条都不会红）。真机证据：分组标题「技术」943→152、
        叶子「深圳」152→99，两个都 `checked=True`。

        这条只做一件事：**防止那段脚本被无声改掉**。字符串断言很弱，
        但它把一个"结构上观测不到"的变异变成了观测得到的。
        """
        from multisite.executors import _CLICK_LABEL_JS
        assert "closest('label')" in _CLICK_LABEL_JS

    def test_it_never_clicks_the_group_button(self):
        """点 `button "技术"` 是**展开分组**，不是勾选——点错了会让"设上了没"
        的判断彻底错位（展开成功、筛选没设，而两者都不报错）。"""
        tools, calls = _tools([self.SNAP, self.SNAP_ON])
        _run(set_filter_option("技术", tools))
        assert ("js", "2_4") not in calls and ("click", "2_4") not in calls
