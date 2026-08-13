"""Tests for multisite.personal_info_loader — pure function, no I/O beyond tmp_path."""
import yaml
import pytest

from multisite.personal_info_loader import load_identity, load_personal_info, save_identity, save_new_facts


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_pool(pool_path, basic_info: dict):
    _write(pool_path, yaml.safe_dump({"basic_info": basic_info}, allow_unicode=True))


class TestLoadPersonalInfo:
    def test_merges_pool_identity_and_identity_yaml(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"
        _write_pool(pool_path, {"name": "张三", "phone": "13800000000", "email": "zhangsan@example.com", "city": "深圳"})
        _write(data_dir / "identity.yaml", "gender: 男\nbirth_date: '2000-01-01'\n")

        result = load_personal_info(data_dir, pool_path)

        assert result == {
            "name": "张三",
            "phone": "13800000000",
            "email": "zhangsan@example.com",
            "gender": "男",
            "birth_date": "2000-01-01",
        }

    def test_pool_non_identity_fields_are_not_included(self, tmp_path):
        """city/degree/target_title 是简历抬头概念，不是身份事实，不该混进来。"""
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"
        _write_pool(pool_path, {"name": "张三", "city": "深圳", "degree": "本科", "target_title": "后端工程师"})

        result = load_personal_info(data_dir, pool_path)

        assert result == {"name": "张三"}

    def test_missing_pool_file_returns_only_identity(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"
        _write(data_dir / "identity.yaml", "gender: 男\n")

        assert load_personal_info(data_dir, pool_path) == {"gender": "男"}

    def test_missing_identity_file_returns_only_pool(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"
        _write_pool(pool_path, {"name": "张三"})

        assert load_personal_info(data_dir, pool_path) == {"name": "张三"}

    def test_empty_values_are_dropped(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"
        _write_pool(pool_path, {"name": "张三", "email": "", "phone": None})
        _write(data_dir / "identity.yaml", "gender: ''\n")

        assert load_personal_info(data_dir, pool_path) == {"name": "张三"}

    def test_government_id_key_raises(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"
        _write(data_dir / "identity.yaml", "id_number: '110101199001011234'\n")

        with pytest.raises(ValueError, match="政府证件号码"):
            load_personal_info(data_dir, pool_path)

    def test_real_project_files_load_without_forbidden_keys(self):
        """Sanity check against the actual (gitignored) data files, if present in
        this environment -- confirms the hard constraint holds in production
        data, not just synthetic fixtures."""
        from multisite.personal_info_loader import DATA_DIR

        if not DATA_DIR.exists():
            pytest.skip("data/personal_info/ not present in this environment")
        load_personal_info()  # must not raise


class TestSaveNewFacts:
    def test_saves_new_demographic_field_to_identity_yaml(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"

        saved = save_new_facts(
            [{"field_id": "学校名称", "kind": "demographic", "candidate_value": "深圳大学"}],
            data_dir, pool_path,
        )
        assert saved == ["学校名称"]
        assert load_personal_info(data_dir, pool_path) == {"学校名称": "深圳大学"}

    def test_does_not_overwrite_existing_pool_key(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"
        _write_pool(pool_path, {"name": "张三"})

        saved = save_new_facts(
            [{"field_id": "name", "kind": "demographic", "candidate_value": "李四"}],
            data_dir, pool_path,
        )
        assert saved == []
        assert load_personal_info(data_dir, pool_path)["name"] == "张三"
        assert not (data_dir / "identity.yaml").exists()  # 没有真正新增的事实，不该动文件

    def test_does_not_overwrite_existing_identity_key(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"
        _write(data_dir / "identity.yaml", "gender: 男\n")

        saved = save_new_facts(
            [{"field_id": "gender", "kind": "demographic", "candidate_value": "女"}],
            data_dir, pool_path,
        )
        assert saved == []
        assert load_personal_info(data_dir, pool_path)["gender"] == "男"

    def test_ignores_government_id_fields(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"

        saved = save_new_facts(
            [{"field_id": "身份证号", "kind": "government_id", "candidate_value": "110101199001011234"}],
            data_dir, pool_path,
        )
        assert saved == []
        assert load_personal_info(data_dir, pool_path) == {}

    def test_ignores_open_question_fields(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"

        saved = save_new_facts(
            [{"field_id": "自我评价", "kind": "open_question", "candidate_value": "熟悉后端开发"}],
            data_dir, pool_path,
        )
        assert saved == []
        assert load_personal_info(data_dir, pool_path) == {}

    def test_ignores_empty_candidate_value(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"

        saved = save_new_facts(
            [{"field_id": "学历", "kind": "demographic", "candidate_value": ""}],
            data_dir, pool_path,
        )
        assert saved == []

    def test_preserves_existing_identity_fields_when_adding_new_one(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"
        _write(data_dir / "identity.yaml", "gender: 男\nbirth_date: '2000-01-01'\n")

        save_new_facts(
            [{"field_id": "学校名称", "kind": "demographic", "candidate_value": "深圳大学"}],
            data_dir, pool_path,
        )
        result = load_personal_info(data_dir, pool_path)
        assert result == {"gender": "男", "birth_date": "2000-01-01", "学校名称": "深圳大学"}

    def test_no_new_facts_returns_empty_list_without_touching_file(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"
        identity_path = data_dir / "identity.yaml"
        assert not identity_path.exists()

        saved = save_new_facts(
            [{"field_id": "身份证号", "kind": "government_id", "candidate_value": "x"}],
            data_dir, pool_path,
        )
        assert saved == []
        assert not identity_path.exists()  # 没有新事实时不该创建/改动文件

    def test_written_yaml_is_valid_and_reloadable(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"

        save_new_facts(
            [{"field_id": "学校名称", "kind": "demographic", "candidate_value": "深圳大学"}],
            data_dir, pool_path,
        )
        raw = (data_dir / "identity.yaml").read_text(encoding="utf-8")
        assert yaml.safe_load(raw) == {"学校名称": "深圳大学"}


class TestLoadIdentity:
    def test_reads_identity_yaml_only(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        _write(data_dir / "identity.yaml", "gender: 男\nbirth_date: '2000-01-01'\n")

        assert load_identity(data_dir) == {"gender": "男", "birth_date": "2000-01-01"}

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_identity(tmp_path / "personal_info") == {}

    def test_empty_values_dropped(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        _write(data_dir / "identity.yaml", "gender: 男\nbirth_date: ''\n")

        assert load_identity(data_dir) == {"gender": "男"}

    def test_government_id_key_raises(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        _write(data_dir / "identity.yaml", "id_number: '110101199001011234'\n")

        with pytest.raises(ValueError, match="政府证件号码"):
            load_identity(data_dir)


class TestSaveIdentity:
    def test_writes_and_reloads(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        save_identity({"gender": "男", "birth_date": "2000-01-01"}, data_dir)

        assert load_identity(data_dir) == {"gender": "男", "birth_date": "2000-01-01"}

    def test_overwrites_wholesale_not_merges(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        _write(data_dir / "identity.yaml", "gender: 男\n学校名称: 深圳大学\n")

        save_identity({"gender": "女"}, data_dir)

        assert load_identity(data_dir) == {"gender": "女"}  # 学校名称 被整体覆盖掉了

    def test_drops_empty_values(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        save_identity({"gender": "男", "birth_date": ""}, data_dir)

        assert load_identity(data_dir) == {"gender": "男"}

    def test_rejects_government_id_key(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        with pytest.raises(ValueError, match="政府证件号码"):
            save_identity({"id_number": "110101199001011234"}, data_dir)
        assert not (data_dir / "identity.yaml").exists()  # 拒绝时不该留下文件
