"""Tests for the pure-logic (no browser/LLM) helpers in multisite.layer1_agent.

The fixture below is a trimmed, real chrome-devtools-mcp a11y snapshot captured
against Bambu Lab's campus application form during live verification (values were
all empty at capture time -- no PII in this text; the masked phone number "1812****869"
is the site's own display, not something this project unmasked).
"""
from multisite.layer1_agent import (
    FieldClassification,
    _enforce_government_id_blank,
    _extract_text,
    _looks_blank,
    _looks_logged_out,
    _parse_empty_input_elements,
)

REAL_FORM_SNAPSHOT = """## Latest page snapshot
uid=1_0 RootWebArea "投递简历 - 欢迎加入拓竹科技" url="https://bambulab.jobs.feishu.cn/campus/resume/x/apply"
  uid=1_11 StaticText "1812****869"
  uid=1_12 main
    uid=2_0 form
      uid=2_9 StaticText "申请信息"
      uid=2_10 StaticText "推荐方式"
      uid=2_11 StaticText "*"
      uid=2_12 radio "无" checked
      uid=2_13 StaticText "无"
      uid=2_14 radio "内推"
      uid=2_15 StaticText "内推"
      uid=2_16 radio "大使推荐"
      uid=2_17 StaticText "大使推荐"
      uid=2_18 StaticText "意向城市"
      uid=2_19 StaticText "深圳"
      uid=2_20 StaticText "附件简历"
      uid=2_21 button "将你的简历拖拽至此处 选择文件 支持格式：PDF、DOC、DOCX"
        uid=2_22 button "选择文件"
      uid=2_23 StaticText "基本信息"
      uid=2_24 StaticText "姓名"
      uid=2_11 StaticText "*"
      uid=2_25 textbox "姓名 *"
      uid=2_30 StaticText "邮箱"
      uid=2_11 StaticText "*"
      uid=2_31 textbox "邮箱 *"
      uid=2_32 StaticText "您从哪些渠道了解到该岗位招聘信息？"
      uid=2_33 combobox expandable haspopup="menu"
        uid=2_34 textbox
      uid=2_36 StaticText "学校名称"
      uid=2_11 StaticText "*"
      uid=2_37 combobox expandable haspopup="menu"
        uid=2_38 textbox
      uid=2_39 StaticText "学历"
      uid=2_11 StaticText "*"
      uid=2_40 combobox expandable haspopup="menu"
      uid=2_41 StaticText "专业"
      uid=2_11 StaticText "*"
      uid=2_42 textbox "专业 *"
      uid=2_43 StaticText "起止时间"
      uid=2_11 StaticText "*"
      uid=2_44 StaticText "无准确的毕业时间可填写预计毕业时间"
      uid=2_45 StaticText "YYYY"
      uid=2_47 StaticText "MM"
      uid=2_51 textbox
    uid=2_59 button "提交简历"
"""


class TestExtractText:
    def test_plain_string_passthrough(self):
        assert _extract_text("hello") == "hello"

    def test_content_block_list(self):
        assert _extract_text([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]) == "a\nb"

    def test_ignores_non_text_blocks(self):
        assert _extract_text([{"type": "image", "data": "..."}, {"type": "text", "text": "x"}]) == "x"


class TestLooksBlank:
    def test_about_blank_url(self):
        assert _looks_blank('## Latest page snapshot\nuid=1_0 RootWebArea url="about:blank"') is True

    def test_real_content_is_not_blank(self):
        assert _looks_blank(REAL_FORM_SNAPSHOT) is False


class TestLooksLoggedOut:
    def test_detects_login_keyword(self):
        assert _looks_logged_out("请登录后继续") is True

    def test_detects_english_login(self):
        assert _looks_logged_out("Please sign in") is True

    def test_real_form_is_logged_in(self):
        # masked phone number in the nav bar -- a logged-in signal, no "登录" text
        assert _looks_logged_out(REAL_FORM_SNAPSHOT) is False


# 注：`TestFindUidByLabel` / `TestFindUidNearText` 随被测函数一起于 v2.22.0 删除
# ——找投递入口/上传控件改由 agent 自主决定，这两个函数没有消费方了。留着测试
# 断言一个已经不存在的行为，比没有测试更糟。


