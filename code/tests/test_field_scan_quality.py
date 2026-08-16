"""字段扫描的质量问题（2026-08-17 真机 Checkpoint 2 记录暴露）。

那次跑出来的五个待审批字段，没有一个是对的：

    '学校名称'          | open_question | '请填写您的学校名称（例如：XX大学…）'   ← 页面上早就填好了
    '起止时间'          | open_question | '请填写您的在校起止时间（例如：…）'      ← 同上
    '最多可选 2 个城市'  | open_question | ''                                    ← 这是说明文字，不是字段名
    '接受调剂到其他城市' | open_question | ''
    '您从哪些渠道…？'    | open_question | ''

真正需要人填的只有「意向城市」一个，而它恰恰是被说明文字顶掉名字的那个。

下面的快照片段照抄真机的**结构**，值全部换成虚构占位（甲大学/张三）。
"""
import pytest

from multisite.layer1_agent import (
    FieldClassification,
    _enforce_no_invented_values,
    _parse_empty_input_elements,
    record_application,
)


def _labels(snapshot):
    return [e["label"] for e in _parse_empty_input_elements(snapshot)]


def _by_label(snapshot, label):
    return next(e for e in _parse_empty_input_elements(snapshot) if e["label"] == label)


# 「最多可选 2 个城市」是「意向城市」下面的一行说明文字，位置比字段名更靠近输入框。
HELP_TEXT_SNAPSHOT = """## Latest page snapshot
uid=1_0 RootWebArea "投递简历 - 甲公司" url="https://example.com/apply"
  uid=2_0 form
    uid=2_1 StaticText "意向城市"
    uid=2_2 StaticText "*"
    uid=2_3 StaticText "最多可选 2 个城市"
    uid=2_4 combobox expandable haspopup="menu"
      uid=2_5 textbox
    uid=2_6 checkbox "接受调剂到其他城市"
"""

# 纯展示的字段（手机号已验证，页面只把它印出来、没有输入框），后面紧跟着一个真字段。
DISPLAY_ONLY_THEN_REAL = """## Latest page snapshot
uid=1_0 RootWebArea "投递简历 - 甲公司" url="https://example.com/apply"
  uid=2_0 form
    uid=2_1 StaticText "手机号码"
    uid=2_2 StaticText "*"
    uid=2_3 StaticText "+86"
    uid=2_4 StaticText "138-0000-0000"
    uid=2_5 StaticText "邮箱"
    uid=2_6 StaticText "*"
    uid=2_7 combobox expandable haspopup="menu"
"""


class TestHelpTextIsNotAFieldName:
    def test_the_label_wins_over_the_help_text_below_it(self):
        """星号之后、输入框之前的文字是**说明**，不是字段名。

        判据是位置不是长度：这行只有 9 个字，卡长度的那道闸（>12 字且不是问句）
        根本拦不住它。
        """
        assert "意向城市" in _labels(HELP_TEXT_SNAPSHOT)
        assert "最多可选 2 个城市" not in _labels(HELP_TEXT_SNAPSHOT)

    def test_the_star_still_marks_the_field_as_required(self):
        """说明文字抢走地标位时顺手把必填标记也吞了——「意向城市」是这张表上
        唯一真正要人填的必填项，却被记成选填，于是连值都不会生成。"""
        assert _by_label(HELP_TEXT_SNAPSHOT, "意向城市")["required"] is True

    def test_the_star_is_not_inherited_by_the_next_optional_field(self):
        """输入框吃掉前面那个星号：下一个没有星号的字段不该跟着变必填。"""
        assert _by_label(HELP_TEXT_SNAPSHOT, "接受调剂到其他城市")["required"] is False


# 下拉框的值挂在**内层** textbox 上，外层 combobox 自己没有 value。
NESTED_VALUE_SNAPSHOT = """## Latest page snapshot
uid=1_0 RootWebArea "投递简历 - 甲公司" url="https://example.com/apply"
  uid=2_0 form
    uid=2_1 StaticText "学校名称"
    uid=2_2 StaticText "*"
    uid=2_3 combobox expandable haspopup="menu"
      uid=2_4 textbox value="甲大学"
    uid=2_5 StaticText "专业"
    uid=2_6 StaticText "*"
    uid=2_7 combobox expandable haspopup="menu"
      uid=2_8 textbox
"""

# 日期控件：**已经选好**的年月是平铺在输入框前面的 StaticText，输入框自己永远是空的。
FILLED_DATE_SNAPSHOT = """## Latest page snapshot
uid=1_0 RootWebArea "投递简历 - 甲公司" url="https://example.com/apply"
  uid=2_0 form
    uid=2_1 StaticText "起止时间"
    uid=2_2 StaticText "*"
    uid=2_3 StaticText "无准确的毕业时间可填写预计毕业时间"
    uid=2_4 StaticText "2019"
    uid=2_5 StaticText "-"
    uid=2_6 StaticText "09"
    uid=2_7 StaticText "2023"
    uid=2_8 StaticText "-"
    uid=2_9 StaticText "09"
    uid=2_10 textbox
"""

