# m1/m2 三层可视化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 m1/m2 的 LangGraph 节点进度和 ReAct 内层循环（agent 每一轮说了什么、调了什么、看到什么）在 Dashboard 上可见，实时与事后回放一致。

**Architecture:** `agent_runtime.run_agent` 的 `astream` 循环已经逐条拿到 agent 消息，现在只 print 掉。抽一个纯函数 `describe_message` 把消息解读成结构化记录，stdout 与 run 日志共用它；新增 `agent_step` 事件类型走现有 RunLogger（JSONL + SSE）双写，实时与回放共用一个格式化函数 `agent_event`；前端为 m1/m2 单独渲染三层视图，W1/W2/W3 渲染路径一行不碰。

**Tech Stack:** Python 3.11+ / LangGraph / FastAPI + SSE / React 18 + Vite / pytest / vitest

**Spec:** `docs/superpowers/specs/2026-08-17-m1-m2-visualization-design.md`

## Global Constraints

- 在 `code/` 目录下执行所有命令。测试 `python -m pytest`，前端 `cd dashboard/frontend && npm run build`（build 会先跑 vitest）。
- **TDD 铁律**：没有先失败的测试就不写生产代码。每个 Task 的 Step 1 是写测试、Step 2 是看它失败。
- **JS/HTML/TSX 里的 CJK 一律 `\uXXXX` escape**（会被渲染的字符串字面量；`//` 注释可以裸中文）。`.py` / `.md` 不需要。
- **不要用 Edit 工具直接写 `\uXXXX`**（会被 JSON 解码回中文）——写 TSX 的中文字面量时用脚本文件转 ASCII 再落盘，并校验非注释行 `nonascii == 0`。
- Windows 上 Bash 的路径用 `/c/...`；pytest 汇总行在本环境不打印，判断绿看退出码和点号。
- 不引入 async/await 到 W1/W2/W3 侧；不碰 `SKELETON` / `RUN_STEPS` / `LOOP_STEPS` / `buildTree`。
- 内部路径 fail fast，不写防御性 swallow。

---

### Task 1: `describe_message` —— 一份解读，stdout 与日志共用

**Files:**
- Modify: `multisite/agent_runtime.py:124-143`（`_trace`）
- Test: `tests/test_agent_trace.py`（新建）

**Interfaces:**
- Produces: `describe_message(msg: BaseMessage, seq: int) -> dict | None`、`format_record(record: dict) -> list[str]`

- [ ] **Step 1: 写失败的测试**

`code/tests/test_agent_trace.py`：

```python
"""agent 每一轮的解读：stdout 追踪和 run 日志共用同一份。

分成两份的话，"日志里说的"和"终端里说的"会慢慢变成两回事，而那种漂移
没有任何东西会发现。
"""
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from multisite.agent_runtime import describe_message, format_record


class TestDescribeMessage:
    def test_thinking_with_tool_calls(self):
        msg = AIMessage(
            content="列表里看到 20 个岗位，先处理前 5 个",
            tool_calls=[{"id": "call_1", "name": "record_job",
                         "args": {"title": "后端开发实习生"}}],
        )
        assert describe_message(msg, 13) == {
            "kind": "think", "seq": 13,
            "text": "列表里看到 20 个岗位，先处理前 5 个",
            "calls": [{"id": "call_1", "name": "record_job",
                       "args": {"title": "后端开发实习生"}}],
        }

    def test_tool_call_without_text(self):
        msg = AIMessage(content="", tool_calls=[
            {"id": "c", "name": "take_snapshot", "args": {}}])
        out = describe_message(msg, 4)
        assert out["kind"] == "think" and out["text"] == ""
        assert out["calls"][0]["name"] == "take_snapshot"

    def test_long_args_are_truncated(self):
        msg = AIMessage(content="", tool_calls=[
            {"id": "c", "name": "fill", "args": {"value": "x" * 500}}])
        assert len(describe_message(msg, 1)["calls"][0]["args"]["value"]) == 120

    def test_tool_result(self):
        msg = ToolMessage(content='uid=2_0 RootWebArea "招聘"\nuid=2_1 link',
                          tool_call_id="call_1", name="take_snapshot")
        assert describe_message(msg, 14) == {
            "kind": "observe", "seq": 14, "call_id": "call_1",
            "tool": "take_snapshot", "chars": 41,
            "head": 'uid=2_0 RootWebArea "招聘"',
        }

    def test_empty_ai_message_is_dropped(self):
        """既没说话也没调工具的一轮不该占一行。"""
        assert describe_message(AIMessage(content=""), 2) is None

    def test_non_agent_message_is_dropped(self):
        assert describe_message(HumanMessage(content="开始"), 0) is None


class TestFormatRecord:
    def test_think_renders_calls_then_text(self):
        record = {"kind": "think", "seq": 7, "text": "先翻页",
                  "calls": [{"id": "c", "name": "click", "args": {"uid": "2_1"}}]}
        lines = format_record(record)
        assert lines == ["  [07] -> click({'uid': '2_1'})", "  [07] 说: 先翻页"]

    def test_observe_renders_one_line(self):
        record = {"kind": "observe", "seq": 8, "call_id": "c",
                  "tool": "take_snapshot", "chars": 12431, "head": "uid=2_0"}
        assert format_record(record) == ["  [08] <- take_snapshot: 12431 字符 | uid=2_0"]
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `python -m pytest tests/test_agent_trace.py -q --color=no`
Expected: FAIL — `ImportError: cannot import name 'describe_message'`

- [ ] **Step 3: 实现**

在 `multisite/agent_runtime.py` 把 `_trace` 换成下面三段（`_trace` 保留，改为调用它们）：

```python
_ARG_MAX = 120       # 单个工具参数打印/记录的字符上限
_HEAD_MAX = 160      # 工具返回首行的字符上限
_TEXT_MAX = 300      # stdout 上 agent 说的话的字符上限


def describe_message(msg: BaseMessage, seq: int) -> Optional[dict]:
    """一条 agent 消息 → 结构化记录；不值得记的返回 None。

    **AIMessage 的「说」和它要调的工具绑成一条**——它们本来就来自同一条消息，
    拆成两种事件反而要在下游再配对一次。
    """
    if isinstance(msg, AIMessage):
        calls = [
            {"id": c.get("id") or "",
             "name": c.get("name") or "",
             "args": {k: str(v)[:_ARG_MAX] for k, v in (c.get("args") or {}).items()}}
            for c in (msg.tool_calls or [])
        ]
        text = msg.content.strip() if isinstance(msg.content, str) else ""
        if not text and not calls:
            return None
        return {"kind": "think", "seq": seq, "text": text, "calls": calls}
    if isinstance(msg, ToolMessage):
        body = msg.content if isinstance(msg.content, str) else str(msg.content)
        stripped = body.strip()
        return {"kind": "observe", "seq": seq,
                "call_id": msg.tool_call_id or "",
                "tool": msg.name or "",
                "chars": len(body),
                "head": stripped.splitlines()[0][:_HEAD_MAX] if stripped else ""}
    return None


def format_record(record: dict) -> list[str]:
    """结构化记录 → stdout 行。刻意与旧 `_trace` 的输出逐字一致。"""
    seq = record["seq"]
    if record["kind"] == "think":
        lines = [f"  [{seq:02d}] -> {c['name']}({c['args']})" for c in record["calls"]]
        if record["text"]:
            lines.append(f"  [{seq:02d}] 说: {record['text'][:_TEXT_MAX]}")
        return lines
    return [f"  [{seq:02d}] <- {record['tool']}: {record['chars']} 字符 "
            f"| {record['head'] or '(空)'}"]


