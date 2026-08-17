"""第 2 层骨架的名字有两个消费方：图本身，和前端。两处对不上的表现是
"骨架上有一站永远不亮"，跟"卡住了"一模一样——所以在建图时当场对账。"""
import pytest

from multisite.layer1_agent import (
    M1_STAGES,
    M2_STAGES,
    build_graph,
    build_select_graph,
    build_survey_graph,
    stage_names,
)


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
        """`build_graph` 现在是薄壳，`select_only=False` 转调 `build_survey_graph`
        （m2 的新 4 站图）。壳必须能正常建图——`run_layer1` 还在靠它跑真实的
        `select_only=False` 调用，Task 3 删壳之前它不能崩。"""
        assert _build(False) is not None

    def test_a_drifted_stage_table_is_rejected_at_build_time(self, monkeypatch):
        """把 stage_names 改掉模拟漂移——建图必须当场炸，而不是等真机跑完
        才发现骨架上有一站永远不亮。

        **只 patch `M1_STAGES`，不 patch `_STAGES_BY_WORKFLOW`。** 拆图后
        `build_select_graph` 拼阶段表时读的是**活的**模块全局 `M1_STAGES`，
        而 `stage_names()` 读的是导入时就定住的 `_STAGES_BY_WORKFLOW` 字典——
        两者只有一个跟着 patch 变，才会真的对不上。以前 `build_graph` 的阶段表
        是硬编码字面量、根本不读 `M1_STAGES`，所以那时 `setattr(M1_STAGES)` 是
        空操作，只有紧跟着 `setitem(_STAGES_BY_WORKFLOW)` 才生效——**如果两个都
        patch（旧写法），两边会一起变成 drifted 值，对账反而通过，测试会变假绿**，
        所以这里只保留真正生效的那一个。
        """
        import multisite.layer1_agent as mod
        drifted = ("ensure_ready", "find_jobs", "oops")
        monkeypatch.setattr(mod, "M1_STAGES", drifted)
        with pytest.raises(RuntimeError, match="阶段表"):
            _build(True)


def _kw():
    return dict(tools=[FakeTool("take_snapshot")], personal_info={},
                tracker=FakeTracker(), quotas={"开发": 1})


class TestTwoGraphs:
    def test_select_graph_builds(self):
        assert build_select_graph(**_kw()) is not None

    def test_survey_graph_builds(self):
        assert build_survey_graph(**_kw()) is not None

    def test_drifted_stage_table_is_rejected_at_build_time(self, monkeypatch):
        """名字漂移的表现是「骨架上有一站永远不亮」，跟卡住了一模一样、测不出来。
        所以在建图时当场炸。"""
        import multisite.layer1_agent as mod
        monkeypatch.setattr(mod, "M1_STAGES", ("ensure_ready", "find_jobs", "oops"))
        with pytest.raises(RuntimeError, match="阶段表"):
            build_select_graph(**_kw())

    def test_survey_graph_drift_is_rejected_too(self, monkeypatch):
        """m1 和 m2 各自独立对账——只测 m1 会让 m2 这条路的 drift 保护成为一段
        从没被验证过的代码（`build_survey_graph` 内部同样调用 `_compile`，但
        「同样调用」不等于「同样测过」）。"""
        import multisite.layer1_agent as mod
        monkeypatch.setattr(mod, "M2_STAGES",
                            ("ensure_ready", "open_application", "oops",
                             "write_pending_application"))
        with pytest.raises(RuntimeError, match="阶段表"):
            build_survey_graph(**_kw())


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
