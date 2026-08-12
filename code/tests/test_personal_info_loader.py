"""Tests for multisite.personal_info_loader — pure function, no I/O beyond tmp_path."""
import yaml
import pytest

from multisite.personal_info_loader import load_personal_info, save_new_facts


def _write(tmp_path, fname, content):
    (tmp_path / fname).write_text(content, encoding="utf-8")


class TestLoadPersonalInfo:
    def test_flattens_both_files(self, tmp_path):
        _write(tmp_path, "basic.yaml", "name: 张三\nemail: zhangsan@example.com\nphone: '13800000000'\n")
        _write(tmp_path, "identity.yaml", "gender: 男\nbirth_date: '2000-01-01'\n")

        result = load_personal_info(tmp_path)

        assert result == {
            "name": "张三",
            "email": "zhangsan@example.com",
            "phone": "13800000000",
            "gender": "男",
            "birth_date": "2000-01-01",
        }

    def test_missing_directory_returns_empty(self, tmp_path):
        assert load_personal_info(tmp_path / "does_not_exist") == {}

    def test_missing_one_file_still_loads_the_other(self, tmp_path):
        _write(tmp_path, "basic.yaml", "name: 张三\n")

        assert load_personal_info(tmp_path) == {"name": "张三"}

    def test_empty_values_are_dropped(self, tmp_path):
        _write(tmp_path, "basic.yaml", "name: 张三\nemail: ''\nphone:\n")

        assert load_personal_info(tmp_path) == {"name": "张三"}

    def test_government_id_key_raises(self, tmp_path):
        _write(tmp_path, "identity.yaml", "id_number: '110101199001011234'\n")

        with pytest.raises(ValueError, match="政府证件号码"):
            load_personal_info(tmp_path)

    def test_real_project_files_load_without_forbidden_keys(self):
        """Sanity check against the actual (gitignored) data/personal_info/ files,
        if present in this environment -- confirms the hard constraint holds in
        production data, not just synthetic fixtures."""
        from multisite.personal_info_loader import DATA_DIR

        if not DATA_DIR.exists():
            pytest.skip("data/personal_info/ not present in this environment")
        load_personal_info()  # must not raise


class TestSaveNewFacts:
    def test_saves_new_demographic_field(self, tmp_path):
        saved = save_new_facts(
            [{"field_id": "学校名称", "kind": "demographic", "candidate_value": "深圳大学"}],
            tmp_path,
        )
        assert saved == ["学校名称"]
        assert load_personal_info(tmp_path) == {"学校名称": "深圳大学"}

    def test_does_not_overwrite_existing_key(self, tmp_path):
        _write(tmp_path, "basic.yaml", "name: 张三\n")
        saved = save_new_facts(
            [{"field_id": "name", "kind": "demographic", "candidate_value": "李四"}],
            tmp_path,
        )
        assert saved == []
        assert load_personal_info(tmp_path)["name"] == "张三"

    def test_ignores_government_id_fields(self, tmp_path):
        saved = save_new_facts(
            [{"field_id": "身份证号", "kind": "government_id", "candidate_value": "110101199001011234"}],
            tmp_path,
        )
        assert saved == []
        assert load_personal_info(tmp_path) == {}

    def test_ignores_open_question_fields(self, tmp_path):
        saved = save_new_facts(
            [{"field_id": "自我评价", "kind": "open_question", "candidate_value": "熟悉后端开发"}],
            tmp_path,
        )
        assert saved == []
        assert load_personal_info(tmp_path) == {}

    def test_ignores_empty_candidate_value(self, tmp_path):
        saved = save_new_facts(
            [{"field_id": "学历", "kind": "demographic", "candidate_value": ""}],
            tmp_path,
        )
        assert saved == []

    def test_preserves_existing_fields_when_adding_new_one(self, tmp_path):
        _write(tmp_path, "basic.yaml", "name: 张三\nemail: zhangsan@example.com\n")
        save_new_facts(
            [{"field_id": "学校名称", "kind": "demographic", "candidate_value": "深圳大学"}],
            tmp_path,
        )
        result = load_personal_info(tmp_path)
        assert result == {"name": "张三", "email": "zhangsan@example.com", "学校名称": "深圳大学"}

    def test_no_new_facts_returns_empty_list_without_touching_file(self, tmp_path):
        basic_path = tmp_path / "basic.yaml"
        assert not basic_path.exists()
        saved = save_new_facts([{"field_id": "身份证号", "kind": "government_id", "candidate_value": "x"}], tmp_path)
        assert saved == []
        assert not basic_path.exists()  # 没有新事实时不该创建/改动文件

    def test_written_yaml_is_valid_and_reloadable(self, tmp_path):
        save_new_facts(
            [{"field_id": "学校名称", "kind": "demographic", "candidate_value": "深圳大学"}],
            tmp_path,
        )
        raw = (tmp_path / "basic.yaml").read_text(encoding="utf-8")
        assert yaml.safe_load(raw) == {"学校名称": "深圳大学"}