def _trace(msg: BaseMessage, step: int) -> None:
    """把 agent 的每一步打到 stdout。**不是可选的调试便利，是这条路线的必需品**：
    agent 自主导航失败时的现象是"跑了很久然后报错"，异常本身完全不说明它在哪兜圈子。"""
    record = describe_message(msg, step)
    if record is None:
        return
    for line in format_record(record):
        safe_print(line, flush=True)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_agent_trace.py -q --color=no`
Expected: 全部通过（8 个）

- [ ] **Step 5: 变异验证**

把 `if not text and not calls: return None` 删掉 → `test_empty_ai_message_is_dropped` 必须变红。恢复。

- [ ] **Step 6: Commit**

```bash
git add code/multisite/agent_runtime.py code/tests/test_agent_trace.py
git commit -m "refactor(multisite): agent 每一轮的解读抽成纯函数，stdout 与日志共用"
```

---

### Task 2: `run_agent` 的 `on_step` 回调

**Files:**
- Modify: `multisite/agent_runtime.py`（`run_agent`）
- Test: `tests/test_agent_trace.py`（追加）

**Interfaces:**
- Consumes: Task 1 的 `describe_message` / `format_record`
- Produces: `run_agent(agent, user_message, max_steps=MAX_STEPS, trace=True, on_step=None) -> dict`；`on_step(record: dict) -> None` 对每条**新出现**的消息调用一次

- [ ] **Step 1: 写失败的测试**

追加到 `code/tests/test_agent_trace.py`：

```python
import asyncio

from langchain_core.messages import AIMessage, ToolMessage

from multisite.agent_runtime import run_agent


class FakeAgent:
    """按 stream_mode="values" 的形状吐 chunk：每个 chunk 是完整的 messages 快照，
    后一个包含前一个（这正是 run_agent 只处理新增部分的原因）。"""

    def __init__(self, batches):
        self._batches = batches

    async def astream(self, payload, config=None, stream_mode=None):
        for msgs in self._batches:
            yield {"messages": msgs}


class TestRunAgentOnStep:
    def _run(self, agent, **kw):
        return asyncio.run(run_agent(agent, "go", trace=False, **kw))

    def test_calls_on_step_once_per_new_message(self):
        a = AIMessage(content="", tool_calls=[{"id": "c1", "name": "take_snapshot", "args": {}}])
        t = ToolMessage(content="uid=1", tool_call_id="c1", name="take_snapshot")
        b = AIMessage(content="找到了", tool_calls=[])
        seen = []
        self._run(FakeAgent([[a], [a, t], [a, t, b]]), on_step=seen.append)

        assert [r["kind"] for r in seen] == ["think", "observe", "think"]
        assert [r["seq"] for r in seen] == [0, 1, 2]

    def test_returns_the_final_state(self):
        b = AIMessage(content="done", tool_calls=[])
        final = self._run(FakeAgent([[b]]), on_step=lambda r: None)
        assert final["messages"][-1].content == "done"

    def test_dropped_messages_do_not_reach_on_step_but_still_advance_seq(self):
        """空消息不占一行，但序号必须继续走——否则序号跟消息下标对不上。"""
        empty = AIMessage(content="")
        b = AIMessage(content="真正说了话", tool_calls=[])
        seen = []
        self._run(FakeAgent([[empty], [empty, b]]), on_step=seen.append)

        assert len(seen) == 1
        assert seen[0]["seq"] == 1
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `python -m pytest tests/test_agent_trace.py -k OnStep -q --color=no`
Expected: FAIL — `run_agent() got an unexpected keyword argument 'on_step'`

- [ ] **Step 3: 实现**

`multisite/agent_runtime.py` 的 `run_agent` 改成：

```python
async def run_agent(agent, user_message: str, max_steps: int = MAX_STEPS,
                    trace: bool = True, on_step=None) -> dict:
    """跑一次 agent 循环并返回最终 state。

    `on_step(record)` 对每条**新出现**且值得记的消息调用一次（record 形状见
    `describe_message`）。它和 `trace` 互不影响：命令行直跑只要 stdout，
    Dashboard 触发的那次两个都要。

    `recursion_limit` 是 LangGraph 对图 superstep 数的硬上限，而**一次模型轮次是
    三跳不是两跳**：`pre_model_hook → agent → tools`。所以乘 3。

    真正先触发的**不是**这个硬上限，而是 `create_react_agent` 内建的软着陆
    （见 `_STEP_LIMIT_SENTINEL`），判断"跑完没跑完"必须用 `hit_step_limit()`。
    """
    config = {"recursion_limit": max_steps * 3 + 4}
    payload = {"messages": [{"role": "user", "content": user_message}]}
    if not trace and on_step is None:
        return await agent.ainvoke(payload, config=config)

    final: dict = {}
    step = 0
    async for chunk in agent.astream(payload, config=config, stream_mode="values"):
        final = chunk
        msgs = chunk.get("messages") or []
        # 只处理新出现的那些，避免每轮把整段历史重放一遍。
        while step < len(msgs):
            record = describe_message(msgs[step], step)
            if record is not None:
                if trace:
                    for line in format_record(record):
                        safe_print(line, flush=True)
                if on_step is not None:
                    on_step(record)
            step += 1
    if hit_step_limit(final):
        # 大声说出来。这条路径是"没干完"，不是"干完了"，而两者的返回值一模一样。
        safe_print(f"  [!!] agent 步数耗尽（MAX_STEPS={max_steps}），任务未完成就返回了。"
                   f"结果是部分的。", flush=True)
    return final
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_agent_trace.py -q --color=no`
Expected: 全部通过

- [ ] **Step 5: 变异验证**

把 `step += 1` 挪进 `if record is not None:` 里 → `test_dropped_messages_do_not_reach_on_step_but_still_advance_seq` 必须变红。恢复。

- [ ] **Step 6: Commit**

```bash
git add code/multisite/agent_runtime.py code/tests/test_agent_trace.py
git commit -m "feat(multisite): run_agent 支持 on_step 回调，agent 每一轮可被外部记录"
```

---

### Task 3: `agent_step` 事件 —— ProgressEvent 加 `seq`，SSE 序列化收敛

**Files:**
- Modify: `services/progress_emitter.py`（`ProgressEvent` 加字段 + 新增 `event_to_dict`）
- Modify: `dashboard/server.py:2159-2171`（SSE 改用 `event_to_dict`）
- Modify: `pipeline/run_logger.py`（新增 `agent_event` + `log_agent_step`）
- Modify: `services/run_logger.py`（新增 `log_agent_step`）
- Test: `tests/test_agent_events.py`（新建）

**Interfaces:**
- Consumes: Task 1 的 record 形状
- Produces:
  - `services.progress_emitter.event_to_dict(event: ProgressEvent) -> dict`
  - `pipeline.run_logger.agent_event(pipeline: str, step: str, record: dict, ts: float) -> dict`
  - `pipeline.run_logger.RunLogger.log_agent_step(step: str, record: dict) -> None`
  - `services.run_logger.RunLogger.log_agent_step(step: str, record: dict) -> None`

- [ ] **Step 1: 写失败的测试**

`code/tests/test_agent_events.py`：

