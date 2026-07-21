# Task 040 — 日志埋点

## Goal
在 W1/W2 所有 Step 和 Tool 上接入 RunLogger，实现 Trace + Business event 双轨日志全量覆盖，废弃旧 event_log.py 的最后引用。

## Background
T031 实现了 RunLogger 能力，T037/T039 实现了 Pipeline 和 Step，但两者对 RunLogger 的接入可能只有最小程度。本 Task 做全量埋点接入：确保每个 Step 和 Tool 的执行都被记录，Business event 在正确位置（由正确的 Step 或 Pipeline 层）发出。

本 Task 不新增功能逻辑，只做埋点接入和格式对照。

## Implementation Requirements

### Trace Events 覆盖

每个 Step 执行前后记录：
```python
start_ts = time.time()
# ... step execution ...
duration_ms = int((time.time() - start_ts) * 1000)
logger.log_step(
    step="fetch_jd",
    scope={"job_id": card.job_id, "company": card.company},
    status=output.status.value,
    duration_ms=duration_ms,
    data={...},     # Step 级别的 data，通常为空或只含关键标志
    error=output.error
)
```

每个 Tool execute 前后记录（在 BaseTool.execute 外层包装，或 ToolRegistry.call 中统一处理）：
```python
logger.log_tool(
    step=current_step_name,
    tool=tool.name,
    scope={...},
    status="successful" if result.ok else "failed",
    duration_ms=...,
    data=result.data,   # Tool 的 data 字段直接用，不做额外处理
    error=result.error
)
```

建议方式：在 ToolRegistry.call() 中统一加埋点，而不是每个 Tool 内部各自写。这样 T034~T038 的 Tool 无需改动，只更新 registry.call 即可。

### Tool data 字段对照检查

对照 design/logging.md「Trace Tool data 规格」逐一检查 T034~T038 产出的每个 Tool 的 data 字段：

- 不应出现：jd_text / messages 全文（过大）
- 应出现（W1）：salary_raw / card_count / new_card_count / panel_loaded / result（枚举）等
- 应出现（W2）：item_count / reached_end / method / boss_conv_id_confirmed / message_count 等
- 应出现（LLM）：score / intent / provider_used
- 应出现（DB）：action / inserted_count / stage / stage_changed / updated_count 等

如发现 Tool 的 data 字段不符合规格，在本 Task 中修正（加字段或删除过大字段）。

### Business Events 覆盖

确认以下 Business event 在正确位置发出（对照 design/logging.md Business Events 清单）：

**W1**：
- `job_scored`：CardPipeline，ScoreJob 成功后（score / reason / above_threshold / provider_used）
- `job_applied`：ApplyStep 成功后（result）
- `job_skipped`：CardPipeline（reason: classify_skip / score_below / llm_error / panel_failed）

**W2**：
- `intent_analyzed`：AnalyzeStep 成功后（intent / confidence / provider_used）
- `resume_sent`：ResumeStep 成功后（strategy_used）
- `reply_sent`：ReplyStep 成功后（reply_text）
- `stage_advanced`：ConversationPipeline，UpsertHRConversation 后若 stage_changed=True（old_stage / new_stage）
- `conv_timeout_closed`：FinalizeStep，逐条发（scope 含 conv_id）
- `job_no_response_rejected`：FinalizeStep，逐条发（scope 含 job_id）

检查每个 event 的 scope 字段（job_id / conv_id / company 等），确认 data 字段无冗余（scope 已有的不重复写入 data）。

### event_log.py 清理

确认所有对旧 `code/services/event_log.py` 的 import 已移除（T031 完成后应已处理，本 Task 做最后确认）。若仍有残留引用，在本 Task 中清除。

### 验证方式

在 dry_run=True 模式下触发 W1Pipeline，检查产出的 JSONL 文件：
- 有 run_start / run_end
- 有至少一条 event="step"
- 有至少一条 event="tool"
- 有至少一条 Business event

## Acceptance Criteria

- [ ] 一次完整 dry_run 后，`logs/runs/` 下出现 `w1_{YYYYMMDD_HHmm}.jsonl` 文件
- [ ] `grep '"event": "job_scored"' logs/runs/*.jsonl` 能找到对应条目（dry_run 时可能 score 但不 apply）
- [ ] `grep '"event": "tool"' logs/runs/*.jsonl | python -c "import sys,json; [print(json.loads(l)['tool']) for l in sys.stdin]"` 列出所有工具名，无遗漏
- [ ] 每条 tool 日志的 data 字段无 jd_text / messages 大字段
- [ ] 无对 event_log.py 的 import（grep 验证）

## Reference
- design/logging.md（全文，特别是「Trace Tool data 规格」和「Business Events 清单」）
- code/pipeline/w1/ + code/pipeline/w2/（T037/T039 产出，在这里加埋点）
- code/tools/registry.py（建议在 call 方法中统一加 trace）
