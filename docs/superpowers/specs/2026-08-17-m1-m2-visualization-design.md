# m1/m2 三层可视化设计（2026-08-17）

> 状态：已与用户对齐，待实现。
> 相关：`PROGRESS.md`「m1/m2 要能看到 agent 每一步和它的推理过程」、`DECISION.md`。

## 1. 要解决什么

m1/m2 的 LangGraph **节点级**进度已经进了 `logs/runs/*.jsonl` + SSE，但**节点内部的 agent 循环几十步一条都没落盘**——只有 `agent_runtime._trace` 打到 uvicorn 的 stdout。

后果是：agent 选错岗、兜圈子、半途而废时，只能靠事后翻数据库倒推它当时在想什么。而 m1/m2 恰恰是**唯一一条内部不确定的流程**，最需要看清楚的那条反而最看不见。

用户要的形态（原话）：

> m1/m2 不是结构化定死的 workflow，但 LangGraph 这种状态图也是很结构化的步骤了，只是到 ReAct 循环里 agent 做什么是不确定的。agent 用什么 tool 肯定是看情况，**这里用什么 tool 和 agent 的「说」这个思考过程天然同步**，可以做成地铁路线图（总体 workflow 到哪了 / LangGraph 到哪了 / 内层循环到哪了）+ Agent 思考可视化。

## 2. 为什么不能照抄 W1/W2 的渲染

| | W1/W2/W3 | m1/m2 |
|---|---|---|
| 步骤从哪来 | 代码写死，有静态骨架 `SKELETON` | 节点内部是 agent 自主循环，每次都不同 |
| 骨架的用途 | 「预期步骤 vs 实际步骤」对照 | 对 agent 层没有意义：没有预期步骤这回事 |
| 数据结构 | 集合（每步每个 tool 调一次） | **序列**（`take_snapshot` 一次 run 调几十次） |

**决定性的代码事实**：`WorkflowTrack.tsx::buildTree` 把 tool 事件按**名字**存进 `Map`、后来者覆盖（注释写着 "Latest event wins for a given node"）。ReAct 循环挂进去会塌成一个节点。

→ **第 3 层必须是独立的 append-only 时间线，不能当现有树的第三级。**

## 3. 三层定位

| 层 | 内容 | 确定性 | 渲染 | 数据来源 |
|----|------|--------|------|---------|
| 1 总体 workflow | m1 选岗 → 审批① → m2 填表 → 审批② → Layer 3 | 固定 | **静态全链，高亮当前段** | 前端常量 |
| 2 LangGraph 节点 | `ensure_ready` → `find_jobs` → … | 固定，图定义即权威源 | 地铁站（走到第几站、每站耗时/结果） | `stage_names()` + `step` 事件 |
| 3 ReAct 内层循环 | agent 每一轮：说了什么 + 调了什么 + 看到什么 | 不确定 | 时间线，流式追加 | 新增 `agent_step` 事件 |

第 1 层**只画静态链并高亮当前段**，不查跨 run 真实状态。理由：跨 run 全链要以「岗位」为主体、用 `pending_job_id` 把 m1 run / 人工审批 / m2 run 串起来，那等于先把 layer 之间的状态流转定死——而那正是用户明确说「还没想清楚、要单独理」的部分。方位感现在就能给，状态机等理清了再说。

**第 3 层按第 2 层的站点分组**：点第 2 层某一站，第 3 层只显示那一站的时间线；默认跟随正在跑的（或最后一个）站点。不做成一条跨站大流水。

## 4. 数据源：一份解读，两个出口

`agent_runtime.run_agent` 的 `astream` 循环已经逐条拿到每条新消息，现在只是 `_trace()` 打到 stdout。

抽一个纯函数，stdout 和 run 日志**共用同一份解读**——否则「日志里说的」和「终端里说的」会慢慢变成两回事，而那种漂移没有任何东西会发现：

```python
def describe_message(msg: BaseMessage, seq: int) -> dict | None:
    """一条 agent 消息 → 结构化记录。返回 None 表示这条不值得记。"""
```

产出两种形状：

```python
# AIMessage（思考 + 它决定要调的工具，来自同一条消息，天然同步）
{"kind": "think", "seq": 13, "text": "列表里看到 20 个岗位，先处理前 5 个",
 "calls": [{"id": "call_abc", "name": "record_job", "args": {"title": "…"}}]}

# ToolMessage（工具返回）
{"kind": "observe", "seq": 14, "call_id": "call_abc", "tool": "take_snapshot",
 "chars": 12431, "head": "uid=2_0 RootWebArea \"招聘-职位列表\""}
```

