"""第 2 层骨架的名字有两个消费方：图本身，和前端。两处对不上的表现是
"骨架上有一站永远不亮"，跟"卡住了"一模一样——所以在建图时当场对账。"""
import pytest

from multisite.layer1_agent import M1_STAGES, M2_STAGES, build_graph, stage_names


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
    def test_m1_is_selection_only(self):
        assert stage_names("m1") == ("ensure_ready", "find_jobs", "write_pending_jobs")

    def test_m2_surveys_the_form(self):
        assert stage_names("m2") == (
            "ensure_ready", "open_application",
            "scan_and_classify_fields", "write_pending_application",
        )

    def test_m2_is_not_m1_plus_a_suffix(self):
        """以前 m2 = STAGE_ORDER[:3] + 三站，那个切片把「m2 是 m1 的延长」写进了代码。
        m2 里 find_jobs / write_pending_jobs 是幽灵节点：前者把调用方给的那一个岗位
        原样传回，后者因 url 已在库里而空转。"""
        assert "find_jobs" not in M2_STAGES
        assert "write_pending_jobs" not in M2_STAGES

    def test_unknown_workflow_fails_loudly(self):
        with pytest.raises(ValueError, match="workflow"):
            stage_names("m9")


class TestGraphMatchesStageNames:
    def test_select_only_graph_builds(self):
        assert _build(True) is not None

    def test_full_graph_still_builds(self):
        """本任务只改阶段表定义，不拆 build_graph。中间态里 m2 那条路建的仍是
        拆分前的 6 站——**但它必须照常能建起来**。一个 task 不该留下真实功能
        会崩的状态，更不该把崩溃写成绿色断言。"""
        assert _build(False) is not None

    def test_a_drifted_stage_table_is_rejected_at_build_time(self, monkeypatch):
        """把 stage_names 改掉模拟漂移——建图必须当场炸，而不是等真机跑完
        才发现骨架上有一站永远不亮。"""
        import multisite.layer1_agent as mod
        drifted = ("ensure_ready", "find_jobs", "oops")
        monkeypatch.setattr(mod, "M1_STAGES", drifted)
        monkeypatch.setitem(mod._STAGES_BY_WORKFLOW, "m1", drifted)
        with pytest.raises(RuntimeError, match="阶段表"):
            _build(True)


class TestStagesEndpoint:
    def test_endpoint_returns_m1_and_m2_stage_lists(self):
        from fastapi.testclient import TestClient

        from dashboard.server import app as fastapi_app

        with TestClient(fastapi_app) as c:
            resp = c.get("/api/multisite/stages")
        assert resp.status_code == 200
        body = resp.json()
        assert body["m1"] == list(M1_STAGES)
        assert body["m2"] == list(M2_STAGES)
        assert isinstance(body["max_steps"], int)
