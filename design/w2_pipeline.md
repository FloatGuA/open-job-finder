# W2 Pipeline Design

会话检查 + 意图分析 + 自动回复 + 简历发送。

状态说明：✅ 已确认 | ⏳ 待确认

---

## 总体结构 ✅

```
W2Pipeline.run(config)
│
├── ScanStep                                  [一次：获取全部会话 + 待发回复]
│
├── ConversationPipeline × conversations      [per conv，脏检查后决定是否进入]
│   ├── NavigateStep
│   ├── ReadStep
│   ├── AnalyzeStep
│   ├── ResumeStep                            [条件执行]
│   ├── ReplyStep                             [条件执行]
│   └── Tool: UpsertHRConversation
│
└── FinalizeStep                              [一次：批量同步状态 + 超时标记]
```

---

## StepOutput 基类（所有 Step 共用）✅

```python
class StepStatus(Enum):
    SUCCESSFUL = "successful"
    DEGRADED   = "degraded"
    SKIPPED    = "skipped"
    FAILED     = "failed"

@dataclass
class StepOutput:
    status: StepStatus
    error: Optional[str] = None
```

所有 W2 Step 的具体 Output 继承此基类，子类字段存业务数据。
详见 `logging.md`。

---

## ScanStep ✅（Step 方向确认，Tool 细节待实现）

**目的**：导航到聊天列表，提取全部会话，与 DB 存储状态比对（脏检查），返回本次需要处理的会话列表。

脏检查是业务逻辑，在 ScanStep 内部完成，W2Pipeline 直接迭代输出结果，不做额外过滤。

```python
@dataclass
class ScanStepInput:
    pass

@dataclass
class ScanStepOutput(StepOutput):
    conversations_to_process: List[ConvBasic]     # 过滤后需要进入 ConversationPipeline 的会话
    approved_replies: Dict[str, ApprovedReply]    # conv_id → ApprovedReply，供 ConversationPipeline 查询
```

`on_error`: ABORT_WORKFLOW

**内部执行顺序**：
```
1. Tool: NavigateToChatList
2. Tool: ExtractConversationList + ScrollChatList（循环，直到 reached_end）
3. Tool: GetApprovedReplies            → 获取 reply_status=approved 的会话集合
4. Tool: GetConversationStates         → 从 DB 批量拉取 { conv_id → last_msg_preview, stage }
5. BusinessLogicTool: FilterConversations（纯函数）
       输入：current_convs, stored_states, approved_reply_ids
       过滤规则：
         先排除（满足任意一条 → 跳过）：
           - stage IN ('closed', 'offer')    ← 终态，永不处理
         再进入（排除后满足任意一条 → 进入处理）：
           - has_unread == True
           - conv_id 在 approved_replies 中
           - stored last_msg_preview != current last_msg_preview
       输出：conversations_to_process
```

---

## ConversationPipeline（per conv）✅（Step 方向确认，Tool 细节待实现）

**目的**：完整处理一个 HR 会话：导航 → 读取 → 分析 → 行动 → 持久化。

```python
@dataclass
class ConversationPipelineInput:
    conv: ConvBasic
    approved_reply: Optional[ApprovedReply]

@dataclass
class ConversationPipelineOutput(StepOutput):
    conv_id: str
    stage_advanced: bool
    resume_sent: bool
    reply_sent: bool
```

`on_error`: SKIP（单会话失败不影响其余）

---

## NavigateStep（W2）⏳

**目的**：打开指定 HR 会话（优先 boss_conv_id URL 直跳，降级扫列表原子 JS 点击）。

```python
@dataclass
class W2NavigateStepInput:
    conv_id: str
    company: str
    hr_name: str
    boss_conv_id: str

@dataclass
class W2NavigateStepOutput(StepOutput):
    boss_conv_id_confirmed: str
```

`on_error`: SKIP
Tool: `NavigateToConversation`

---

## ReadStep ⏳

**目的**：读取当前会话所有消息气泡，立即持久化到 hr_messages（不等后续步骤）。

```python
@dataclass
class ReadStepInput:
    conv_id: str

@dataclass
class ReadStepOutput(StepOutput):
    messages: List[Message]       # { sender, text, time }
    new_message_count: int
```

