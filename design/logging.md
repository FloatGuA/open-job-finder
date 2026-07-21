# Logging Design

Pipeline 层结构化日志，从零设计。现有 event_log.py 及 logs/runs/ 体系废弃。

状态说明：✅ 已确认 | ⏳ 待确认

---

## 日志层级 ✅

```
Run
└── Step[]
    └── Tool[]
```

每次 W1Pipeline 或 W2Pipeline 的执行是一个 Run。
每个 Step 执行产生一条 Step 条目。
每个 Tool 调用产生一条 Tool 条目，只记录 debug 必要字段，不记录完整输入输出。

---

## 两类 Event ⏳

同一 JSONL 内混合写入，通过 `event` 字段区分用途：

```
logs/runs/{run_id}.jsonl
│
├── run_start / run_end              ← Pipeline 生命周期
├── step   (Trace event)             ← Step 执行记录，框架自动发出
├── tool   (Trace event)             ← Tool 调用记录，框架自动发出
└── {named} (Business event)         ← 业务决策结果，Step/Pipeline 层发出
```

**Trace event**（流程视角）：Step/Tool 是否执行，是否成功，耗时多少。框架统一发出，用于定位流程问题。

**Business event**（业务视角）：做了哪些有意义的决策，结果是什么。只在有实际业务意义时发出，用于快速检查业务问题。

---

## 日志格式 ✅

JSONL，每次 Run 一个文件：

```
logs/runs/{run_id}.jsonl
```

`run_id` 格式：`w1_{YYYYMMDD_HHmm}` / `w2_{YYYYMMDD_HHmm}`

### Run 级别条目

```json
{"event": "run_start", "run_id": "w1_20260527_0900", "pipeline": "w1", "ts": "2026-05-27T09:00:00"}
{"event": "run_end",   "run_id": "w1_20260527_0900", "status": "successful", "duration_ms": 45000,
 "summary": {"cards_viewed": 20, "applied": 5, "skipped": 15}, "ts": "..."}
```

### Step 级别条目（Trace）

```json
{
  "event": "step",
  "run_id": "w1_20260527_0900",
  "pipeline": "w1",
  "step": "fetch_jd",
  "scope": {"job_id": "abc123", "company": "字节跳动"},
  "status": "successful",
  "duration_ms": 820,
  "data": {"salary_decoded": "25-40k"},
  "error": null,
  "ts": "2026-05-27T09:01:23"
}
```

### Tool 级别条目（Trace）

```json
{
  "event": "tool",
  "run_id": "w1_20260527_0900",
  "step": "fetch_jd",
  "tool": "read_panel_jd",
  "scope": {"job_id": "abc123"},
  "status": "successful",
  "duration_ms": 350,
  "data": {"salary_raw": "25k-40k·13薪"},
  "error": null,
  "ts": "2026-05-27T09:01:24"
}
```

### Business Event 条目

```json
{
  "event": "job_scored",
  "run_id": "w1_20260527_0900",
  "scope": {"job_id": "abc123", "company": "字节跳动"},
  "data": {"score": 78, "reason": "技能匹配度高，薪资略低", "above_threshold": true},
  "ts": "2026-05-27T09:01:25"
}
```

Business event 无 `status` / `duration_ms` 字段（不是执行记录，是结果记录）。

---

## StepStatus ✅

```python
class StepStatus(Enum):
    SUCCESSFUL = "successful"   # 正常完成
    DEGRADED   = "degraded"     # 完成但有问题（CONTINUE_DEGRADED 路径）
    SKIPPED    = "skipped"      # 条件不满足，未执行
    FAILED     = "failed"       # 失败，触发 on_error 策略

@dataclass
class StepOutput:
    status: StepStatus
    error: Optional[str] = None   # FAILED / DEGRADED 时填充
```

---

## Business Events 清单 ⏳

| event | 触发方 | data 字段 |
|---|---|---|
| `job_scored` | CardPipeline（ScoreJob 完成后） | `score, reason, above_threshold, provider_used` |
| `job_applied` | CardPipeline（ApplyStep 完成后） | `result` |
| `job_skipped` | CardPipeline（任意跳过路径） | `reason`（classify_skip / score_below / llm_error / panel_failed） |
| `intent_analyzed` | ConversationPipeline（AnalyzeStep 完成后） | `intent, confidence, provider_used` |
| `resume_sent` | ConversationPipeline（ResumeStep 完成后） | `strategy_used` |
| `reply_sent` | ConversationPipeline（ReplyStep 完成后） | `reply_text` |
| `stage_advanced` | ConversationPipeline（UpsertHRConversation 返回 stage_changed=true） | `old_stage, new_stage` |
| `conv_timeout_closed` | FinalizeStep（MarkTimeoutRejections 完成后，逐条发） | `{}` |
| `job_no_response_rejected` | FinalizeStep（MarkTimeoutRejections 完成后，逐条发） | `{}` |

