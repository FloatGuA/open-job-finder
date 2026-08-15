"""m1/m2 跟系统其余部分的接线：队列参数、run 日志摘要、前后端 workflow 白名单。

**这一组守的都是"接线断了但没人报错"的那类缺陷**——它们的共同表现是"跑完了、
没报错、只是某件事悄悄没发生"，全都是靠真机跑或者用户点出来才发现的：

- `--category` / `--max-pages` 放不进队列 params → 默认路径上静默失效，
  而脚本还照常打印「本站生效名额」，打印的和实际跑的不是一回事；
- 前端 `WorkflowId` 少了 m1/m2 → `WF_META[item.workflow]` 是 undefined，
  队列页一渲染就抛，**没有 ErrorBoundary，整个 SPA 白屏**；
- `source_job_id` 生产路径不写 → 两个 checkpoint 的记录互相认不出来，
  而 tracker 那层的测试是绿的（它测的是"能写"，不是"有人写"）。
"""
import importlib.util
import re
import sys
from pathlib import Path

import pytest

from services.tracker import ApplicationTracker
from services.workflow_orchestration import OrchestrationService
from services.workflow_queue import VALID_WORKFLOWS

CODE_DIR = Path(__file__).resolve().parent.parent


# ── 前后端 workflow 白名单必须一致 ────────────────────────────────────────────

class TestWorkflowIdContract:
    """前端 `WorkflowId` 联合类型 == 后端 `VALID_WORKFLOWS`。

    这是一个跨语言契约，两边各写一份必然漂移——m1/m2 上线时后端加了、前端没加，
    结果队列页白屏。tsc 只能保证 `Record<WorkflowId, …>` 的键是齐的，**保证不了
    WorkflowId 本身没漏后端的某个 workflow**，那正是漏掉的那一层。
    """

    @staticmethod
    def _frontend_ids() -> set:
        src = (CODE_DIR / "dashboard" / "frontend" / "src" / "api" / "index.ts").read_text(
            encoding="utf-8")
        m = re.search(r"export type WorkflowId\s*=\s*([^\n]+)", src)
        assert m, "api/index.ts 里找不到 WorkflowId 的声明（改名了？）"
        return set(re.findall(r"'([^']+)'", m.group(1)))

    def test_frontend_covers_every_backend_workflow(self):
        assert self._frontend_ids() == set(VALID_WORKFLOWS)


class TestRunLogsAreReachableByPipeline:
    """m1/m2 的 run 日志要能按 pipeline 筛出来。

    日志文件叫 `m1_*.jsonl`，但端点的白名单是另写的一份——两份不同步的表现是
    "日志明明在磁盘上，一按筛选就 400"。
    """

    def test_every_workflow_is_accepted_by_the_runs_endpoint(self):
        from fastapi.testclient import TestClient

        from dashboard.server import app as fastapi_app

        with TestClient(fastapi_app) as c:
            for wf in VALID_WORKFLOWS:
                assert c.get(f"/api/runs?pipeline={wf}").status_code == 200, wf

    def test_logs_page_can_filter_by_every_workflow(self):
        """前端日志页的筛选按钮同理——后端接受了但页面上点不到，等于没有。"""
        src = (CODE_DIR / "dashboard" / "frontend" / "src" / "pages" / "Logs.tsx").read_text(
            encoding="utf-8")
        m = re.search(r"type PipelineFilter\s*=\s*([^\n]+)", src)
        assert m, "Logs.tsx 里找不到 PipelineFilter 的声明（改名了？）"
        options = set(re.findall(r"'([^']*)'", m.group(1)))
        assert set(VALID_WORKFLOWS) <= options


# ── m1/m2 的队列参数透传 ──────────────────────────────────────────────────────

class _FakeEmitter:
    def __init__(self):
        self.current_workflow = None


class _FakeState:
    def __init__(self, tracker):
        self.tracker = tracker
        self.emitter = _FakeEmitter()


@pytest.fixture()
def tracker(tmp_path):
    return ApplicationTracker(db_path=str(tmp_path / "t.db"))


@pytest.fixture()
def service(tmp_path, tracker):
    return OrchestrationService(
        get_state=lambda: _FakeState(tracker),
        ensure_state=lambda: None,
        data_dir=tmp_path,
        write_schedule_log=lambda entry: None,
        write_selfcheck_log=lambda entry: None,
        smoke_log_path=tmp_path / "smoke.jsonl",
    )


@pytest.fixture()
def captured_run(monkeypatch):
    """拦下 run_layer1，记录它实际收到的关键字参数。

    打的是 `multisite.layer1_agent.run_layer1`（而不是 orchestration 里的名字）：
    那边是在函数体内 import 的，patch 模块属性才拦得住。
    """
    import multisite.layer1_agent as la

    calls = []

    async def fake_run_layer1(**kwargs):
        calls.append(kwargs)
        return {"found_jobs": [], "pending_job_ids": [], "open_result": None,
                "classified_fields": [], "pending_application_id": None}

    monkeypatch.setattr(la, "run_layer1", fake_run_layer1)
    return calls


