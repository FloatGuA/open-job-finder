"""Tests for multisite.personal_info_loader — pure function, no I/O beyond tmp_path."""
import pytest

from multisite.personal_info_loader import load_personal_info


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