注：所有 Business event 的 `scope` 字段已含 `job_id` / `conv_id`，data 中不再重复。

---

## Trace Tool data 规格 ⏳

每个 Tool 的 `data` 字段只记录 debug 必要信息。原则：
- BrowserTool：记"到没到目标"和"关键计数"，不记 DOM 内容
- LLMTool：记决策结果 + provider，不记 prompt / response 全文
- DBTool：记影响行数或关键动作，不记 SQL
- BusinessLogicTool：记输入输出计数或关键判断结果

### W1 BrowserTools

| tool | data | 说明 |
|---|---|---|
| NavigateSearchUrl | `loaded_url` | 实际加载的 URL |
| ExtractCardList | `card_count` | 本次提取的卡片数 |
| ScrollSearchResults | `new_card_count, reached_end` | 滚动后新增卡片数 + 是否触底 |
| ClickCardOpenPanel | `panel_loaded` | 面板是否成功打开 |
| ReadPanelJD | `salary_raw` | 原始薪资字符串，jd_text 不记（过大） |
| ClickApplyButton | `result` | 点击结果枚举（applied / button_not_found 等） |
| HandleApplyDialog | `dialog_was_present, dialog_closed` | 弹窗是否出现 + 是否关闭 |

### W2 BrowserTools

| tool | data | 说明 |
|---|---|---|
| NavigateToChatList | `{}` | 成功与否在 status 字段 |
| ExtractConversationList | `item_count` | 本次提取的会话数 |
| ScrollChatList | `reached_end` | 是否滚动到底 |
| NavigateToConversation | `method, boss_conv_id_confirmed` | 导航方式 + 确认的 conv_id |
| ReadMessages | `message_count` | 读取的消息气泡总数，不记内容 |
| SendChatMessage | `{}` | 成功与否在 status 字段 |
| AcceptResumeCard | `card_found, cross_border_dialog` | 卡片是否找到 + 是否触发跨境弹窗 |
| ClickToolbarSendResume | `button_found, button_enabled` | 按钮状态 |
| UploadResumeFile | `{}` | 成功与否在 status 字段 |

### LLMTools

| tool | data | 说明 |
|---|---|---|
| ScoreJob | `score, provider_used` | 分数 + 使用的 LLM；reason / dimensions / above_threshold 归 Business event |
| AnalyzeHRIntent | `intent, provider_used` | 意图枚举 + 使用的 LLM；confidence / suggested_reply 归 Business event |

### DBTools

| tool | data | 说明 |
|---|---|---|
| ClassifyJobForW1 | `action, reason` | 分类结果 + 原因（DB 确定性逻辑，非 LLM 判断） |
| UpsertApplication | `status` | 写入的 status 值 |
| UpsertHRConversation | `stage, stage_changed` | 写入的 stage + 是否发生变化 |
| WriteHRMessages | `inserted_count` | 实际插入行数（跳过重复后） |
| UpdateHRAnalysis | `{}` | 成功与否在 status 字段 |
| GetApprovedReplies | `count` | 返回的已批准回复数 |
| GetConversationStates | `state_count` | 查询到的状态记录数 |
| SyncApplicationStatusFromConversations | `updated_count` | 批量更新行数 |
| MarkTimeoutRejections | `no_response_rejected_count, stale_closed_count` | 各类超时标记数 |

### BusinessLogicTools

| tool | data | 说明 |
|---|---|---|
| FilterConversations | `input_count, output_count` | 过滤前后的会话数 |
| DetectResumeRequest | `needs_resume, request_type` | 检测结果 |
| DecodeJobSalary | `{}` | 纯字符串转换，无需记录 |

---

## Dashboard 消费 ⏳

现有 Logs 页面（React）需要基于新格式重写或调整 API。
两个视图：
- Flow 视图：过滤 `event: step / tool`，展示执行时间线
- Decision 视图：过滤 Business event，展示业务决策时间线

---

## 待确认项

- [ ] 两类 Event 划分是否合理（Trace / Business）
- [ ] Business Events 清单是否完整，有无多余
- [ ] 各 Tool data 规格是否合适
- [ ] Dashboard 两视图设计