class TestParseEmptyInputElements:
    def test_captures_named_textboxes(self):
        elems = _parse_empty_input_elements(REAL_FORM_SNAPSHOT)
        labels = {e["label"] for e in elems}
        assert "姓名 *" in labels
        assert "邮箱 *" in labels
        assert "专业 *" in labels

    def test_unlabeled_comboboxes_fall_back_to_landmark(self):
        """真机验证的核心 bug：学校名称/学历/来源渠道三个必填 combobox 没有
        accessible name，直接跳过会让 Layer 2 完全看不到这些必填字段。"""
        elems = _parse_empty_input_elements(REAL_FORM_SNAPSHOT)
        labels = {e["label"] for e in elems}
        assert "学校名称" in labels
        assert "学历" in labels
        assert "您从哪些渠道了解到该岗位招聘信息？" in labels

    def test_deduplicates_combobox_and_its_nested_textbox(self):
        """combobox 外层和内层 textbox 都没 name，都会落到同一个地标——不能
        算成两个字段。"""
        elems = _parse_empty_input_elements(REAL_FORM_SNAPSHOT)
        labels = [e["label"] for e in elems]
        assert labels.count("学校名称") == 1

    def test_date_placeholder_hints_are_not_used_as_landmark(self):
        """YYYY/MM 这类日期格式占位符不能抢真地标的位置。"""
        elems = _parse_empty_input_elements(REAL_FORM_SNAPSHOT)
        labels = {e["label"] for e in elems}
        assert "MM" not in labels
        assert "YYYY" not in labels

    def test_already_selected_radio_group_is_excluded(self):
        """真机验证的另一个核心 bug：单选题被拆成 N 个假字段。"推荐方式"已经
        默认选中"无"（checked），整题不该出现在待处理字段里。"""
        elems = _parse_empty_input_elements(REAL_FORM_SNAPSHOT)
        labels = {e["label"] for e in elems}
        assert "无" not in labels
        assert "内推" not in labels
        assert "大使推荐" not in labels
        assert "推荐方式" not in labels

    def test_unchecked_radio_group_surfaces_as_one_field(self):
        snapshot = """## Latest page snapshot
uid=1_0 RootWebArea
  uid=2_1 StaticText "推荐方式"
  uid=2_2 radio "无"
  uid=2_3 radio "内推"
"""
        elems = _parse_empty_input_elements(snapshot)
        radio_elems = [e for e in elems if e["role"] == "radio"]
        assert len(radio_elems) == 1
        assert radio_elems[0]["label"] == "推荐方式"

    def test_filled_textbox_is_excluded(self):
        snapshot = '## Latest page snapshot\nuid=1_0 RootWebArea\n  uid=2_1 textbox "姓名" value="张三"\n'
        assert _parse_empty_input_elements(snapshot) == []


class TestEnforceGovernmentIdBlank:
    def test_clears_candidate_value_for_government_id(self):
        fields = [
            FieldClassification(field_id="身份证号", kind="government_id", candidate_value="110101199001011234"),
            FieldClassification(field_id="姓名", kind="demographic", demographic_key="name"),
        ]
        result = _enforce_government_id_blank(fields)
        assert result[0].candidate_value == ""
        assert result[0].kind == "government_id"

    def test_other_kinds_untouched(self):
        fields = [FieldClassification(field_id="自我评价", kind="open_question", candidate_value="熟悉后端开发")]
        result = _enforce_government_id_blank(fields)
        assert result[0].candidate_value == "熟悉后端开发"


# a11y 树里日期控件的真实形状（2026-08-15 真机快照，人名/校名换成虚构）：年月被拆成
# 一堆平铺的 StaticText，**离输入框比真正的字段名更近**。
DATE_WIDGET_SNAPSHOT = """
uid=1_0 RootWebArea "投递简历" url="https://example.com/apply"
  uid=3_42 textbox "专业 *" value="某专业"
  uid=3_43 StaticText "起止时间"
  uid=3_11 StaticText "*"
  uid=3_44 StaticText "无准确的毕业时间可填写预计毕业时间"
  uid=3_45 StaticText "2019"
  uid=3_46 StaticText "-"
  uid=3_47 StaticText "09"
  uid=3_48 StaticText "2023"
  uid=3_49 StaticText "-"
  uid=3_50 StaticText "09"
  uid=3_51 textbox
"""


