# Task 039 — W2 Pipeline

## Goal
实现完整 W2Pipeline，驱动 ScanStep + ConversationPipeline + FinalizeStep，处理会话检查、意图分析、简历发送、回复发送的完整流程。

## Background
W2 是会话管理 workflow：扫描聊天列表 → 对需要处理的会话逐个执行完整操作 → 批量同步状态。

ScanStep 内部包含页面扫描和业务筛选两个概念层：页面扫描（NavigateToChatList / ExtractConversationList / ScrollChatList）负责从 DOM 获取当前状态；业务筛选（FilterConversations）是纯函数，决定哪些会话需要进入 ConversationPipeline。两者概念独立，但都在 ScanStep 内部顺序执行。

依赖：T030（DB schema）+ T031（基础框架）+ T033（ProfileLoader）+ T035（W2 BrowserTools）+ T038（W2 非浏览器 Tools）。

## Implementation Requirements

### 目录结构

```
code/pipeline/w2/
├── __init__.py
├── pipeline.py                      # W2Pipeline
├── scan_step.py                     # ScanStep
├── conversation_pipeline.py         # ConversationPipeline（per conv）
├── finalize_step.py                 # FinalizeStep
└── steps/
    ├── __init__.py
    ├── navigate.py                  # W2NavigateStep
    ├── read.py                      # ReadStep
    ├── analyze.py                   # AnalyzeStep
    ├── resume.py                    # ResumeStep
    └── reply.py                     # ReplyStep
```

### W2Pipeline（pipeline.py）

```python
@dataclass
class W2Config:
    dry_run: bool
    no_response_days: int
    stale_conv_days: int
    resume_path: str

class W2Pipeline:
    def __init__(self, registry: ToolRegistry, profile: Profile, logger: RunLogger)
    def run(self, config: W2Config) -> dict
```

run() 流程：
1. log_run_start（run_id = `w2_{YYYYMMDD_HHmm}`）
2. ScanStep → 获取 conversations_to_process + approved_replies
3. 遍历 conversations_to_process → ConversationPipeline.run(conv, approved_reply)
   - on_error: SKIP（单会话失败不影响其余）
4. FinalizeStep（所有会话处理完后）
5. log_run_end（汇总 convs_processed / replies_sent / resumes_sent / stage_changes）

### ScanStep（scan_step.py）

```python
@dataclass
class ScanStepOutput(StepOutput):
    conversations_to_process: List[ConvBasic]
    approved_replies: Dict[str, ApprovedReply]  # conv_id → ApprovedReply
```

内部执行顺序（严格按此顺序，概念上 ScanStep=页面扫描 + FilterConversations=业务筛选）：
1. NavigateToChatList
2. 循环：ExtractConversationList → 若未触底则 ScrollChatList（seen_conv_ids 参数去重），直到 reached_end=True
3. GetApprovedReplies → 获取所有 reply_status=approved 的会话
4. GetConversationStates(conv_ids) → 批量从 DB 拉取 {last_msg_preview, stage}
5. FilterConversations(current_convs, stored_states, approved_reply_ids) → conversations_to_process

on_error: ABORT_WORKFLOW（无法扫描列表则终止整个 W2）

### ConversationPipeline（conversation_pipeline.py）

```python
@dataclass
class ConvBasic:
    conv_id: str
    hr_name: str
    company: str
    boss_conv_id: str
    hr_title: str
    job_id: Optional[str]

@dataclass
class ApprovedReply:
    conv_id: str
    reply_text: str

class ConversationPipeline:
    def run(self, conv: ConvBasic, approved_reply: Optional[ApprovedReply],
            config: W2Config) -> ConversationPipelineOutput
```

执行顺序：
1. W2NavigateStep（on_error: SKIP）
2. ReadStep（on_error: SKIP）
3. AnalyzeStep（on_error: CONTINUE_DEGRADED）
4. Stage 推导（ConversationPipeline 控制层执行，不在 Step 内）：
   ```
   intent=interview_invite  → 升为 interview（当前 stage < interview 时）
   intent=offer             → 升为 offer
   intent=rejection         → 升为 closed
   resume_sent=True         → 升为 resume_sent（当前 stage < resume_sent 时）
   其他                     → 升为 active（当前 stage = new 时）
   ```