# 同一个控件**没填**的时候，碎片是 YYYY / MM 这样的格式占位符。
EMPTY_DATE_SNAPSHOT = FILLED_DATE_SNAPSHOT.replace('"2019"', '"YYYY"').replace(
    '"2023"', '"YYYY"').replace('"09"', '"MM"')


class TestAlreadyFilledFieldsAreNotReportedEmpty:
    """「这个节点没有 value」≠「这个字段没填」。

    真机那张表单其实**整张都被简历解析填好了**，唯一真需要人填的是「意向城市」。
    我们却报了 5 个空字段，其中两个已经有值——而 LLM 对着它们编了两句填写说明
    冒充答案。如果这些值被真的填回表单，覆盖掉的是正确内容。
    """

    def test_combobox_is_filled_when_its_nested_textbox_has_a_value(self):
        assert "学校名称" not in _labels(NESTED_VALUE_SNAPSHOT)

    def test_an_actually_empty_combobox_still_surfaces(self):
        """别把闸门修成"所有下拉框都当已填"——那样必填项会集体隐形。"""
        assert "专业" in _labels(NESTED_VALUE_SNAPSHOT)

    def test_a_date_widget_that_already_has_a_value_is_not_reported_empty(self):
        """选好的年月是 StaticText，输入框自己永远是空的——只看输入框必然误判。"""
        assert _labels(FILLED_DATE_SNAPSHOT) == []

    def test_an_unfilled_date_widget_still_surfaces(self):
        """空的时候碎片是 YYYY/MM 格式占位符，不是数字——这就是两种状态的区别。"""
        assert _by_label(EMPTY_DATE_SNAPSHOT, "起止时间")["required"] is True


class FakeTracker:
    def __init__(self):
        self.saved = None

    def add_pending_application(self, **kw):
        self.saved = kw
        return 1


class TestNoBucketMeansEverythingBecomesAnInventedAnswer:
    """kind 只有三档时，"事实性字段但我没有这份资料"没有地方可去。

    真机那次五个字段**全部**是 open_question——不是因为它们真是开放问题，而是
    personal_info 只有 5 个 key，凡不在其中的一律落进 open_question，而
    open_question 的指令是"生成一段候选文本"。于是「学校名称」拿到的答案是
    「请填写您的学校名称（例如：…）」：一句填写说明冒充答案。

    补上第四档 `unknown_fact`（事实性字段，资料里没有 → 留空请人填），
    并用代码兜住"只有 open_question 允许带生成的值"。
    """

    def test_unknown_fact_is_a_valid_kind(self):
        f = FieldClassification(field_id="意向城市", kind="unknown_fact")
        assert f.kind == "unknown_fact"

    def test_an_invented_value_on_unknown_fact_is_stripped(self):
        """兜底在代码里，不指望 prompt 每次都听话。"""
        fields = [FieldClassification(field_id="意向城市", kind="unknown_fact",
                                      candidate_value="深圳、上海")]
        assert _enforce_no_invented_values(fields)[0].candidate_value == ""

    def test_government_id_is_still_stripped(self):
        fields = [FieldClassification(field_id="身份证号", kind="government_id",
                                      candidate_value="110101199001011234")]
        assert _enforce_no_invented_values(fields)[0].candidate_value == ""

    def test_open_question_keeps_its_draft(self):
        """真正的开放问题（自我评价这类）仍然可以起草——被砍掉的是"对事实编造"。"""
        fields = [FieldClassification(field_id="为什么应聘", kind="open_question",
                                      candidate_value="我对该岗位很感兴趣")]
        assert _enforce_no_invented_values(fields)[0].candidate_value == "我对该岗位很感兴趣"

    def test_record_application_writes_an_empty_value_for_unknown_fact(self):
        tracker = FakeTracker()
        state = {
            "empty_elements": [{"uid": "1", "role": "combobox",
                                "label": "意向城市", "required": True}],
            "classified_fields": [FieldClassification(
                field_id="意向城市", kind="unknown_fact", candidate_value="深圳")],
            "job_url": "https://example.com/apply",
        }
        record_application(tracker, state, {"name": "张三"})

        field = tracker.saved["fields"][0]
        assert field["kind"] == "unknown_fact"
        assert field["candidate_value"] == ""


class TestDisplayOnlyFieldDoesNotSwallowTheNextLabel:
    """回归守门：上一条的修法（星号之后不再接受新地标）不能把这种版式压死。

    手机号那一段没有任何输入框，所以"等输入框来释放"永远等不到；「邮箱」必须
    仍然当得上地标——它后面紧跟着星号，那是字段名最硬的信号。
    """

    def test_the_real_label_after_a_display_only_field(self):
        assert _labels(DISPLAY_ONLY_THEN_REAL) == ["邮箱"]