- `text` 为空且 `calls` 为空的 AIMessage 返回 `None`（没内容不占一行）。
- `args` 每个值截断到 120 字符（沿用 `_trace` 现有做法）。
- `head` = 返回内容第一行，截断到 160 字符。
- `call_id` 让前端能把「调用」和「结果」配成一对；配不上就各占一行，不强求。

`run_agent` 增加可选回调：

```python
async def run_agent(agent, user_message, max_steps=MAX_STEPS,
                    trace: bool = True, on_step=None) -> dict
```

`on_step(record: dict)` 对每条新消息调用一次。`trace=True` 时 stdout 行为完全不变（命令行直跑仍然有输出，那是 `--direct` 路径的唯一可见性）。

## 5. 事件契约：新增 `agent_step`

### 为什么不复用 `log_tool`

1. `buildTree` 按 tool 名去重（见 §2），复用会塌缩。
2. agent 的「说」不是 tool call，塞进 tool 事件要造一个假 tool 名。
3. `seq` 是 agent 事件独有的（tool 事件没有序号概念）。

### JSONL（`services/run_logger.py`）

```json
{"event": "agent_step", "run_id": "m1_20260817_0930", "step": "find_jobs",
 "seq": 13, "kind": "think", "text": "…", "calls": [...], "ts": "2026-08-17T09:31:02Z"}
```

新增 `RunLogger.log_agent_step(step: str, record: dict) -> None`（`services/run_logger.py`），
`pipeline/run_logger.py` 的适配层同名方法负责 JSONL + SSE 双写。

### SSE（`ProgressEvent`）

`ProgressEvent` 增加一个可选字段：

```ts
seq?: number | null   // 非 null = 这是一条 agent 步事件
```

其余字段沿用：`workflow` / `step`（LangGraph 节点名，用来分组）/ `status`（固定 `"info"`）/
`message`（一行人可读摘要）/ `detail`（完整 record）。`tool` 字段在 `kind="observe"` 时填工具名，
`kind="think"` 时为 `null`。

**agent_step 只在 `debug=True` 时推 SSE**，与现有 `log_tool` 一致；JSONL 无条件写。

### 回放（`services/run_log_reader.py::parse_run_events`）

加一个 `elif event == "agent_step"` 分支，产出与 SSE **完全相同**的 ProgressEvent 形状。

> 这是本设计里最容易漂移的一处：同一条记录有两条路（实时 SSE / 事后回放）到达同一个前端组件。
> 两边各写一套格式化必然分叉。所以格式化收敛成一个函数 `agent_event(pipeline, step, record) -> dict`，
> 并写一条测试直接比对两条路的产出。
>
> **放在 `pipeline/run_logger.py`**，`services/run_log_reader.py` 导入它——沿用现有 `_ui_status`
> 的方向（reader 已经 `from pipeline.run_logger import _ui_status`）。反过来放会成循环导入。

## 6. 第 2 层骨架：从图定义导出，不手维护

`WorkflowTrack.tsx` 的 `SKELETON` 是手维护的静态模板，已经漂移过（`PITFALLS.md` 有记录）。
m1/m2 不重蹈——骨架从 `build_graph` 的阶段表导出。

`multisite/layer1_agent.py` 提出模块级：

```python
STAGE_ORDER = ("ensure_ready", "find_jobs", "write_pending_jobs",
               "open_application", "scan_and_classify_fields", "write_pending_application")

def stage_names(select_only: bool) -> tuple[str, ...]:
    """这次 run 会经过哪些图节点。select_only=True 只跑到 Checkpoint 1。"""
    return STAGE_ORDER[:3] if select_only else STAGE_ORDER
```

`build_graph` 里的 `stages` 表仍是函数与 summarizer 的权威源，**名字顺序由测试守着不许分叉**：
用假 tools（只需 `.name` 属性）建一次图，断言 `list(graph.nodes)` 与 `stage_names()` 一致。

新端点：

```
GET /api/multisite/stages
→ {"m1": ["ensure_ready", "find_jobs", "write_pending_jobs"],
   "m2": ["ensure_ready", ..., "write_pending_application"]}
```

（m1 = 队列里 `select_only=True` 的那条路径；m2 = 完整路径。端点只做接线，名字来自 `stage_names()`。）

## 7. 前端

### 入口分支

`RunView` 在最外层分支：`workflowId` 是 `m1`/`m2` → 渲染新组件 `MultisiteRunView`；其余原样走现有树。
**W1/W2/W3 的渲染路径一行不改。**

### 新文件 `components/workflow/MultisiteRunView.tsx`