class TestLandmarkHeuristic:
    """日期控件的碎片不能当字段名。

    真机踩过两次，都是同一个控件：第一次是 `MM`/`YYYY` 格式提示抢走地标；
    第二次是年月被拆成 `"2019"` `"-"` `"09"` 平铺，字段名成了 `09`。

    **第二次的后果严重得多**：`09` 被当成开放问题交给 LLM，而它拿到岗位
    上下文之后**认真编了一段期望薪资**——一个凭空生成的数字会跟着审批流走到
    Layer 3，真填进企业表单。
    """

    def _labels(self, snapshot):
        from multisite.layer1_agent import _parse_empty_input_elements
        return [e["label"] for e in _parse_empty_input_elements(snapshot)]

    def test_date_fragments_never_become_the_label(self):
        labels = self._labels(DATE_WIDGET_SNAPSHOT)
        assert "09" not in labels and "2019" not in labels and "-" not in labels

    def test_landmark_falls_back_to_the_real_field_name(self):
        """拒掉器碎片后，地标应该回退到它们前面那个真字段名。"""
        assert self._labels(DATE_WIDGET_SNAPSHOT) == ["起止时间"]

    def test_help_text_is_not_a_field_name(self):
        # "无准确的毕业时间可填写预计毕业时间" 是页面说明，不是字段名。
        assert "无准确的毕业时间可填写预计毕业时间" not in self._labels(DATE_WIDGET_SNAPSHOT)

    def test_a_long_question_is_still_a_valid_label(self):
        """**长度分不开真假**：同一张表单上两个 17 字的串，一个是真字段名（问句）
        一个是说明文字。卡长度会把问句一起误杀（试过 12 字，它变成了前面的"邮箱"）。"""
        snap = """
uid=1_0 RootWebArea "x" url="https://example.com"
  uid=2_1 StaticText "邮箱"
  uid=2_2 StaticText "您从哪些渠道了解到该岗位招聘信息？"
  uid=2_3 combobox
"""
        assert self._labels(snap) == ["您从哪些渠道了解到该岗位招聘信息？"]

    def test_element_is_dropped_when_no_usable_label_exists(self):
        """宁可漏一个字段，也不要交出一个名字是垃圾的字段——漏了人看截图能
        发现，交出去会变成 LLM 给不存在的问题编答案。"""
        snap = """
uid=1_0 RootWebArea "x" url="https://example.com"
  uid=2_1 StaticText "2024"
  uid=2_2 textbox
"""
        assert self._labels(snap) == []

    def test_named_fields_are_unaffected(self):
        # 自带 accessible name 的字段根本不走地标逻辑。
        snap = """
uid=1_0 RootWebArea "x" url="https://example.com"
  uid=2_1 StaticText "09"
  uid=2_2 textbox "手机号码 *"
"""
        assert self._labels(snap) == ["手机号码 *"]

    def test_a_field_whose_own_name_is_garbage_is_dropped(self):
        """地标那两道闸管不到这条路径：元素**自带**的 accessible name 就是垃圾。

        表单写得糟的时候真会这样（把月份数字当成了输入框的 aria-label）。
        走到这里必须丢掉——宁可漏一个字段，也不要交出一个名字是 `09` 的字段让
        LLM 去"回答"它。
        """
        snap = """
uid=1_0 RootWebArea "投递简历" url="https://example.com"
  uid=2_1 StaticText "起止时间"
  uid=2_2 textbox "09"
"""
        assert self._labels(snap) == []


class TestRequiredDetection:
    """只把**必填**字段交给 LLM 作答。

    这类站点会解析上传的简历自动回填，剩下还空着的多半是选填。给全部字段生成内容
    的产出是：「起止时间 → "请填写您在教育或工作经历中的起止时间，格式如：
    2020.09 - 2024.06"」——一句填写说明冒充答案（2026-08-15 真机）。

    必填标记的真实形态（来自真机快照）：`StaticText "*"` 夹在字段名和字段之间。
    """

    def _scan(self, snapshot):
        from multisite.layer1_agent import _parse_empty_input_elements
        return {e["label"]: e["required"] for e in _parse_empty_input_elements(snapshot)}

    def test_star_between_label_and_field_marks_required(self):
        snap = """
uid=1_0 RootWebArea "投递简历" url="https://example.com"
  uid=2_1 StaticText "学校名称"
  uid=2_2 StaticText "*"
  uid=2_3 combobox
"""
        assert self._scan(snap) == {"学校名称": True}

    def test_no_star_means_optional(self):
        snap = """
uid=1_0 RootWebArea "投递简历" url="https://example.com"
  uid=2_1 StaticText "您从哪些渠道了解到该岗位招聘信息？"
  uid=2_2 combobox
"""
        assert self._scan(snap) == {"您从哪些渠道了解到该岗位招聘信息？": False}

    def test_star_survives_rejected_landmarks(self):
        """**这条是关键**：「起止时间」的星号落在日期碎片和说明文字**前面**。
        被拒的地标不该重置必填标记，否则这个字段会被误判成选填。"""
        snap = """
uid=1_0 RootWebArea "投递简历" url="https://example.com"
  uid=2_1 StaticText "起止时间"
  uid=2_2 StaticText "*"
  uid=2_3 StaticText "无准确的毕业时间可填写预计毕业时间"
  uid=2_4 StaticText "2019"
  uid=2_5 StaticText "-"
  uid=2_6 StaticText "09"
  uid=2_7 textbox
"""
        assert self._scan(snap) == {"起止时间": True}

    def test_star_is_reset_by_the_next_real_label(self):
        """必填标记不能跨字段泄漏——上一个字段必填不代表下一个也必填。"""
        snap = """
uid=1_0 RootWebArea "投递简历" url="https://example.com"
  uid=2_1 StaticText "学校名称"
  uid=2_2 StaticText "*"
  uid=2_3 combobox
  uid=2_4 StaticText "个人网站"
  uid=2_5 textbox
"""
        assert self._scan(snap) == {"学校名称": True, "个人网站": False}

    def test_star_inside_the_accessible_name(self):
        # 有的站把星号写进字段自己的 name 里（"专业 *"）。
        snap = """
uid=1_0 RootWebArea "投递简历" url="https://example.com"
  uid=2_1 textbox "手机号码 *"
"""
        assert self._scan(snap) == {"手机号码 *": True}