```python
"""agent_step 事件：JSONL 落盘 + SSE 推送，两者形状由同一个函数产出。"""
import json

from pipeline.run_logger import RunLogger, agent_event
from services.progress_emitter import ProgressEvent, event_to_dict

THINK = {"kind": "think", "seq": 13, "text": "先翻页",
         "calls": [{"id": "c1", "name": "click", "args": {"uid": "2_1"}}]}
OBSERVE = {"kind": "observe", "seq": 14, "call_id": "c1",
           "tool": "take_snapshot", "chars": 12431, "head": "uid=2_0 RootWebArea"}


class FakeEmitter:
    def __init__(self):
        self.events = []
        self.stop_requested = False

    def emit(self, event):
        self.events.append(event)


class TestEventToDict:
    def test_carries_every_field_including_seq(self):
        """SSE 的序列化原本在 server.py 里逐个字段手写——加一个字段就要记得
        改那里，忘了的表现是前端永远收不到它、而且不报错。收敛成一个函数。"""
        ev = ProgressEvent(workflow="m1", step="find_jobs", status="info",
                           message="x", tool=None, scope={}, detail={"a": 1},
                           seq=13, ts=1.0)
        assert event_to_dict(ev) == {
            "workflow": "m1", "step": "find_jobs", "tool": None, "status": "info",
            "message": "x", "scope": {}, "detail": {"a": 1}, "seq": 13, "ts": 1.0,
        }

    def test_seq_is_none_for_ordinary_events(self):
        ev = ProgressEvent(workflow="w1", step="scan", status="done", message="m")
        assert event_to_dict(ev)["seq"] is None


class TestAgentEvent:
    def test_think_event_shape(self):
        out = agent_event("m1", "find_jobs", THINK, ts=1.5)
        assert out["workflow"] == "m1" and out["step"] == "find_jobs"
        assert out["seq"] == 13 and out["status"] == "info"
        assert out["tool"] is None            # 「说」不是工具调用
        assert out["detail"] == THINK          # 完整 record 原样带上
        assert out["ts"] == 1.5

    def test_observe_event_carries_the_tool_name(self):
        out = agent_event("m1", "find_jobs", OBSERVE, ts=2.0)
        assert out["tool"] == "take_snapshot"
        assert out["detail"] == OBSERVE


class TestLogAgentStep:
    def test_writes_one_jsonl_line_with_the_record_nested(self, tmp_path, monkeypatch):
        import services.run_logger as srl
        monkeypatch.setattr(srl, "RUNS_DIR", tmp_path)
        logger = RunLogger(pipeline="m1", run_id="m1_test", debug=True)
        logger.log_agent_step("find_jobs", THINK)
        logger.close("done")

        lines = [json.loads(x) for x in (tmp_path / "m1_test.jsonl").read_text(
            encoding="utf-8").splitlines() if x.strip()]
        rec = next(x for x in lines if x["event"] == "agent_step")
        assert rec["step"] == "find_jobs"
        assert rec["record"] == THINK      # 整体嵌一层，不摊平

    def test_emits_sse_when_debug(self, tmp_path, monkeypatch):
        import services.run_logger as srl
        monkeypatch.setattr(srl, "RUNS_DIR", tmp_path)
        emitter = FakeEmitter()
        logger = RunLogger(pipeline="m1", run_id="m1_test2", emitter=emitter, debug=True)
        logger.log_agent_step("find_jobs", THINK)

        sent = [e for e in emitter.events if e.seq is not None]
        assert len(sent) == 1
        assert sent[0].workflow == "m1" and sent[0].detail == THINK
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `python -m pytest tests/test_agent_events.py -q --color=no`
Expected: FAIL — `cannot import name 'event_to_dict'`

- [ ] **Step 3: 实现（四个文件）**

`services/progress_emitter.py` —— `ProgressEvent` 末尾加字段，并新增序列化函数：

```python
@dataclass
class ProgressEvent:
    ...
    ts: float = field(default_factory=time.time)
    # seq: agent 内层循环的轮次序号。非 None = 这是一条 agent 步事件（m1/m2 专有）。
    # 普通 step/tool 事件没有序号概念，留 None。
    seq: Optional[int] = None


def event_to_dict(event: ProgressEvent) -> dict:
    """ProgressEvent → SSE / 回放共用的线上形状。

    **别改成 dataclasses.asdict 之外的手写枚举**：这个函数存在的理由就是
    server.py 原来在 SSE 生成器里逐字段手写，加一个字段要记得改那里，
    忘了的表现是前端永远收不到它、而且不报错。
    """
    return {
        "workflow": event.workflow,
        "step": event.step,
        "tool": event.tool,
        "status": event.status,
        "message": event.message,
        "scope": event.scope,
        "detail": event.detail,
        "seq": event.seq,
        "ts": event.ts,
    }
```

`dashboard/server.py` SSE 生成器（约 2159-2171 行）里那个手写 dict 换成：

```python
                    event: ProgressEvent = q.get_nowait()
                    yield {
                        "data": json.dumps(event_to_dict(event), ensure_ascii=False),
                    }
```

（`from services.progress_emitter import ProgressEmitter, ProgressEvent, event_to_dict`）

`services/run_logger.py` 新增：

```python
    def log_agent_step(self, step: str, record: dict) -> None:
        """agent 内层循环的一轮。`record` 整体嵌一层，不摊平到顶层——回放时要
        原样取回来，摊平就得靠"排除信封字段"来重建，加一个信封字段就会悄悄污染它。"""
        self._write({
            "event": "agent_step",
            "run_id": self._run_id,
            "step": step,
            "record": record,
            "ts": _now_iso(),
        })
```

`pipeline/run_logger.py` 新增（放在 `_ui_status` 下面）：

```python
def agent_event(pipeline: str, step: str, record: dict, ts: float) -> dict:
    """一条 agent 记录 → 前端 ProgressEvent 形状。

    **实时 SSE 和事后回放共用这一份**。两边各写一套的表现是"实时看着好好的、
    翻历史就少一半"，而那种不一致没有任何东西会报错。
    `services/run_log_reader.py` 也导入它（方向与 `_ui_status` 一致，反过来是循环导入）。
    """
    if record.get("kind") == "think":
        names = ", ".join(c.get("name", "") for c in (record.get("calls") or []))
        text = (record.get("text") or "")[:120]
        message = " ".join(x for x in (f"说: {text}" if text else "",
                                       f"-> {names}" if names else "") if x)
        tool = None
    else:
        message = f"{record.get('tool', '')}: {record.get('chars', 0)} 字符"
        tool = record.get("tool") or None
    return {"workflow": pipeline, "step": step, "tool": tool, "status": "info",
            "message": message, "scope": {}, "detail": record,
            "seq": record.get("seq"), "ts": ts}
```

以及 `pipeline/run_logger.RunLogger` 的方法：

```python
    def log_agent_step(self, step: str, record: dict) -> None:
        """JSONL 无条件写；SSE 只在 debug 时推（与 log_tool 一致）。"""
        self._inner.log_agent_step(step=step, record=record)
        if self._emitter is not None and self._debug:
            try:
                from services.progress_emitter import ProgressEvent
                payload = agent_event(self._pipeline, step, record, time.time())
                self._emitter.emit(ProgressEvent(**payload))
            except Exception:
                pass
```

（`pipeline/run_logger.py` 顶部加 `import time`）

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_agent_events.py -q --color=no`
Expected: 全部通过

- [ ] **Step 5: 跑全量，确认 SSE 序列化收敛没打断别的**

Run: `python -m pytest -q --color=no`；再 `cd dashboard/frontend && npm run build`
Expected: 退出码 0

- [ ] **Step 6: Commit**

```bash
git add code/services/progress_emitter.py code/services/run_logger.py \
        code/pipeline/run_logger.py code/dashboard/server.py code/tests/test_agent_events.py
git commit -m "feat(multisite): 新增 agent_step 事件，SSE 序列化收敛成一个函数"
```

---

### Task 4: 回放认识 `agent_step`，且与实时逐字段相同

**Files:**
- Modify: `services/run_log_reader.py:173-220`（`parse_run_events`）
- Test: `tests/test_agent_events.py`（追加）

**Interfaces:**
- Consumes: Task 3 的 `agent_event`、`event_to_dict`
- Produces: `parse_run_events` 对 `agent_step` 行产出与 SSE **完全相同**的 dict（`ts` 除外，一个是 epoch 转换、一个是发生时刻）

- [ ] **Step 1: 写失败的测试**

追加到 `code/tests/test_agent_events.py`：

