"""Tests for multisite.personal_info_loader — pure function, no I/O beyond tmp_path."""
import yaml
import pytest

from multisite.personal_info_loader import (
    load_identity,
    load_personal_info,
    match_value,
    resolve_key,
    save_identity,
    save_new_facts,
)


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


class TestResolveKey:
    """字段名同义归一：不同网站对同一个事实叫法不同，必须都能落到同一个 key。"""

    KNOWN = ["name", "phone", "email", "gender", "birth_date"]

    def test_exact_match(self):
        assert resolve_key("birth_date", self.KNOWN) == "birth_date"

    @pytest.mark.parametrize("label", ["生日", "出生日期", "出生年月", "birthday", "Date of Birth", "DOB"])
    def test_birth_date_synonyms(self, label):
        assert resolve_key(label, self.KNOWN) == "birth_date"

    @pytest.mark.parametrize("label", ["手机号码", "联系电话", "手机", "Mobile", "phone_number"])
    def test_phone_synonyms(self, label):
        assert resolve_key(label, self.KNOWN) == "phone"

    @pytest.mark.parametrize("label", ["姓名 *", "姓名*", " 姓名 ", "姓名：", "Full Name"])
    def test_normalization_strips_required_marker_and_spacing(self, label):
        """真机扫到的 label 经常带 ` *`（必填标记）或全角冒号。"""
        assert resolve_key(label, self.KNOWN) == "name"

    def test_unknown_label_returns_none(self):
        assert resolve_key("最高学历院校排名", self.KNOWN) is None

    def test_empty_label_returns_none(self):
        assert resolve_key("", self.KNOWN) is None

    def test_resolves_when_stored_key_is_itself_a_synonym(self):
        """存储里存的可能是中文别名（审批时人工存进去的），用英文规范名也要能查到。"""
        assert resolve_key("birth_date", ["生日", "gender"]) == "生日"
        assert resolve_key("出生年月", ["生日", "gender"]) == "生日"

    def test_does_not_match_across_different_facts(self):
        assert resolve_key("性别", ["birth_date"]) is None


class TestMatchValue:
    def test_returns_value_via_synonym(self):
        info = {"birth_date": "2000-01-01", "name": "张三"}
        assert match_value("生日", info) == "2000-01-01"
        assert match_value("出生年月", info) == "2000-01-01"

    def test_returns_empty_when_no_match(self):
        assert match_value("最高学历院校排名", {"name": "张三"}) == ""

    def test_returns_empty_for_empty_info(self):
        assert match_value("生日", {}) == ""


class TestSaveNewFactsSynonymDedup:
    """同义字段不该被当成新字段重复保存——否则 identity.yaml 会越攒越乱。"""

    def test_synonym_of_existing_key_is_not_saved_again(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"
        _write(data_dir / "identity.yaml", "birth_date: '2000-01-01'\n")

        saved = save_new_facts(
            [{"field_id": "生日", "kind": "demographic", "candidate_value": "2000-01-01"}],
            data_dir, pool_path,
        )

        assert saved == []
        assert load_identity(data_dir) == {"birth_date": "2000-01-01"}

    def test_synonym_of_pool_key_is_not_saved_again(self, tmp_path):
        """姓名的真源在 info_pool，表单叫「姓名」时不该在 identity.yaml 里再存一份。"""
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"
        _write_pool(pool_path, {"name": "张三"})

        saved = save_new_facts(
            [{"field_id": "姓名", "kind": "demographic", "candidate_value": "张三"}],
            data_dir, pool_path,
        )

        assert saved == []
        assert not (data_dir / "identity.yaml").exists()

    def test_two_synonyms_in_same_batch_save_only_once(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"

        saved = save_new_facts(
            [
                {"field_id": "生日", "kind": "demographic", "candidate_value": "2000-01-01"},
                {"field_id": "出生日期", "kind": "demographic", "candidate_value": "2000-01-01"},
            ],
            data_dir, pool_path,
        )

        assert saved == ["生日"]
        assert load_identity(data_dir) == {"生日": "2000-01-01"}

    def test_genuinely_new_field_still_saved(self, tmp_path):
        data_dir = tmp_path / "personal_info"
        pool_path = tmp_path / "info_pool.yaml"
        _write(data_dir / "identity.yaml", "birth_date: '2000-01-01'\n")

        saved = save_new_facts(
            [{"field_id": "英语能力", "kind": "demographic", "candidate_value": "CET-6"}],
            data_dir, pool_path,
        )

        assert saved == ["英语能力"]
