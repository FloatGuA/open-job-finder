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
    _find_uid_by_label,
    _find_uid_near_text,
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


class TestFindUidByLabel:
    def test_finds_submit_button(self):
        assert _find_uid_by_label(REAL_FORM_SNAPSHOT, ["提交", "submit"]) == "2_59"

    def test_returns_none_when_not_found(self):
        assert _find_uid_by_label(REAL_FORM_SNAPSHOT, ["不存在的关键词"]) is None


class TestFindUidNearText:
    def test_finds_button_after_resume_landmark(self):
        # 落地地标本身（"将你的简历拖拽至此处..."）就带"简历"/"拖拽"字样，命中
        # 地标后继续找下一个 button——找到的是嵌套在里面的"选择文件"按钮，
        # 这正是实际要点击上传的那个元素。
        uid = _find_uid_near_text(REAL_FORM_SNAPSHOT, ["简历", "拖拽"], roles={"button"})
        assert uid == "2_22"


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