```python
from services.progress_emitter import event_to_dict
from services.run_log_reader import parse_run_events


class TestReplayMatchesLive:
    """同一条 record 有两条路到达同一个前端组件：实时 SSE 和事后回放。
    两边各写一套格式化必然分叉，所以这里直接把两条路的产出摆在一起比。"""

    def test_replay_and_sse_produce_the_same_event(self, tmp_path, monkeypatch):
        import services.run_logger as srl
        monkeypatch.setattr(srl, "RUNS_DIR", tmp_path)
        emitter = FakeEmitter()
        logger = RunLogger(pipeline="m1", run_id="m1_same", emitter=emitter, debug=True)
        logger.log_agent_step("find_jobs", THINK)
        logger.close("done")

        live = event_to_dict(next(e for e in emitter.events if e.seq is not None))
        replayed = next(e for e in parse_run_events(tmp_path / "m1_same.jsonl")
                        if e.get("seq") is not None)

        assert {**live, "ts": 0} == {**replayed, "ts": 0}

    def test_observe_events_replay_too(self, tmp_path, monkeypatch):
        import services.run_logger as srl
        monkeypatch.setattr(srl, "RUNS_DIR", tmp_path)
        logger = RunLogger(pipeline="m1", run_id="m1_obs", debug=True)
        logger.log_agent_step("find_jobs", OBSERVE)
        logger.close("done")

        got = next(e for e in parse_run_events(tmp_path / "m1_obs.jsonl")
                   if e.get("seq") is not None)
        assert got["tool"] == "take_snapshot" and got["detail"] == OBSERVE
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `python -m pytest tests/test_agent_events.py -k Replay -q --color=no`
Expected: FAIL — `StopIteration`（回放里根本没有 seq 事件）

- [ ] **Step 3: 实现**

`services/run_log_reader.py` 顶部导入改成：

```python
from pipeline.run_logger import _ui_status, agent_event
```

在 `parse_run_events` 的 `elif event == "tool":` 之后加一支：

```python
        elif event == "agent_step":
            # agent 内层循环。格式化跟实时 SSE 共用 agent_event()——两边各写一套的
            # 表现是"实时看着好好的、翻历史就少一半"，而那不会报错。
            out.append(agent_event(pipeline, e.get("step", ""), e.get("record") or {}, ts))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_agent_events.py -q --color=no`
Expected: 全部通过

- [ ] **Step 5: 变异验证**

把新分支里的 `agent_event(...)` 换成手写 dict 且漏掉 `"seq"` → `test_replay_and_sse_produce_the_same_event` 必须变红。恢复。

- [ ] **Step 6: Commit**

```bash
git add code/services/run_log_reader.py code/tests/test_agent_events.py
git commit -m "feat(multisite): 回放认识 agent_step，与实时 SSE 共用一份格式化"
```

---

### Task 5: 第 2 层骨架 —— `stage_names()` + 不许漂移 + 端点

**Files:**
- Modify: `multisite/layer1_agent.py`（模块级加 `STAGE_ORDER` / `stage_names`；`build_graph` 里加对账）
- Modify: `dashboard/server.py`（新端点）
- Test: `tests/test_multisite_stages.py`（新建）

**Interfaces:**
- Produces: `multisite.layer1_agent.stage_names(select_only: bool) -> tuple[str, ...]`；`GET /api/multisite/stages`

- [ ] **Step 1: 写失败的测试**

`code/tests/test_multisite_stages.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `python -m pytest tests/test_multisite_stages.py -q --color=no`
Expected: FAIL — `cannot import name 'STAGE_ORDER'`

- [ ] **Step 3: 实现**

`multisite/layer1_agent.py` 模块级（放在 `_PASSTHROUGH_OPEN_APPLICATION` 附近）：

```python
# 图节点的名字与顺序。**第二个消费方是前端第 2 层骨架**（经 /api/multisite/stages），
# 所以它不能只活在 build_graph 的局部变量里。真正的函数与 summarizer 仍在
# build_graph 的 stages 表里，两者由建图时的对账保证不漂移。
STAGE_ORDER = ("ensure_ready", "find_jobs", "write_pending_jobs",
               "open_application", "scan_and_classify_fields", "write_pending_application")


def stage_names(select_only: bool) -> tuple[str, ...]:
    """这次 run 会经过哪些图节点。select_only=True 只跑到 Checkpoint 1。"""
    return STAGE_ORDER[:3] if select_only else STAGE_ORDER
```

`build_graph` 里，在 `graph = StateGraph(Layer1State)` **之前**插入对账：

```python
    # 名字漂移在运行时表现为"骨架上有一站永远不亮"，跟"卡住了"一模一样、测不出来，
    # 所以在这里当场炸掉。这个分支在正确的构建里永远不可能进。
    built = tuple(name for name, _, _ in stages)
    if built != stage_names(select_only):
        raise RuntimeError(f"阶段表与 stage_names() 不一致：{built} vs {stage_names(select_only)}")
```

`dashboard/server.py` 新端点（放在 `/api/runs/...` 那一组附近）：

```python
@app.get("/api/multisite/stages")
async def get_multisite_stages() -> JSONResponse:
    """m1/m2 的 LangGraph 节点顺序——前端第 2 层「地铁站」的骨架。

    **从图定义导出，不手维护**：W1/W2 的 SKELETON 是手抄的静态模板，已经漂移过
    （见 PITFALLS.md）。m1 = 队列里的 select_only 路径（只跑到 Checkpoint 1）。
    """
    from multisite.layer1_agent import stage_names
    return JSONResponse({"m1": list(stage_names(True)), "m2": list(stage_names(False))})
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_multisite_stages.py -q --color=no`
Expected: 全部通过

- [ ] **Step 5: 手工验一次端点**

Run: `curl -s http://localhost:8765/api/multisite/stages`（后端要先重启）
Expected: `{"m1":["ensure_ready","find_jobs","write_pending_jobs"],"m2":[... 6 个 ...]}`

- [ ] **Step 6: Commit**

```bash
git add code/multisite/layer1_agent.py code/dashboard/server.py code/tests/test_multisite_stages.py
git commit -m "feat(multisite): 第 2 层骨架从图定义导出，建图时对账防漂移"
```

---

### Task 6: 接线 —— agent 的每一轮真的写进 run 日志

**Files:**
- Modify: `multisite/observability.py`（新增 `agent_step_sink`）
- Modify: `multisite/layer1_agent.py:1094-1097` 与 `:1152-1153`（两处 `run_agent` 调用）
- Test: `tests/test_multisite_observability.py`（追加）

**Interfaces:**
- Consumes: Task 2 的 `on_step`、Task 3 的 `log_agent_step`
- Produces: `multisite.observability.agent_step_sink(logger, step: str)`（logger 为 None 时返回 None）

- [ ] **Step 1: 写失败的测试**

追加到 `code/tests/test_multisite_observability.py`：

```python
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
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `python -m pytest tests/test_multisite_observability.py -k AgentStepSink -q --color=no`
Expected: FAIL — `cannot import name 'agent_step_sink'`

- [ ] **Step 3: 实现**

`multisite/observability.py` 追加：

```python
def agent_step_sink(logger, step: str):
    """给 `run_agent(on_step=...)` 用的回调：把 agent 每一轮记到这个阶段名下。

    `logger` 为 None（命令行 `--direct` 路径）时返回 None——让 run_agent 保持
    原来的行为，而不是塞一个什么都不做的函数进去。
    """
    if logger is None:
        return None
    return lambda record: logger.log_agent_step(step, record)
```

`multisite/layer1_agent.py` 两处调用改成（`find_jobs` 节点内）：

```python
            result = await agent_runtime.run_agent(
                agent, f"入口页面：{state['search_url']}\n请开始。",
                on_step=agent_step_sink(logger, "find_jobs"))
```

以及（`open_application` 节点内）：

```python
        result = await agent_runtime.run_agent(
            agent, f"岗位详情页：{job.url}\n请开始。",
            on_step=agent_step_sink(logger, "open_application"))
```

顶部导入补 `agent_step_sink`：

```python
from multisite.observability import agent_step_sink, run_scope, traced_stage
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_multisite_observability.py -q --color=no`
Expected: 全部通过

- [ ] **Step 5: 跑全量**

Run: `python -m pytest -q --color=no`
Expected: 退出码 0

- [ ] **Step 6: Commit**

```bash
git add code/multisite/observability.py code/multisite/layer1_agent.py \
        code/tests/test_multisite_observability.py
