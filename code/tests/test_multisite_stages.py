"""第 2 层骨架的名字有两个消费方：图本身，和前端。两处对不上的表现是
"骨架上有一站永远不亮"，跟"卡住了"一模一样——所以在建图时当场对账。"""
import pytest

from multisite.layer1_agent import STAGE_ORDER, build_graph, stage_names


class FakeTool:
    def __init__(self, name):
        self.name = name


class FakeTracker:
    def get_pending_jobs(self):
        return []


def _build(select_only):
    return build_graph(
        tools=[FakeTool("take_snapshot")],
        personal_info={},
        tracker=FakeTracker(),
        quotas={"开发": 1},
        select_only=select_only,
    )


class TestStageNames:
    def test_select_only_stops_at_checkpoint_1(self):
        assert stage_names(True) == ("ensure_ready", "find_jobs", "write_pending_jobs")

    def test_full_run_continues_into_the_form(self):
        assert stage_names(False) == STAGE_ORDER
        assert "write_pending_application" in stage_names(False)


class TestGraphMatchesStageNames:
    def test_select_only_graph_builds(self):
        assert _build(True) is not None

    def test_full_graph_builds(self):
        assert _build(False) is not None

    def test_a_drifted_stage_table_is_rejected_at_build_time(self, monkeypatch):
        """把 stage_names 改掉模拟漂移——建图必须当场炸，而不是等真机跑完
        才发现骨架上有一站永远不亮。"""
        import multisite.layer1_agent as mod
        monkeypatch.setattr(mod, "STAGE_ORDER", ("ensure_ready", "find_jobs", "oops"))
        with pytest.raises(RuntimeError, match="阶段表"):
            _build(True)


class TestStagesEndpoint:
    def test_endpoint_returns_m1_and_m2_stage_lists(self):
        from fastapi.testclient import TestClient

        from dashboard.server import app as fastapi_app

        with TestClient(fastapi_app) as c:
            resp = c.get("/api/multisite/stages")
        assert resp.status_code == 200
        assert resp.json() == {
            "m1": ["ensure_ready", "find_jobs", "write_pending_jobs"],
            "m2": list(STAGE_ORDER),
        }