`on_error`: SKIP
Tools: `ReadMessages` → `WriteHRMessages`

---

## AnalyzeStep ⏳

**目的**：检测简历请求（纯函数）+ LLM 意图分析 + 持久化分析结果。

跳过条件：`new_message_count == 0 AND current_intent is not None`
`DetectResumeRequest` 是 BusinessLogicTool（纯函数），内联在此 Step。

```python
@dataclass
class AnalyzeStepInput:
    conv_id: str
    messages: List[Message]
    company: str
    job_title: Optional[str]
    current_intent: Optional[str]
    new_message_count: int

@dataclass
class AnalyzeStepOutput(StepOutput):
    needs_resume: bool
    resume_request_type: Optional[str]   # system_notification | hr_card | hr_text | null
    already_sent_resume: bool
    intent: str
    needs_reply: bool
    suggested_reply: Optional[str]
```

`on_error`: CONTINUE_DEGRADED
Tools: `DetectResumeRequest` → `AnalyzeHRIntent` → `UpdateHRAnalysis`

---

## ResumeStep ⏳

**目的**：按简历请求类型选择对应策略发送简历。

触发条件：`needs_resume=True AND already_sent_resume=False`
ResumeStep 先于 ReplyStep 执行。两者可在同一次会话中同时触发。

```python
@dataclass
class ResumeStepInput:
    conv_id: str
    needs_resume: bool
    request_type: Optional[str]
    already_sent: bool
    resume_path: str

@dataclass
class ResumeStepOutput(StepOutput):
    strategy_used: Optional[str]    # accept_card | toolbar | upload | skipped
    sent: bool
```

`on_error`: CONTINUE_DEGRADED
Tools（三选一）: `AcceptResumeCard` / `ClickToolbarSendResume` / `UploadResumeFile`

策略路由：
```
request_type=system_notification  →  AcceptResumeCard
request_type=hr_card              →  AcceptResumeCard
request_type=hr_text              →  UploadResumeFile
request_type=null                 →  ⏳ 待确认
```

---

## ReplyStep ⏳

**目的**：发送已批准的 HR 回复。

触发条件：`approved_reply is not None`

```python
@dataclass
class ReplyStepInput:
    conv_id: str
    reply_text: str

@dataclass
class ReplyStepOutput(StepOutput):
    sent: bool
```

`on_error`: CONTINUE_DEGRADED
Tool: `SendChatMessage`

---

## UpsertHRConversation（ConversationPipeline 末尾）⏳

每个 ConversationPipeline 最后调用此 Tool 写入最终会话状态。
stage 推导规则见下方。

Tool: `UpsertHRConversation`

---

## Stage 推导规则 ⏳

AnalyzeStep 完成后，ConversationPipeline 控制层推导 new_stage：

```
intent=interview_invite  →  升为 interview（当前 stage < interview 时）
intent=offer             →  升为 offer
intent=rejection         →  升为 closed
resume_sent=True         →  升为 resume_sent（当前 stage < resume_sent 时）
其他                     →  升为 active（当前 stage = new 时）
```

Stage 只升不降。`closed` / `offer` 为终态，不可覆写。

---

## FinalizeStep ⏳

**目的**：所有会话处理完后，批量同步投递状态 + 标记超时会话为 closed。

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

`on_error`: CONTINUE_DEGRADED
Tools: `SyncApplicationStatusFromConversations` → `MarkTimeoutRejections`

---

## 已确认

- ✅ 总体结构：per-conversation sub-pipeline，W2Pipeline 管理循环
- ✅ ScanStep：含脏检查（FilterConversations 纯函数）+ 终态排除
- ✅ ConversationPipeline：NavigateStep → ReadStep → AnalyzeStep → ResumeStep → ReplyStep → UpsertHRConversation
- ✅ ResumeStep：三策略互斥，ResumeStep 先于 ReplyStep
- ✅ Stage 推导规则
- ✅ FinalizeStep：批量同步 + 超时标记

## 待处理

- [ ] ResumeStep 策略路由：request_type=null 时的处理（实现阶段决定）
- [ ] 各 Step / Tool 的 emits 规格（logging.md，实现阶段填入）