git commit -m "feat(multisite): agent 每一轮接进 run 日志，按 LangGraph 阶段分组"
```

---

### Task 7: 失败快照落进 `logs/runs/{run_id}/`

**Files:**
- Modify: `services/run_logger.py`（新增 `run_artifacts_dir`）
- Modify: `multisite/layer1_agent.py`（`_dump_debug_snapshot` 接目标目录；`add_node` 那行传 provider）
- Modify: `multisite/observability.py`（`traced_stage` 加 `snapshot_provider`）
- Test: `tests/test_multisite_observability.py`（追加）

> 行号一律**按符号名定位**，不要按计划里写的行号找——Task 5 会在 `layer1_agent.py`
> 模块级插入常量，之后的行号全体下移。

**Interfaces:**
- Consumes: Task 6 的 logger
- Produces:
  - `services.run_logger.run_artifacts_dir(run_id: str, runs_dir: Path | None = None) -> Path`
    （**写入、读取端点、清理三处共用这一个函数**，Task 8 也要用）
  - `traced_stage(name, fn, logger, summarize=None, snapshot_provider=None)`；失败时写
    `logs/runs/{run_id}/{stage}_snapshot.txt`，并把文件名放进失败 step 的 `data["snapshot_file"]`

- [ ] **Step 1: 写失败的测试**

追加到 `code/tests/test_multisite_observability.py`：

```python
import asyncio

import pytest

from multisite.observability import traced_stage


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
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `python -m pytest tests/test_multisite_observability.py -k FailureSnapshot -q --color=no`
Expected: FAIL — `traced_stage() got an unexpected keyword argument 'snapshot_provider'`

- [ ] **Step 3: 实现**

`multisite/layer1_agent.py` 的 `_dump_debug_snapshot` 改成接收目标目录：

```python
def _dump_debug_snapshot(tag: str, snapshot_text: str, target_dir: Optional[Path] = None) -> None:
    """调试用：某个定位失败时把当时的原始 a11y 快照存下来，省得只能靠报错
    字符串猜页面长什么样——上一次真机排查就是因为没有这个才多跑了一轮。

    `target_dir` 不给就落回老位置 `data/multisite_debug/`（图之外的调用点还在用它）。
    run 里的失败走 `logs/runs/{run_id}/`：那是 run 证据，跟 run 同生死、整目录删得干净
    （见 spec §7.5）。
    """
    dest = Path(target_dir) if target_dir is not None else _DEBUG_DIR
    dest.mkdir(parents=True, exist_ok=True)
    (dest / f"{tag}.txt").write_text(snapshot_text, encoding="utf-8")
```

`services/run_logger.py` 新增（**放这里而不是 observability**：`RUNS_DIR` 就在这个模块，
而且下一个 Task 的读取端点和 `artifact_cleanup` 也要用它——三处各写一份 `runs_dir / run_id`
就是同一个契约三份实现）：

```python
def run_artifacts_dir(run_id: str, runs_dir: Optional[Path] = None) -> Path:
    """一次 run 的产物目录，与 `{run_id}.jsonl` 平级。

    `run_log_reader.iter_run_files` glob 的是 `*.jsonl`，不会把这个目录当成 run，
    所以放在这里不破坏任何现有代码。写入、读取端点、清理三处**都用这一个函数**。
    """
    return (runs_dir if runs_dir is not None else RUNS_DIR) / run_id
```

`multisite/observability.py` 的 `traced_stage`：

```python
from services.run_logger import run_artifacts_dir


def traced_stage(name, fn, logger, summarize=None, snapshot_provider=None):
    """包一层，让这个阶段跑完在 run 日志里留下一条记录。

    `summarize(out) -> dict` **跟着阶段走**，不由这里认识每个阶段的输出形状。

    `snapshot_provider() -> str` 失败时用来取"当时最近一张"完整 a11y 快照。
    **不能改用 `state["snapshot_text"]`**：它只在阶段成功返回时才写回，阶段失败时
    装的是上一个阶段的快照——正好在最需要它的时候是错的。
    """

    async def wrapped(state):
        started = time.monotonic()
        try:
            out = await fn(state)
        except Exception as exc:
            data = {}
            if snapshot_provider is not None:
                from multisite.layer1_agent import _dump_debug_snapshot
                tag = f"{name}_snapshot"
                _dump_debug_snapshot(tag, snapshot_provider() or "",
                                     target_dir=run_artifacts_dir(logger.run_id))
                data["snapshot_file"] = f"{tag}.txt"
            logger.log_step(name, {}, "failed",
                            int((time.monotonic() - started) * 1000),
                            data=data, error=str(exc))
            raise   # 记日志不是处理异常
        logger.log_step(name, {}, "successful", int((time.monotonic() - started) * 1000),
                        data=summarize(out) if summarize else {})
        return out

    return wrapped
```

> `_dump_debug_snapshot` 在函数体里 import：`layer1_agent` 已经 import 了 `observability`，
> 顶层反向 import 会成环。

`multisite/layer1_agent.py` 的 `add_node` 那行改成传 provider：

```python
    for name, fn, summarize in stages:
        graph.add_node(name, traced_stage(name, fn, logger, summarize,
                                          snapshot_provider=lambda: _latest_snapshot["text"])
                       if logger else fn)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_multisite_observability.py -q --color=no`
Expected: 全部通过

- [ ] **Step 5: 变异验证**

把 `snapshot_provider()` 换成 `state.get("snapshot_text", "")` → `test_dumps_the_providers_snapshot_not_the_state_one` 必须变红。恢复。

- [ ] **Step 6: Commit**

```bash
git add code/multisite/layer1_agent.py code/multisite/observability.py \
        code/tests/test_multisite_observability.py
git commit -m "feat(multisite): 阶段失败时把当时最近一张快照存进 logs/runs/{run_id}/"
```

---

### Task 8: artifacts 读取端点 + 删 run 连目录一起删

**Files:**
- Modify: `dashboard/server.py`（新端点，放在 `/api/runs/{run_id}/events` 之后）
- Modify: `services/artifact_cleanup.py`（`delete_run_log`）
- Test: `tests/test_run_artifacts.py`（新建）

**Interfaces:**
- Consumes: Task 7 写出的 `logs/runs/{run_id}/{tag}.txt`
- Produces: `GET /api/runs/{run_id}/artifacts/{name}`

- [ ] **Step 1: 写失败的测试**

`code/tests/test_run_artifacts.py`：

```python
"""run 产物的读取端点。

照抄现有两个文件端点（/api/apply-failure/{name}、/api/pending-applications/screenshot/{name}）
的约定：bare filename + 固定 base dir + 拒绝路径穿越 + FileResponse。

**多一处**：那两个端点的 base dir 是常量，只有 {name} 来自用户；这里多一段 {run_id}
也参与定位目录。解法是不拼——用 find_run_file（glob + 比对 run_start 的字段，
从不把用户输入拼进路径）拿到 jsonl，再取同名目录。
"""
import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    import dashboard.server as server
    runs = tmp_path / "runs"
    (runs / "m1_art").mkdir(parents=True)
    (runs / "m1_art.jsonl").write_text(
        json.dumps({"event": "run_start", "run_id": "m1_art", "pipeline": "m1"}) + "\n",
        encoding="utf-8")
    (runs / "m1_art" / "find_jobs_snapshot.txt").write_text(
        'uid=2_0 RootWebArea "招聘"', encoding="utf-8")
    monkeypatch.setattr(server, "RUNS_DIR", runs)
    return TestClient(server.app)


class TestArtifactEndpoint:
    def test_serves_a_snapshot_as_plain_text(self, client):
        r = client.get("/api/runs/m1_art/artifacts/find_jobs_snapshot.txt")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/plain")
        assert "RootWebArea" in r.text

    def test_unknown_run_is_404(self, client):
        assert client.get("/api/runs/nope/artifacts/x.txt").status_code == 404

    def test_missing_file_is_404(self, client):
        assert client.get("/api/runs/m1_art/artifacts/absent.txt").status_code == 404

    @pytest.mark.parametrize("name", ["../m1_art.jsonl", "a/b.txt", "a\\b.txt"])
    def test_path_traversal_is_rejected(self, client, name):
        assert client.get(f"/api/runs/m1_art/artifacts/{name}").status_code in (400, 404)

    def test_unknown_extension_is_rejected(self, client):
        assert client.get("/api/runs/m1_art/artifacts/x.exe").status_code == 400


class TestDeleteRunTakesTheDirectory:
    def test_deleting_a_run_log_removes_its_artifacts_dir(self, tmp_path):
        """两处分别删就会留孤儿，而这些文件装的是真实公司/HR 的 PII
        （/api/ops/artifacts 的注释自己写着没有自动清理）。"""
        from services import artifact_cleanup

        runs = tmp_path / "runs"
        (runs / "m1_del").mkdir(parents=True)
        (runs / "m1_del.jsonl").write_text("{}\n", encoding="utf-8")
        (runs / "m1_del" / "snap.txt").write_text("x", encoding="utf-8")

        assert artifact_cleanup.delete_run_log(runs, "m1_del.jsonl") is True
        assert not (runs / "m1_del.jsonl").exists()
        assert not (runs / "m1_del").exists()
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `python -m pytest tests/test_run_artifacts.py -q --color=no`
Expected: FAIL — 端点 404（未注册）、目录仍在

- [ ] **Step 3: 实现**

`dashboard/server.py`，紧跟 `/api/runs/{run_id}/events` 之后：

```python
_ARTIFACT_MEDIA = {".txt": "text/plain; charset=utf-8", ".png": "image/png"}