```
第1层  [m1 选岗]━━●━━[审批①]────[m2 填表]────[审批②]┄┄[Layer3 未建]
            ▲ 本次 run

第2层  ● ensure_ready 1.2s ──◉ find_jobs 12.4s ──○ write_pending_jobs
                                （◉ = 正在跑，○ = 还没走到）

第3层  [12] → take_snapshot()
       [12] ← 12.4KB · uid=2_0 RootWebArea "招聘-职位列表"
       [13] 说: 列表里看到 20 个岗位，先处理前 5 个
       [13] → record_job({title: "后端开发实习生", …})
```

- 第 3 层数据 = `events.filter(e => e.seq != null && e.step === activeStage)`，**按 `seq` 升序，不去重**。
- 站点状态：`done`/`error` 来自该 step 的终态事件；有 agent_step 但无终态 = `running`；两者都无 = `pending`。
- m1/m2 **不渲染通用 `LiveLog`**——第 3 层严格更全，两个都放是重复信息。
- 长时间线：容器内滚动，跟随最新；用户手动上滚后停止跟随（与现有 `LiveLog` 行为一致）。

## 8. a11y 快照：只记摘要，失败时另存全文

一次 run 几十张、每张 10KB+，全存是几百 KB/run。

- **常规**：`kind="observe"` 只记 `chars` + `head`（首行）。够回答「它调了什么、看到的页面标题是什么」。
- **失败时**：某个 stage 抛异常时，把**当时最近一张**完整快照写进 `data/multisite_debug/{stage}_failed_{ts}.txt`，
  并在该 stage 的 `step` 失败事件 `data` 里带上文件名，前端给一个可下载链接。
- 复用现有 `_dump_debug_snapshot(tag, text)`，调用点扩到 `traced_stage` 的 except 分支。

  **快照从哪取**：不能用 `state["snapshot_text"]`——它只在 stage **成功返回时**才被写回，
  stage 失败时那里装的是**上一个** stage 的快照，正好在最需要它的时候是错的。
  正确的源是 `build_graph` 里那个 `_latest_snapshot` 闭包（`_snapshot_and_cache` 每次截图都更新它）。
  所以 `traced_stage` 增加一个可选参数 `snapshot_provider: Callable[[], str]`，由 `build_graph`
  传 `lambda: _latest_snapshot["text"]`。不传则失败时不 dump（命令行 `--direct` 路径不受影响）。

判据：成功的 run 要看的是「它调了什么、说了什么」；只有出错才需要「它到底看到了什么」。

## 9. 测试

| 测什么 | 怎么测 |
|--------|--------|
| `describe_message` 四种形状 | 纯函数：AIMessage 只有 text / 只有 calls / 两者都有 / ToolMessage |
| 空消息不占行 | text 与 calls 都空 → 返回 `None` |
| `log_agent_step` 双写 | 假 emitter + tmp 日志目录，断言 JSONL 一行 + SSE 一条 |
| **回放 == 实时**（关键） | 同一条 record 走 `pipeline/run_logger` 的 SSE 路径与 `parse_run_events` 的回放路径，断言两个 dict 相等 |
| 阶段表不漂移 | 假 tools 建图，`list(graph.nodes) == stage_names(select_only)`，两种 `select_only` 各一次 |
| 失败时 dump 的是最近一张 | `traced_stage` 的 fn 抛异常 → 断言 dump 出来的是 `snapshot_provider()` 的返回值，不是 `state["snapshot_text"]` |
| 时间线不塌缩 | vitest：同名工具连调 3 次 → 渲染出 3 行 |
| 站点状态推导 | vitest：pending / running / done / error 四种输入 |

全部走 TDD（先写失败的测试），改完做变异验证。

## 10. 范围与验收

- **后端 m1/m2 一次做完**：两者共用 `build_graph` + `run_agent`，拆不开也没必要拆。
- **真机只验 m1**（`scripts/run_layer1.py --select-only`，对外零副作用）：跑一次，确认
  ①第 2 层三站都亮、②第 3 层能看到 agent 的话和工具调用、③`logs/runs/m1_*.jsonl` 里有 `agent_step` 行、
  ④Logs 页回放同一个 run，第 3 层内容与实时一致。
- **m2 真机验证推迟**：它会往企业系统真传简历，且当前简历闸门会拒跑（三份简历全 missing/stale），
  等用户导出 PDF 后单独跑。

## 11. 明确不做

- 跨 run 的岗位生命周期视图（第 1 层的完整版）——等 layer 状态流转理清后再说。
- W1/W2/W3 的渲染改动——一行不碰。
- `pending_jobs` 的「已填表」终态——用户已明确本轮不做。
- agent 步骤的实时性优化（虚拟滚动等）——先按几百条的量做，真卡了再说。