class TestSelectPassthrough:
    def test_categories_and_max_pages_reach_run_layer1(self, service, captured_run):
        """CLI 的 --category / --max-pages 经队列 params 一路传到底。

        以前这两个开关**只在 --direct 下生效**：CLI 不往 body 里放，队列侧也不读。
        默认路径正是走队列的，于是它们静默失效——最坏的一种，因为没有任何报错。
        """
        service._run_multisite_select({"site": "s", "search_url": "https://x/jobs",
                                       "categories": {"开发": 5}, "max_pages": 3})
        kw = captured_run[0]
        assert kw["quotas"] == {"开发": 5}
        assert kw["max_pages"] == 3

    def test_defaults_when_not_given(self, service, captured_run):
        # 不给 = 用 profile 的站点解析结果（quotas=None 让 run_layer1 自己解析）+ 默认 8 页。
        service._run_multisite_select({"site": "s", "search_url": "https://x/jobs"})
        kw = captured_run[0]
        assert kw["quotas"] is None
        assert kw["max_pages"] == 8

    def test_select_only_is_always_on(self, service, captured_run):
        # m1 永远只跑到 Checkpoint 1，填表是 m2 的事。
        service._run_multisite_select({"site": "s", "search_url": "https://x/jobs"})
        assert captured_run[0]["select_only"] is True

    def test_bad_categories_type_raises(self, service, captured_run):
        # 悄悄忽略一个写错的 categories，表现跟"配置漏写"完全一样，极难查。
        with pytest.raises(ValueError):
            service._run_multisite_select({"site": "s", "search_url": "https://x",
                                           "categories": ["开发", 5]})
        assert captured_run == []


class TestFillPassthrough:
    def test_approved_job_runs_with_its_url(self, service, captured_run, tracker,
                                            tmp_path):
        job_id = tracker.add_pending_job(site_name="s", url="https://x/1", title="t")
        tracker.decide_pending_job(job_id, "approved")
        service._run_multisite_fill({"pending_job_id": job_id,
                                     "resume_pdf_path": str(tmp_path / "r.pdf")})
        assert captured_run[0]["job_url"] == "https://x/1"

    def test_unapproved_job_refused(self, service, captured_run, tracker, tmp_path):
        # 没批准就填表 = 绕过 Checkpoint 1。守门在队列这一层，不在 UI。
        job_id = tracker.add_pending_job(site_name="s", url="https://x/2", title="t")
        with pytest.raises(ValueError):
            service._run_multisite_fill({"pending_job_id": job_id,
                                         "resume_pdf_path": str(tmp_path / "r.pdf")})
        assert captured_run == []


# ── CLI → 队列 的参数打包 ────────────────────────────────────────────────────

def _load_cli():
    path = CODE_DIR / "scripts" / "run_layer1.py"
    spec = importlib.util.spec_from_file_location("run_layer1_cli", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_layer1_cli"] = mod
    spec.loader.exec_module(mod)
    return mod


class _Args:
    def __init__(self, **kw):
        self.search_url = ""
        self.job_url = ""
        self.site = "s"
        self.headless = False
        self.max_pages = 8
        self.select_only = False
        self.dashboard = "http://127.0.0.1:8765"
        self.__dict__.update(kw)


class TestCliEnqueuesFullParams:
    def test_m1_body_carries_categories_and_max_pages(self, monkeypatch):
        cli = _load_cli()
        sent = {}

        class _Resp:
            def __enter__(self_inner):
                return self_inner

            def __exit__(self_inner, *a):
                return False

            def read(self_inner):
                return b'{"status": "pending", "id": "1"}'

        def fake_urlopen(req, timeout=10):
            sent["body"] = req.data.decode("utf-8")
            return _Resp()

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

        rc = cli._enqueue_via_dashboard(
            _Args(search_url="https://x/jobs", max_pages=3), "", {"开发": 5})

        assert rc == 0
        import json
        body = json.loads(sent["body"])
        assert body["workflow"] == "m1"
        assert body["params"]["categories"] == {"开发": 5}
        assert body["params"]["max_pages"] == 3

    def test_dashboard_down_does_not_fall_back_to_direct(self, monkeypatch):
        """连不上就退出并给出提示，**绝不静默改走 --direct**——"安全路径失败时
        自动改走不安全路径"比一开始就不安全更糟（直接跑会跟 W1/W2 抢浏览器）。"""
        cli = _load_cli()
        import urllib.error
        import urllib.request

        def boom(req, timeout=10):
            raise urllib.error.URLError("refused")

        monkeypatch.setattr(urllib.request, "urlopen", boom)
        with pytest.raises(SystemExit):
            cli._enqueue_via_dashboard(_Args(search_url="https://x/jobs"), "", None)