@app.get("/api/runs/{run_id}/artifacts/{name}")
async def get_run_artifact(run_id: str, name: str):
    """一次 run 的产物（失败时的 a11y 快照全文等）。

    照现有文件端点的约定：bare filename + 拒绝路径穿越 + FileResponse。
    **但那两个端点的 base dir 是常量、只有 name 来自用户**，这里多一段 run_id：
    所以不拼路径——用 find_run_file（glob + 比对 run_start 的 run_id 字段）拿到
    jsonl，再取同名目录，穿越在结构上不可能。
    """
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(status_code=400, detail="非法文件名")
    media = _ARTIFACT_MEDIA.get(Path(name).suffix)
    if media is None:
        raise HTTPException(status_code=400, detail="不支持的文件类型")
    run_path = run_log_reader.find_run_file(RUNS_DIR, run_id)
    if run_path is None:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    # 用**扫出来的那个文件的 stem**，不是用户传进来的 run_id；目录的拼法只有
    # run_artifacts_dir 一份实现（写入、读取、清理三处共用）。
    path = run_artifacts_dir(run_path.stem, RUNS_DIR) / name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="产物不存在")
    return FileResponse(str(path), media_type=media)
```

（`dashboard/server.py` 顶部补 `from pathlib import Path` 与
`from services.run_logger import run_artifacts_dir`，已有就跳过）

`services/artifact_cleanup.py` 的 `delete_run_log`：

```python
def delete_run_log(runs_dir: Path, filename: str) -> bool:
    """删 run 日志时**连它的产物目录一起删**。

    分两处删就会留孤儿，而这些文件装的是真实公司/HR 的 PII——本模块存在的
    理由就是"手动 review 然后删干净"，留一半等于没删。
    """
    import shutil

    from services.run_logger import run_artifacts_dir

    ok = _safe_delete(runs_dir, filename, ".jsonl")
    if ok:
        artifacts = run_artifacts_dir(Path(filename).stem, runs_dir)
        if artifacts.is_dir():
            shutil.rmtree(artifacts, ignore_errors=True)
    return ok
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_run_artifacts.py -q --color=no`
Expected: 全部通过

- [ ] **Step 5: 跑全量**

Run: `python -m pytest -q --color=no`
Expected: 退出码 0

- [ ] **Step 6: Commit**

```bash
git add code/dashboard/server.py code/services/artifact_cleanup.py code/tests/test_run_artifacts.py
git commit -m "feat(multisite): run 产物读取端点 + 删 run 连产物目录一起删"
```

---

### Task 9: 前端纯逻辑 —— 站点状态推导与时间线分组

**Files:**
- Create: `dashboard/frontend/src/components/workflow/multisiteRun.ts`
- Create: `dashboard/frontend/src/components/workflow/multisiteRun.test.ts`
- Modify: `dashboard/frontend/src/hooks/useWorkflowStream.ts`（`ProgressEvent` 加 `seq`）
- Modify: `dashboard/frontend/src/api/index.ts`（`multisiteStages()`）

**Interfaces:**
- Consumes: Task 3/4 的事件形状（`seq != null` = agent 步）、Task 5 的 `/api/multisite/stages`
- Produces:
  - `export type StageStatus = 'pending' | 'running' | 'done' | 'error'`
  - `export function stageStatuses(events, stages): Record<string, StageStatus>`
  - `export function agentRows(events, step): ProgressEvent[]`
  - `API.multisiteStages(): Promise<{ m1: string[]; m2: string[] }>`

- [ ] **Step 1: 写失败的测试**

`dashboard/frontend/src/components/workflow/multisiteRun.test.ts`：

```ts
import { describe, expect, it } from 'vitest'
import type { ProgressEvent } from '@/hooks/useWorkflowStream'
import { agentRows, stageStatuses } from './multisiteRun'

const STAGES = ['ensure_ready', 'find_jobs', 'write_pending_jobs']

function step(name: string, status: string, ts: number): ProgressEvent {
  return { workflow: 'm1', step: name, status, message: '', ts }
}
function agent(name: string, seq: number, tool: string | null, ts: number): ProgressEvent {
  return { workflow: 'm1', step: name, status: 'info', message: '', tool, seq, ts }
}

describe('stageStatuses', () => {
  it('marks an unreached stage as pending', () => {
    expect(stageStatuses([], STAGES).find_jobs).toBe('pending')
  })

  it('marks a stage with agent activity but no terminal event as running', () => {
    const evs = [agent('find_jobs', 0, 'take_snapshot', 1)]
    expect(stageStatuses(evs, STAGES).find_jobs).toBe('running')
  })

  it('marks a stage done on its terminal event', () => {
    const evs = [agent('find_jobs', 0, null, 1), step('find_jobs', 'done', 2)]
    expect(stageStatuses(evs, STAGES).find_jobs).toBe('done')
  })

  it('marks a stage error on failure', () => {
    expect(stageStatuses([step('find_jobs', 'error', 2)], STAGES).find_jobs).toBe('error')
  })
})

describe('agentRows', () => {
  it('keeps every call of the same tool', () => {
    // 这是不能复用现有 buildTree 的原因：它按 tool 名去重，
    // 而 take_snapshot 一次 run 会被调几十次。
    const evs = [
      agent('find_jobs', 0, 'take_snapshot', 1),
      agent('find_jobs', 1, 'take_snapshot', 2),
      agent('find_jobs', 2, 'take_snapshot', 3),
    ]
    expect(agentRows(evs, 'find_jobs')).toHaveLength(3)
  })

  it('only returns rows of the asked stage', () => {
    const evs = [agent('ensure_ready', 0, null, 1), agent('find_jobs', 1, null, 2)]
    expect(agentRows(evs, 'find_jobs').map((e) => e.seq)).toEqual([1])
  })

  it('sorts by seq, not arrival order', () => {
    const evs = [agent('find_jobs', 2, null, 3), agent('find_jobs', 0, null, 1)]
    expect(agentRows(evs, 'find_jobs').map((e) => e.seq)).toEqual([0, 2])
  })

  it('ignores non-agent events', () => {
    expect(agentRows([step('find_jobs', 'done', 1)], 'find_jobs')).toHaveLength(0)
  })
})
```

- [ ] **Step 2: 跑测试确认它失败**

Run: `cd dashboard/frontend && npx vitest run src/components/workflow/multisiteRun.test.ts`
Expected: FAIL — 找不到 `./multisiteRun`

- [ ] **Step 3: 实现**

`useWorkflowStream.ts` 的 `ProgressEvent` 加一个字段：

```ts
export interface ProgressEvent {
  workflow: string
  step: string
  tool?: string | null
  status: string
  message: string
  scope?: Record<string, unknown> | null
  detail?: Record<string, unknown> | null
  ts?: number
  // seq: agent 内层循环的轮次序号。非 null = 这是一条 agent 步事件（m1/m2 专有）。
  seq?: number | null
}
```

`api/index.ts` 加：

```ts
  // m1/m2 第 2 层骨架。从后端图定义导出，不在前端手抄——W1/W2 的 SKELETON
  // 就是手抄的，已经漂移过。
  multisiteStages: (): Promise<{ m1: string[]; m2: string[] }> =>
    requestJson('/api/multisite/stages'),
