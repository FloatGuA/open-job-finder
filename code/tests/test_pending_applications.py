"""Tests for ApplicationTracker's pending_applications CRUD (Layer 2 审批队列)."""
import pytest

from services.tracker import ApplicationTracker


@pytest.fixture
def tracker(tmp_path):
    t = ApplicationTracker(str(tmp_path / "test.db"))
    yield t
    t.close()


def _fields():
    return [
        {"field_id": "name", "label": "姓名", "kind": "demographic", "candidate_value": "张三"},
        {"field_id": "self_intro", "label": "自我评价", "kind": "open_question", "candidate_value": "熟悉后端开发"},
        {"field_id": "id_number", "label": "证件号码", "kind": "government_id", "candidate_value": ""},
    ]


class TestAddAndGet:
    def test_add_returns_id(self, tracker):
        app_id = tracker.add_pending_application(
            site_name="huawei", job_title="后端工程师", fields=_fields(), company="华为",
        )
        assert isinstance(app_id, int) and app_id > 0

    def test_get_pending_application_roundtrips_fields(self, tracker):
        app_id = tracker.add_pending_application(
            site_name="huawei", job_title="后端工程师", fields=_fields(),
        )
        rec = tracker.get_pending_application(app_id)
        assert rec is not None
        assert rec.site_name == "huawei"
        assert rec.status == "pending"
        assert rec.fields == _fields()

    def test_get_nonexistent_returns_none(self, tracker):
        assert tracker.get_pending_application(999) is None

    def test_get_pending_applications_filters_by_status(self, tracker):
        id1 = tracker.add_pending_application(site_name="huawei", job_title="A", fields=_fields())
        id2 = tracker.add_pending_application(site_name="hytera", job_title="B", fields=_fields())
        tracker.decide_pending_application(id1, "approved", fields=_fields())

        pending = tracker.get_pending_applications(status="pending")
        assert [r.id for r in pending] == [id2]

        approved = tracker.get_pending_applications(status="approved")
        assert [r.id for r in approved] == [id1]

        assert len(tracker.get_pending_applications()) == 2


class TestDecide:
    def test_approve_writes_final_fields_and_decided_at(self, tracker):
        app_id = tracker.add_pending_application(site_name="huawei", job_title="A", fields=_fields())
        edited = _fields()
        edited[2]["candidate_value"] = "110101199001011234"  # reviewer fills government_id by hand

        rowcount = tracker.decide_pending_application(app_id, "approved", fields=edited)
        assert rowcount == 1

        rec = tracker.get_pending_application(app_id)
        assert rec.status == "approved"
        assert rec.fields[2]["candidate_value"] == "110101199001011234"
        assert rec.decided_at is not None

    def test_reject_records_reason_without_touching_fields(self, tracker):
        app_id = tracker.add_pending_application(site_name="huawei", job_title="A", fields=_fields())
        rowcount = tracker.decide_pending_application(app_id, "rejected", reason="岗位不合适")
        assert rowcount == 1

        rec = tracker.get_pending_application(app_id)
        assert rec.status == "rejected"
        assert rec.reason == "岗位不合适"
        assert rec.fields == _fields()

    def test_decide_already_decided_is_noop(self, tracker):
        app_id = tracker.add_pending_application(site_name="huawei", job_title="A", fields=_fields())
        tracker.decide_pending_application(app_id, "approved", fields=_fields())

        rowcount = tracker.decide_pending_application(app_id, "rejected", reason="改主意了")
        assert rowcount == 0
        assert tracker.get_pending_application(app_id).status == "approved"

    def test_decide_rejects_invalid_decision(self, tracker):
        app_id = tracker.add_pending_application(site_name="huawei", job_title="A", fields=_fields())
        with pytest.raises(AssertionError):
            tracker.decide_pending_application(app_id, "maybe")
