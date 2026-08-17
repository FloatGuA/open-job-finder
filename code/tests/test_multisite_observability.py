"""m1/m2 的可观测性：跑的时候能看到进度，跑完能回放。

**断言的是真的落盘了什么**（把 RUNS_DIR 指到 tmp_path 再读回 JSONL），不是"某个
函数被调用过"——这条链路的价值全在文件里那几行，中间调用对了而写出来的东西不对
等于没有。
"""
import asyncio
import json

import pytest

from multisite.observability import traced_stage
from services import run_logger as run_logger_module


@pytest.fixture()
def runs_dir(tmp_path, monkeypatch):
    d = tmp_path / "runs"
    d.mkdir()
    monkeypatch.setattr(run_logger_module, "RUNS_DIR", d)
    return d


def read_events(runs_dir) -> list:
    files = list(runs_dir.glob("*.jsonl"))
    assert len(files) == 1, f"期望正好一个 run 文件，实际 {[f.name for f in files]}"
    return [json.loads(line) for line in files[0].read_text(encoding="utf-8").splitlines() if line]


class TestRunScope:
    """一次 m1/m2 运行的生命周期：开头写 run_start，结尾**无论如何**写 run_end。

    跟浏览器拆开是被这组测试逼出来的——原本这段生命周期是手写在 `run_layer1` 里
    的 try/except，而 `run_layer1` 要开真 Chrome 才跑得起来，于是它一条测试都没有。
    """

    def test_writes_run_start_and_end(self, runs_dir):
        from multisite.observability import run_scope

        with run_scope("m1") as run:
            run.summary["found"] = 3

        events = read_events(runs_dir)
        assert events[0]["event"] == "run_start"
        assert events[0]["pipeline"] == "m1"
        assert events[-1]["event"] == "run_end"
        assert events[-1]["status"] == "done"
        assert events[-1]["summary"] == {"found": 3}

    def test_failure_still_writes_run_end(self, runs_dir):
        """**读 run 日志的铁律之一：没有 run_end 意味着"可能还在写"。** 炸掉却不写
        run_end，事后翻日志会把一次失败读成一次进行中的运行。"""
        from multisite.observability import run_scope

        with pytest.raises(RuntimeError):
            with run_scope("m2"):
                raise RuntimeError("chrome 起不来")

        events = read_events(runs_dir)
        assert events[-1]["event"] == "run_end"
        assert events[-1]["status"] == "failed"

    def test_run_id_is_prefixed_by_workflow(self, runs_dir):
        # 日志按 pipeline 前缀筛（/api/runs?pipeline=m1），前缀错了就永远筛不到。
        from multisite.observability import run_scope

        with run_scope("m1"):
            pass
        assert list(runs_dir.glob("m1_*.jsonl"))


class TestSseMirroring:
    """给了 emitter 就同时推 SSE。用**真的** ProgressEmitter + 真的订阅队列，
    断言前端实际会收到什么——断言"某个方法被调用过"证明不了事件长什么样。"""

    @staticmethod
    def _drain(q) -> list:
        out = []
        while not q.empty():
            out.append(q.get_nowait())
        return out

    def test_run_and_steps_reach_subscribers(self, runs_dir):
        from services.progress_emitter import ProgressEmitter

        from multisite.observability import run_scope, traced_stage

        emitter = ProgressEmitter()
        q = emitter.subscribe()

        async def find_jobs(state):
            return {}

        with run_scope("m1", emitter=emitter) as run:
            asyncio.run(traced_stage("find_jobs", find_jobs, run.logger)({}))

        steps = [e.step for e in self._drain(q)]
        assert steps[0] == "start"          # 开始跑了
        assert "find_jobs" in steps          # 现在跑到哪一步
        assert steps[-1] == "done"           # 跑完了

    def test_failure_leaves_the_done_event_to_the_queue(self, runs_dir):
        """失败时**不发** finish_workflow：队列的 `run_item` 已经在它的 except 里发了。
        两边都发，前端会收到两个终止事件——而 `done` 是"workflow 结束"的权威信号。"""
        from services.progress_emitter import ProgressEmitter

        from multisite.observability import run_scope

        emitter = ProgressEmitter()
        q = emitter.subscribe()
        with pytest.raises(RuntimeError):
            with run_scope("m1", emitter=emitter):
                raise RuntimeError("x")

        assert [e.step for e in self._drain(q)] == ["start"]

    def test_works_without_an_emitter(self, runs_dir):
        """命令行 `--direct` 跑时没有 emitter，**JSONL 照样要落**——它才是完整数据源，
        SSE 只是实时镜像。"""
        from multisite.observability import run_scope

        with run_scope("m1"):
            pass
        assert read_events(runs_dir)[-1]["event"] == "run_end"