```

`components/workflow/multisiteRun.ts`：

```ts
import type { ProgressEvent } from '@/hooks/useWorkflowStream'

export type StageStatus = 'pending' | 'running' | 'done' | 'error'

const TERMINAL: Record<string, StageStatus> = {
  done: 'done',
  error: 'error',
  skipped: 'done',
}

// 一个阶段的状态：有终态事件就用它；只有 agent 活动说明正在跑；都没有就是还没走到。
export function stageStatuses(
  events: ProgressEvent[],
  stages: string[],
): Record<string, StageStatus> {
  const out: Record<string, StageStatus> = {}
  for (const s of stages) out[s] = 'pending'
  for (const ev of events) {
    if (!(ev.step in out)) continue
    if (ev.seq != null) {
      if (out[ev.step] === 'pending') out[ev.step] = 'running'
      continue
    }
    const terminal = TERMINAL[ev.status]
    if (terminal) out[ev.step] = terminal
    else if (ev.status === 'running' && out[ev.step] === 'pending') out[ev.step] = 'running'
  }
  return out
}

// 第 3 层：某个阶段里 agent 的每一轮，按 seq 升序，**不去重**。
// 现有 buildTree 按 tool 名存 Map、后来者覆盖，而 take_snapshot 一次 run 调几十次。
export function agentRows(events: ProgressEvent[], step: string): ProgressEvent[] {
  return events
    .filter((e) => e.seq != null && e.step === step)
    .sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0))
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd dashboard/frontend && npx vitest run src/components/workflow/multisiteRun.test.ts`
Expected: 全部通过（9 个）

- [ ] **Step 5: 变异验证**

把 `agentRows` 改成用 `Map` 按 `e.tool` 存 → `keeps every call of the same tool` 必须变红。恢复。

- [ ] **Step 6: Commit**

```bash
git add code/dashboard/frontend/src/components/workflow/multisiteRun.ts \
        code/dashboard/frontend/src/components/workflow/multisiteRun.test.ts \
        code/dashboard/frontend/src/hooks/useWorkflowStream.ts \
        code/dashboard/frontend/src/api/index.ts
git commit -m "feat(dashboard): m1/m2 站点状态与 agent 时间线的纯逻辑 + 测试"
```

---

### Task 10: `MultisiteRunView` 三层组件 + `RunView` 分支

**Files:**
- Create: `dashboard/frontend/src/components/workflow/MultisiteRunView.tsx`
- Modify: `dashboard/frontend/src/components/workflow/WorkflowTrack.tsx`（`RunView` 开头分支）

**Interfaces:**
- Consumes: Task 9 的 `stageStatuses` / `agentRows` / `API.multisiteStages`
- Produces: `export default function MultisiteRunView({ events, workflowId, isRunning })`

- [ ] **Step 1: 写组件**

本任务没有新的纯逻辑（都在 Task 9 里测过了），这里是装配 + 呈现。

**中文字面量必须走脚本转 ASCII 落盘**（见 Global Constraints）：写一个
`$CLAUDE_JOB_DIR/tmp/write_multisite_view.py`，把组件源码放在 Python 字符串里，
对**会被渲染的字符串字面量**做 `"".join(c if ord(c) < 128 else "\\u%04x" % ord(c) for c in s)`，
`//` 注释保持中文，落盘后按 Step 4 校验。

组件骨架（逻辑部分是权威的，样式类名可按现有组件的调性调整）：

```tsx
import { useEffect, useMemo, useRef, useState } from 'react'
import { API } from '@/api'
import type { ProgressEvent } from '@/hooks/useWorkflowStream'
import { agentRows, stageStatuses, type StageStatus } from './multisiteRun'

// 第 1 层：静态全链，只高亮当前段。**不查跨 run 真实状态**——那要先把 layer 之间的
// 状态流转定死，而那是用户明确说"还没想清楚、要单独理"的部分（spec §3）。
// Layer 3 = 提交 + 回站点抓已投递截图，目前还没建，画成虚线。
const PIPELINE: { id: string; label: string; unbuilt?: boolean }[] = [
  { id: 'm1', label: '选岗' },
  { id: 'cp1', label: '审批①' },
  { id: 'm2', label: '填表' },
  { id: 'cp2', label: '审批②' },
  { id: 'l3', label: 'Layer 3', unbuilt: true },
]

const STAGE_DOT: Record<StageStatus, string> = {
  pending: 'bg-text-3/30',
  running: 'bg-signal-blue animate-pulse',
  done: 'bg-signal-green',
  error: 'bg-signal-red',
}

export default function MultisiteRunView({
  events,
  workflowId,
  isRunning = false,
}: {
  events: ProgressEvent[]
  workflowId: string
  isRunning?: boolean
}) {
  const [stages, setStages] = useState<string[]>([])
  const [picked, setPicked] = useState<string | null>(null)

  // 骨架从后端图定义取，不在前端手抄——W1/W2 的 SKELETON 就是手抄的，已经漂移过。
  useEffect(() => {
    let alive = true
    API.multisiteStages().then((r) => {
      if (alive) setStages(workflowId === 'm1' ? r.m1 : r.m2)
    })
    return () => {
      alive = false
    }
  }, [workflowId])

  const statuses = useMemo(() => stageStatuses(events, stages), [events, stages])

  // 默认跟随"最后一个已经开跑的站"；用户点过就固定在他选的那个。
  const latest = useMemo(
    () => [...stages].reverse().find((s) => statuses[s] !== 'pending') ?? stages[0] ?? null,
    [stages, statuses],
  )
  const active = picked && stages.includes(picked) ? picked : latest
  const rows = useMemo(() => (active ? agentRows(events, active) : []), [events, active])

  // 失败那一站的完整快照：文件名来自失败事件的 detail，跟 applyFailScreenshot
  // 从事件 detail 抠文件名是同一个路子。
  const runId = (events.find((e) => e.step === 'start')?.detail?.run_id as string) || ''
  const snapshotFile = active
    ? ((events.find((e) => e.step === active && e.seq == null && e.status === 'error')
        ?.detail?.snapshot_file as string) || '')
    : ''

  // 跟随最新：用户手动上滚后停止跟随（与现有 LiveLog 同款）。
  const boxRef = useRef<HTMLDivElement | null>(null)
  const stickRef = useRef(true)
  useEffect(() => {
    const box = boxRef.current
    if (box && stickRef.current) box.scrollTop = box.scrollHeight
  }, [rows.length])

  return (
    <div className="space-y-4">
      {/* 第 1 层 */}
      <div className="flex items-center gap-1 overflow-x-auto">
        {PIPELINE.map((seg, i) => (
          <div key={seg.id} className="flex shrink-0 items-center gap-1">
            {i > 0 && <span className={seg.unbuilt ? 'text-text-3/40' : 'text-text-3'}>{'──'}</span>}
            <span
              className="rounded-lg px-2.5 py-1 text-[12px]"
              style={
                seg.id === workflowId
                  ? { background: 'rgba(10,132,255,0.16)', color: '#0a84ff', fontWeight: 600 }
                  : { color: seg.unbuilt ? 'rgba(255,255,255,0.25)' : 'rgba(255,255,255,0.45)' }
              }
            >
              {seg.label}
            </span>
          </div>
        ))}
      </div>

      {/* 第 2 层：地铁站。点一站看那一站的时间线。 */}
      <div className="flex flex-wrap items-center gap-1">
        {stages.map((s, i) => (
          <div key={s} className="flex items-center gap-1">
            {i > 0 && <span className="text-text-3">{'──'}</span>}
            <button
              type="button"
              onClick={() => setPicked(s)}
              className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[12px] transition ${
                s === active ? 'bg-white/[0.08] text-text-1' : 'text-text-2 hover:bg-white/[0.04]'
              }`}
            >
              <span className={`h-2 w-2 rounded-full ${STAGE_DOT[statuses[s] ?? 'pending']}`} />
              <span className="font-mono">{s}</span>
            </button>
          </div>
        ))}
      </div>

      {/* 第 3 层：agent 每一轮。append-only，不去重。 */}
      <div
        ref={boxRef}
        onScroll={(e) => {
          const el = e.currentTarget
          stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
        }}
        className="max-h-[420px] overflow-y-auto rounded-xl p-2 font-mono text-[11.5px]"
        style={{ background: 'rgba(0,0,0,0.25)', border: '1px solid rgba(255,255,255,0.06)' }}
      >
        {rows.length === 0 ? (
          <p className="p-2 text-text-3">{isRunning ? '等待 agent 输出…' : '这一站没有 agent 活动'}</p>
        ) : (
          rows.map((ev) => <AgentRow key={`${ev.step}-${ev.seq}`} ev={ev} />)
        )}
      </div>

      {snapshotFile && runId && (
        <a
          className="text-[11.5px] text-signal-bright underline"
          href={`/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(snapshotFile)}`}
          target="_blank"
          rel="noreferrer"
        >
          {'下载失败时的完整快照'}
        </a>
      )}
    </div>
  )
}

