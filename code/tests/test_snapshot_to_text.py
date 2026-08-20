"""快照转可读正文：`jd` 存的是给人看和给分类 LLM 看的文本，不是 a11y 转储。

**为什么必须转**（2026-08-21）：`job_url_online` 返回的详情页快照长这样——

```
## Latest page snapshot
uid=19_0 RootWebArea "岗位详情" url="https://example.test/d?id=1"
  uid=19_1 heading "某公司校园招聘" level="1"
  uid=19_20 link "关于我们" url="https://example.test/about"
    uid=19_21 StaticText "关于我们"
  uid=19_30 StaticText "岗位描述"
```

**两个消费方都吃不下它**：Checkpoint 1 审批页把它原样渲染出来就是一堆 `uid=`；
分类 prompt 里 3000 字的上限有大半花在 `uid=` / 角色名 / `url=` 这些标记上，
真正的岗位正文被挤掉。转换之后同样的 3000 字能装下的正文多一倍不止。
"""
import pytest

from multisite.executors import snapshot_to_text


class TestSnapshotToText:
    def test_keeps_the_visible_text_and_drops_the_markup(self):
        snap = ('## Latest page snapshot\n'
                'uid=19_0 RootWebArea "岗位详情" url="https://example.test/d?id=1"\n'
                '  uid=19_1 heading "甲公司校园招聘" level="1"\n'
                '  uid=19_30 StaticText "岗位描述"\n'
                '  uid=19_31 StaticText "负责后端服务开发"\n')
        got = snapshot_to_text(snap)
        assert "岗位描述" in got and "负责后端服务开发" in got
        assert "uid=" not in got
        assert "RootWebArea" not in got
        assert "https://example.test" not in got

    def test_collapses_the_duplicate_text_of_nested_nodes(self):
        """`link "关于我们"` 底下往往还挂一个内容一模一样的 `StaticText`。
        原样保留会让页脚的每一个链接都出现两遍，白占 `_JD_MAX_CHARS` 的额度。"""
        snap = ('## Latest page snapshot\n'
                '  uid=19_20 link "关于我们" url="https://example.test/about"\n'
                '    uid=19_21 StaticText "关于我们"\n'
                '  uid=19_30 StaticText "岗位描述"\n')
        assert snapshot_to_text(snap).count("关于我们") == 1

    def test_a_name_that_spans_several_physical_lines_is_kept_whole(self):
        """一整段岗位职责挤在一个节点的 name 里，**里面是真实换行**——开引号在
        `uid=` 那一行，闭引号在两三行之后。

        **这条测试是拿真机数据校正过的**：第一版按"换行被转义成字面 `\\n`"写，
        逐行匹配，真机 3076 字的详情页只提取出 303 字（导航栏加两个小标题），
        而单测全绿——因为我编的 fixture 把整段正文写在了一行里。
        **fixture 的形状错了，测试就只是在验证我的误解。**
        """
        snap = ('## Latest page snapshot\n'
                '  uid=19_31 StaticText "1、负责后端开发；\n'
                '2、参与架构设计；\n'
                '3、跟踪前沿技术。"\n'
                '  uid=19_32 StaticText "岗位要求"\n')
        got = snapshot_to_text(snap)
        assert "1、负责后端开发；" in got
        assert "2、参与架构设计；" in got
        assert "3、跟踪前沿技术。" in got
        assert "岗位要求" in got
        assert "uid=" not in got

    def test_a_node_without_a_name_contributes_nothing(self):
        snap = ('## Latest page snapshot\n'
                '  uid=19_4 generic\n'
                '  uid=19_5 StaticText ""\n'
                '  uid=19_6 StaticText "岗位要求"\n')
        assert snapshot_to_text(snap).strip() == "岗位要求"

    def test_plain_text_that_is_not_a_snapshot_survives_unchanged(self):
        """`link_in_row` 那条路径的 `jd` 是 `row.text`（本来就是干净文本），
        不能被这个函数吃掉——两条路径最终都会经过它，行为必须是"没有可提取的
        节点就原样返回"，而不是返回空串。"""
        text = "AI全栈工程师 深圳 应届毕业生 负责全栈开发"
        assert snapshot_to_text(text) == text
