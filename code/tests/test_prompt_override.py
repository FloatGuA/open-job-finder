"""用户可编辑 prompt 模板：覆盖层加载 / 占位符校验 / 恢复默认。"""
import pytest

from services.prompt_manager import PromptManager


def _pm(tmp_path):
    # 用真实默认模板 prompts/ + 临时覆盖目录，隔离测试。
    return PromptManager(override_dir=tmp_path)


def test_override_takes_priority(tmp_path):
    pm = _pm(tmp_path)
    default = pm.get_default("system")
    assert not pm.is_modified("system")
    assert pm.load("system") == default

    pm.save_override("system", "我的自定义系统角色")
    assert pm.is_modified("system")
    assert pm.load("system") == "我的自定义系统角色"     # 覆盖优先
    assert pm.get_default("system") == default            # 默认不受影响


def test_reset_restores_default(tmp_path):
    pm = _pm(tmp_path)
    pm.save_override("system", "临时改的")
    assert pm.is_modified("system")
    pm.reset_override("system")
    assert not pm.is_modified("system")
    assert pm.load("system") == pm.get_default("system")
    pm.reset_override("system")  # 幂等，不报错


def test_placeholder_set_must_match_default(tmp_path):
    pm = _pm(tmp_path)
    default = pm.get_default("score_job")   # 含 {{title}}/{{jd_text}}/... 占位符
    # 删掉一个占位符 → 拒绝
    broken = default.replace("{{jd_text}}", "（略）")
    with pytest.raises(ValueError):
        pm.save_override("score_job", broken)
    # 加一个未知占位符 → 拒绝
    with pytest.raises(ValueError):
        pm.save_override("score_job", default + "\n{{unknown_field}}")
    assert not pm.is_modified("score_job")  # 两次失败都没写入


def test_valid_edit_keeping_placeholders_ok(tmp_path):
    pm = _pm(tmp_path)
    default = pm.get_default("score_job")
    edited = "【自定义前言】\n" + default   # 占位符集不变
    pm.save_override("score_job", edited)
    assert pm.load("score_job") == edited


def test_system_has_no_placeholders_rejects_any(tmp_path):
    pm = _pm(tmp_path)
    # system 无占位符：纯文本 OK，带占位符则被拒（引入未知占位符）
    pm.save_override("system", "任意文本没有占位符")
    with pytest.raises(ValueError):
        pm.save_override("system", "text {{oops}}")


def test_non_editable_name_rejected(tmp_path):
    pm = _pm(tmp_path)
    with pytest.raises(ValueError):
        pm.save_override("../evil", "x")
    with pytest.raises(ValueError):
        pm.reset_override("nope")