5. ResumeStep（条件：needs_resume=True AND already_sent=False）（on_error: CONTINUE_DEGRADED）
6. ReplyStep（条件：approved_reply is not None）（on_error: CONTINUE_DEGRADED）
7. UpsertHRConversation Tool（写入最终 stage + last_msg_preview）
   - 若 stage_changed=True → log_business_event("stage_advanced", scope={conv_id, company}, data={old_stage, new_stage})

### Step 规格

**W2NavigateStep**（on_error: SKIP）：
- 调用 NavigateToConversation Tool
- 输出：boss_conv_id_confirmed

**ReadStep**（on_error: SKIP）：
- 调用 ReadMessages → WriteHRMessages
- 输出：messages: List, new_message_count: int（与 DB 比较后的新增数）

**AnalyzeStep**（on_error: CONTINUE_DEGRADED）：
- 跳过条件：new_message_count == 0 AND current_intent is not None
- 执行：DetectResumeRequest（纯函数）→ AnalyzeHRIntent → UpdateHRAnalysis
- 成功后发 log_business_event("intent_analyzed", data={intent, confidence, provider_used})
- 输出：needs_resume / request_type / already_sent_resume / intent / needs_reply / suggested_reply

**ResumeStep**（on_error: CONTINUE_DEGRADED，触发条件：needs_resume AND NOT already_sent）：
- 策略路由：
  - request_type=system_notification → AcceptResumeCard
  - request_type=hr_card → AcceptResumeCard
  - request_type=hr_text → UploadResumeFile
  - request_type=None → UploadResumeFile（默认 fallback）
- 成功后发 log_business_event("resume_sent", data={strategy_used})
- 输出：strategy_used / sent: bool

**ReplyStep**（on_error: CONTINUE_DEGRADED，触发条件：approved_reply is not None）：
- 调用 SendChatMessage(text=approved_reply.reply_text)
- 成功后：UpdateHRAnalysis 将 reply_status 设为 null（清空），reply_text 清空
- 发 log_business_event("reply_sent", data={reply_text})（reply_text 内容短，值得记录）
- 输出：sent: bool

### FinalizeStep（finalize_step.py）

```python
@dataclass
class FinalizeStepInput:
    no_response_days: int
    stale_conv_days: int

@dataclass
class FinalizeStepOutput(StepOutput):
    updated_count: int
    closed_count: int
```

on_error: CONTINUE_DEGRADED

执行：
1. SyncApplicationStatusFromConversations
2. MarkTimeoutStatuses → 遍历 no_response_rejected 逐条发 log_business_event("job_no_response_rejected", scope={job_id}, data={})；遍历 stale_closed 逐条发 log_business_event("conv_timeout_closed", scope={conv_id}, data={})

## Acceptance Criteria

- [ ] ScanStep 对 stage=closed 的会话正确排除（FilterConversations 验证）
- [ ] approved_reply 存在时 ReplyStep 发送消息，DB reply_status 更新为 null（清空）
- [ ] needs_resume=True + already_sent=False 时 ResumeStep 执行策略路由
- [ ] Stage 推导：intent=interview_invite 且当前 stage=active → DB stage 更新为 interview，发出 stage_advanced 事件
- [ ] FinalizeStep 超时会话正确发出 conv_timeout_closed business event
- [ ] 单会话 ConversationPipeline 失败不影响其余会话继续处理

## Reference
- design/w2_pipeline.md（完整 Step 设计、ScanStep 内部顺序、Stage 推导规则）
- design/logging.md（Business Events 清单，特别注意发出位置）
- code/tools/check_responses.py（现有 W2 逻辑参考）
- code/services/browser_agent.py（sync_conversations 等现有实现）
