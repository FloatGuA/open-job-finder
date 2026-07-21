# Run 日志模板与解读指南

> 面向两类读者：**排查问题的人**，和**被要求"看一下这次跑得对不对"的模型**。
> 诊断器：`code/services/run_diagnostics.py`（`diagnose_run` / `render_report`）
> 日志位置：`logs/runs/{run_id}.jsonl`，run_id 格式 `{w1|w2|w3}_{YYYYMMDD_HHmm}`（**UTC**）

---

## 0. 先记住三条，能避开我们真实踩过的坑

1. **run_id 里的时间是 UTC，不是本地时间。** `w2_20260721_0845` 是本地 16:45。曾因此把"刚刚正在跑"误读成"今早跑完的"。
2. **正在写的日志 ≠ 崩溃的日志。** 没有 `run_end` 可能只是**还在跑**。判断中断前先看文件修改时间和当前时间差。曾因此误判一次正常运行为"崩溃且报告丢失"。
3. **两套状态词汇表**：`step` 用 `successful|failed|skipped|degraded`；`run_end` 用 `done|failed`。混用会把 143 个健康 run 全标成异常（真发生过）。

---

## 1. 日志结构

每行一个 JSON。`event` 字段区分类型：

| event | 含义 | 关键字段 |
|-------|------|---------|
| `run_start` | 运行开始，**每个 run 必有** | `meta.trigger`（谁唤起）、`meta.params`（运行参数） |
| `run_end` | 运行收尾，**缺失=中断** | `status`(done/failed)、`summary`（结果汇总） |
| `step` | 流水线阶段 | `step`、`status`、`scope`、`duration_ms`、`error` |
| `tool` | 单个工具调用 | `tool`、`step`、`status` |
| `filter_decision` | 会话脏检查决策（**量大，正常**） | `visible=false`，仅文件不上 SSE |
| 业务事件 | 见下表 | `scope`、`data` |

### trigger 词汇（谁唤起了这次运行）

`manual` 手动 / `scheduled` 定时 / `selfcheck` 自检 / `regression`·`regression_live` 冒烟 / `null` 旧日志

### 业务事件

**外发动作**（不可撤销，对真人产生影响，诊断器会单独审计）：
`job_applied` 投递 · `resume_sent` 发简历 · `reply_sent` 发回复

**失败信号**：
`job_apply_failed` · `db_write_failed` 落库失败 · `conv_pipeline_error` · `send_reply_error` · `hr_conversation_stub_failed`

**告警**（降级但未失败）：
`llm_degraded` 全 provider 降级 · `page_drift_detected` · `run_time_budget_exceeded` · `reply_locate_gave_up`

**其他**：`job_scored` · `job_skipped` · `intent_analyzed` · `stage_advanced` · `conv_timeout_closed`

---

## 2. 诊断报告模板逐段解读

```
=== RUN 诊断 · w2_20260721_0845 ===
结论: PASS
```
`结论` = `ok` 字段。**`ok` 只表示"结构上没出错"**，不表示"验证到了什么"——覆盖是另一个维度（见冒烟的 `fully_covered`）。

```
[完整性]
  run_start ✓   run_end ✓   状态=done
  事件 1049   trigger=regression_live   08:45:56Z → 08:51:26Z
```
- `run_end ✗` → **中断**。先按第 0 节第 2 条排除"还在跑"，再当故障处理。
- `事件` 数量本身不说明好坏；`filter_decision` 通常占大头（W2 一次可上千条），属正常。

```
[参数生效核对]   传入 → log 回显
  max_conversations   5 → 5 ✓
  score_threshold    40 → 60 ✗ 未生效
```
把**你要求的参数**和 `run_start.meta.params` **实际记录的**对照。`✗ 未生效` 意味着端点接受了这个参数但没有转发到 runner —— 这是静默失效，光看运行结果发现不了。

```
[Step 统计]
    navigate         5✓
    resume           2✓ 3skip
```
按 step 名聚合各状态计数。`skip` 多不一定是问题（如"HR 未索要简历，无需发送"）；`✗` 一定要看 `[异常]` 里的具体错误。

```
[外发动作 · 真实副作用]
  发简历 2
```
本次运行**真实对外产生的不可撤销动作**。跑真跑档冒烟后，这一段是审计依据：谁收到了什么。

```
[run_end summary]
  {"convs_processed": 5, "resumes_sent": 2, "stage_changes": 2, ...}
```
流水线自报的结果。**注意**：它是流水线"认为"发生的事，与 DB 实际落库可能不一致——两者对不上正是历史 bug 的特征（见下）。

```
[异常]
  ! 无 run_end：进程中断或崩溃，本次运行未收尾
  ! 中断前已发生真实外发（发简历6）——对方已收到，落库状态未知
```
确定性规则判定，非模型推测。

---

## 3. 症状 → 病因速查

| 你看到 | 大概率是什么 | 下一步 |
|--------|------------|-------|
| 无 `run_end`，文件仍在增长 | **正在跑**，不是故障 | 等它跑完再看 |
| 无 `run_end`，文件已停止增长 | 进程被杀/崩溃 | 查后端是否重启过；看最后一个 step |
| 无 `run_end` + 有外发动作 | **最高危**：对方已收到，我方可能没落库 | 核对 DB：`applications.count_today` / `hr_messages` |
| `summary.applied > 0` 但 DB 没涨 | "投了但没落库"（历史真实 bug） | 查 `db_write_failed` 事件 |
| `db_write_failed` | 落库失败 | 看 `data` 里的具体 SQL/约束错误 |
| 参数核对 `✗ 未生效` | 端点没把参数转发给 runner | 查端点 → runner 的参数链 |
| `llm_degraded` | 全部 provider 失败，intent 落 unknown | 查 ollama 是否在跑 |
| 大量 `filter_decision` reason=`no_change` | 正常，会话没新消息 | 无需处理 |
| `filter_decision` reason=`unanalyzed` 反复出现在同一会话 | 分析反复失败 | 该会话在控制台可能隐形，查 `last_analyzed_ts` |
| 无 `run_start` | 旧格式日志（2026-06 前） | 无法诊断，不代表故障 |

---

## 4. 给模型的使用方式

不要手写脚本解析 JSONL（容易读错中间态——已发生过）。直接：

```python
from services import run_diagnostics as rd
diag = rd.diagnose_run("w2_20260721_0845")
print(rd.render_report(diag, rd.check_params_applied(diag, {"max_conversations": 5})))
```

批量体检：

```python
import glob, os
for p in glob.glob("logs/runs/*.jsonl"):
    d = rd.diagnose_run(os.path.basename(p)[:-6])
    if d.get("diagnosable") and not d["ok"]:
        print(d["run_id"], d["anomalies"])
```

判断规则全部是确定性代码，**不调用 LLM**：run 是否收尾、参数是否生效、外发是否落库，这些有唯一正确答案，交给模型判断只会引入臆造。模型的作用是读这份报告后做**根因推断和下一步建议**，不是替代这些判定。