function AgentRow({ ev }: { ev: ProgressEvent }) {
  const d = (ev.detail ?? {}) as Record<string, unknown>
  const seq = String(ev.seq ?? 0).padStart(2, '0')
  if (d.kind === 'think') {
    const calls = (d.calls ?? []) as { name: string; args: Record<string, unknown> }[]
    return (
      <div className="px-2 py-0.5">
        {calls.map((c, i) => (
          <div key={i} className="text-signal-bright">
            {`[${seq}] -> ${c.name}(${JSON.stringify(c.args)})`}
          </div>
        ))}
        {!!d.text && <div className="text-text-1">{`[${seq}] `}{'说: '}{String(d.text)}</div>}
      </div>
    )
  }
  return (
    <div className="px-2 py-0.5 text-text-3">
      {`[${seq}] <- ${String(d.tool ?? '')}: ${String(d.chars ?? 0)} `}
      {'字符 | '}
      {String(d.head ?? '')}
    </div>
  )
}
```

**不渲染 `LiveLog`** —— 第 3 层严格更全，两个都放是重复信息。

- [ ] **Step 2: `RunView` 改成不带 hooks 的分发器**

⚠️ **不要在现有 `RunView` 里加提前 return。** 它函数体第一行就是 `useState`，
而 `workflowId` 是会变的（切 tab 时 `WorkflowCard` 用同一个位置渲染另一个 workflow，
React 复用同一个实例）。提前 return 会让同一实例前后两次渲染的 hook 数量不同，
直接触发 `Rendered fewer hooks than expected` 崩溃——**这不是 lint 洁癖，是运行时崩**。

改法：把现有函数体整体改名为 `TreeRunView`（不导出），`RunView` 变成**没有任何 hook**
的分发器。它自己没 hook，就不存在 hook 数量变化；两个分支是不同组件类型，
切换时 React 自然卸载重建，状态也不会串。

```tsx
// 现有实现整体改名（只改函数名，函数体一行不动）
function TreeRunView({ events, workflowId, summary = null, isRunning = false }: {
  events: ProgressEvent[]
  workflowId: string
  summary?: Record<string, number> | null
  isRunning?: boolean
}) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  /* ……原样保留…… */
}

// 分发器：**这里不许有任何 hook**。
// m1/m2 的图节点内部是 agent 自主循环，是序列不是集合——buildTree 按 tool 名存 Map、
// 后来者覆盖，take_snapshot 的几十次调用会塌成一个。所以它们走单独的三层视图。
export function RunView(props: {
  events: ProgressEvent[]
  workflowId: string
  summary?: Record<string, number> | null
  isRunning?: boolean
}) {
  if (props.workflowId === 'm1' || props.workflowId === 'm2') {
    return (
      <MultisiteRunView
        events={props.events}
        workflowId={props.workflowId}
        isRunning={props.isRunning ?? false}
      />
    )
  }
  return <TreeRunView {...props} />
}
```

两个调用点（`WorkflowTrack.tsx:925`、`Logs.tsx:853`）**一行不用改**——分支只有一份实现。

- [ ] **Step 3: 构建**

Run: `cd dashboard/frontend && npm run build`
Expected: 退出码 0（build 会先跑 vitest），tsc 无悬空引用

- [ ] **Step 4: 校验没有裸中文**

Run:
```bash
python - <<'PY'
import io
for p in ["dashboard/frontend/src/components/workflow/MultisiteRunView.tsx",
          "dashboard/frontend/src/components/workflow/multisiteRun.ts"]:
    bad = [i+1 for i, l in enumerate(io.open(p, encoding="utf-8").read().splitlines())
           if any(ord(c) > 127 for c in l) and not l.strip().startswith(("//", "/*", "*", "{/*"))]
    print(p, "nonascii:", bad or 0)
PY
```
Expected: 两个都是 `nonascii: 0`

- [ ] **Step 5: Commit**

```bash
git add code/dashboard/frontend/src/components/workflow/MultisiteRunView.tsx \
        code/dashboard/frontend/src/components/workflow/WorkflowTrack.tsx \
        code/dashboard/static
git commit -m "feat(dashboard): m1/m2 三层视图（全链/LangGraph 站点/agent 时间线）"
```

---

### Task 11: 真机验一次 m1 + 收尾

**Files:**
- Modify: `dashboard/frontend/src/version.ts`（升 `Y` → 2.26.0，`Z`/`N` 归零由 build 处理）
- Modify: `PROGRESS.md` / `DECISION.md` / `PITFALLS.md`（按 docs-update 的顺序）

- [ ] **Step 1: 升版本号**

这是一个完整功能交付，升 `Y`：`version.ts` 改成 `2.26.0.0`（`N` 由下次 build 自增）。

- [ ] **Step 2: 重启后端并跑一次 m1**

```bash
# 先确认没有 workflow 在跑——真跑对真实站点有动作
curl -s http://localhost:8765/api/workflow/status
python scripts/run_layer1.py --search-url https://bambulab.jobs.feishu.cn/campus/ \
       --site bambulab --select-only
```

`--select-only` 对外零副作用（只选岗落库，不上传简历）。

- [ ] **Step 3: 逐条验收（spec §10）**

1. 第 2 层三站都亮，`find_jobs` 耗时明显最长
2. 第 3 层能看到 agent 说的话和工具调用，`take_snapshot` 出现多次**且没被合并**
3. `logs/runs/m1_*.jsonl` 里 `grep -c agent_step` > 0
4. Logs 页回放同一个 run，第 3 层内容与实时看到的一致（这是「回放 == 实时」那条测试的真机对照）

- [ ] **Step 4: 文档收尾**

- `PROGRESS.md`：「已完成」顶部写这条（带版本号 v2.26.0）；把「m1/m2 要能看到 agent 每一步」那条待跟进标记为已做；新增待跟进「W1 的 `data/apply_failures/` 按 §7.5 该搬进 run 目录」。
- `DECISION.md`：回填一行拍板结论 —— 「m1/m2 第 3 层用独立时间线而非复用 buildTree（后者按 tool 名去重）；第 1 层只画静态链不查跨 run 状态（否则要先定死 layer 状态流转）；产物按寿命分而非按类型分」，附 spec 路径。
- `PITFALLS.md`：如果实现过程中真踩到坑才写，没踩到就跳过。

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(multisite): m1/m2 三层可视化 (v2.26.0)"
```

---

## 附：本计划对 spec 的覆盖

| spec 节 | Task |
|---------|------|
| §2 不能照抄 W1/W2（buildTree 去重） | 9（`agentRows` 不去重 + 测试） |
| §3 三层定位 / Layer 3 语义 | 10（第 1 层静态链）；Layer 3 本身不实现 |
| §4 `describe_message` 一份解读 | 1、2 |
| §5 `agent_step` 事件 + 共用格式化 | 3、4 |
| §6 骨架从图定义导出 | 5 |
| §7 前端分支 + 新组件 | 9、10 |
| §7.5 产物按寿命分 + 读取端点 | 7、8 |
| §8 快照只记摘要、失败存全文 | 1（摘要）、7（全文） |
| §9 测试清单 | 各 Task 的 Step 1 |
| §10 范围与验收 | 11 |
| §11 明确不做 | —— |