class TestStageLogging:
    """工作流的一个阶段跑完，run 日志里要留下一条能定位它的记录。"""

    def test_successful_stage_writes_one_step(self, runs_dir):
        from multisite.observability import traced_stage
        from pipeline.run_logger import RunLogger

        logger = RunLogger(pipeline="m1")

        async def find_jobs(state):
            return {"found_jobs": []}

        asyncio.run(traced_stage("find_jobs", find_jobs, logger)({"site_name": "acme"}))

        steps = [e for e in read_events(runs_dir) if e.get("event") == "step"]
        assert len(steps) == 1
        assert steps[0]["step"] == "find_jobs"
        assert steps[0]["status"] == "successful"

    def test_failed_stage_is_recorded_with_its_error(self, runs_dir):
        """炸掉的阶段必须**也**留下记录。只记成功的话，日志里"没有这一步"会同时
        意味着"没跑到"和"跑了但炸了"，而这两件事的处理方式完全不同。"""
        from multisite.observability import traced_stage
        from pipeline.run_logger import RunLogger

        logger = RunLogger(pipeline="m1")

        async def open_application(state):
            raise RuntimeError("上传控件没找到")

        with pytest.raises(RuntimeError):
            asyncio.run(traced_stage("open_application", open_application, logger)({}))

        steps = [e for e in read_events(runs_dir) if e.get("event") == "step"]
        assert len(steps) == 1
        assert steps[0]["status"] == "failed"
        assert "上传控件没找到" in steps[0]["error"]

    def test_step_carries_a_summary_of_what_happened(self, runs_dir):
        """"find_jobs successful"回答不了任何问题——事后要看的是"找到了几个、都是
        什么类别"。摘要**跟着阶段走**（包装时就近给出），不是让包装器认识每个阶段的
        输出形状：那样加一个阶段要改两个地方，而漏改的表现是日志里少几个数字，没有
        任何东西会变红。
        """
        from multisite.observability import traced_stage
        from pipeline.run_logger import RunLogger

        async def find_jobs(state):
            return {"found_jobs": ["a", "b", "c"]}

        wrapped = traced_stage("find_jobs", find_jobs, RunLogger(pipeline="m1"),
                               summarize=lambda out: {"found": len(out["found_jobs"])})
        asyncio.run(wrapped({}))

        step = [e for e in read_events(runs_dir) if e.get("event") == "step"][0]
        assert step["data"] == {"found": 3}

    def test_failure_still_propagates(self, runs_dir):
        """记日志不是处理异常。吞掉的话，上层会以为这一步成功了，继续往下跑——
        m2 里下一步是扫描表单字段，在一个没打开的表单上扫，只会产出垃圾记录。"""
        from multisite.observability import traced_stage
        from pipeline.run_logger import RunLogger

        async def boom(state):
            raise ValueError("原样抛出去")

        with pytest.raises(ValueError, match="原样抛出去"):
            asyncio.run(traced_stage("x", boom, RunLogger(pipeline="m1"))({}))


from multisite.observability import agent_step_sink


class RecordingLogger:
    def __init__(self):
        self.calls = []

    def log_agent_step(self, step, record):
        self.calls.append((step, record))


class TestAgentStepSink:
    def test_forwards_the_record_under_its_stage(self):
        logger = RecordingLogger()
        sink = agent_step_sink(logger, "find_jobs")
        sink({"kind": "think", "seq": 1, "text": "x", "calls": []})

        assert logger.calls == [("find_jobs", {"kind": "think", "seq": 1,
                                               "text": "x", "calls": []})]

    def test_no_logger_means_no_sink(self):
        """命令行 --direct 那条路径没有 logger；返回 None 让 run_agent 走原样。"""
        assert agent_step_sink(None, "find_jobs") is None


class DumpLogger:
    """够 traced_stage 用的最小 logger：记 step、给 run_id。"""

    def __init__(self, run_id="m1_dump"):
        self.run_id = run_id
        self.steps = []

    def log_step(self, name, scope, status, duration_ms, data=None, error=None):
        self.steps.append({"name": name, "status": status, "data": data or {},
                           "error": error})


class TestFailureSnapshot:
    def _run(self, logger, provider, runs_dir, monkeypatch):
        import services.run_logger as srl
        monkeypatch.setattr(srl, "RUNS_DIR", runs_dir)

        async def boom(state):
            raise RuntimeError("找不到筛选器")

        wrapped = traced_stage("find_jobs", boom, logger, snapshot_provider=provider)
        with pytest.raises(RuntimeError):
            asyncio.run(wrapped({"snapshot_text": "这是上一个阶段的旧快照"}))

    def test_dumps_the_providers_snapshot_not_the_state_one(self, tmp_path, monkeypatch):
        """state["snapshot_text"] 只在阶段**成功返回**时才写回，阶段失败时它装的是
        **上一个**阶段的快照——正好在最需要它的时候是错的。"""
        logger = DumpLogger()
        self._run(logger, lambda: "这是 agent 循环里最近的一张", tmp_path, monkeypatch)

        dumped = (tmp_path / "m1_dump" / "find_jobs_snapshot.txt").read_text(encoding="utf-8")
        assert dumped == "这是 agent 循环里最近的一张"

    def test_failed_step_carries_the_file_name(self, tmp_path, monkeypatch):
        """前端靠事件 detail 里的文件名拼下载链接——跟 applyFailScreenshot 一个路子。"""
        logger = DumpLogger()
        self._run(logger, lambda: "快照", tmp_path, monkeypatch)

        failed = logger.steps[-1]
        assert failed["status"] == "failed"
        assert failed["data"]["snapshot_file"] == "find_jobs_snapshot.txt"

    def test_no_provider_means_no_dump(self, tmp_path, monkeypatch):
        """命令行 --direct 没有 provider，不该因此报错。"""
        logger = DumpLogger()
        self._run(logger, None, tmp_path, monkeypatch)
        assert not (tmp_path / "m1_dump").exists()
