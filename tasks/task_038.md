# Task 038 — W2 非浏览器 Tools

## Goal
实现 W2 专用的 10 个非浏览器 Tool：1 个 LLMTool（AnalyzeHRIntent）+ 2 个 BusinessLogicTool（DetectResumeRequest / FilterConversations）+ 7 个 DBTool。

## Background
W2 的数据层操作比 W1 复杂：需要处理会话脏检查（FilterConversations）、消息去重写入（WriteHRMessages）、分析结果保护覆写（UpdateHRAnalysis）等。这些 Tool 在 W2Pipeline（T039）实现之前需要先独立完成和测试。

依赖：T030（DB schema）+ T031（BaseTool）+ T032（PromptManager + prompts/analyze_intent.md）。

## Implementation Requirements

### 目录结构

```
code/tools/
├── llm/
│   └── analyze_intent.py
├── biz_logic/
│   ├── detect_resume.py
│   └── filter_conversations.py
└── db/
    └── w2/
        ├── __init__.py
        ├── upsert_hr_conversation.py
        ├── write_hr_messages.py
        ├── update_hr_analysis.py
        ├── get_approved_replies.py
        ├── get_conversation_states.py
        ├── sync_application_status.py
        └── mark_timeout_statuses.py
```

### AnalyzeHRIntent（LLMTool）

```
Input:  conv_id, messages: List[{sender, text, time}], company, job_title: Optional[str]
Output: ToolResult, data = {"intent": str, "provider_used": str}
        （confidence / needs_reply / suggested_reply 归 Business event，不写日志 data）
        额外返回 confidence / needs_reply / suggested_reply 供 Pipeline 使用
```

用 `prompt_manager.render('analyze_intent', context)` 构建 prompt，调用 llm_client.complete，解析 JSON。intent 枚举：interview_invite / offer / rejection / resume_request / general / unknown。

### DetectResumeRequest（BusinessLogicTool）

纯函数，无 IO。分析消息列表，检测简历请求类型，同时检查之后是否已发过简历（防重复）。

```
Input:  messages: List[{sender, text}]
Output: ToolResult, data = {}（ok 始终 True）
        额外返回：needs_resume: bool / request_type: Optional[str] / already_sent: bool
```

request_type 枚举：system_notification（系统卡片）/ hr_card（HR 发卡片）/ hr_text（HR 文字）/ None。

检测逻辑参照现有 `_detect_resume_request` 和 `_has_sent_resume` 方法（code/services/browser_agent.py）。

### FilterConversations（BusinessLogicTool）

纯函数，无 IO。ScanStep 内部调用。

```
Input:  current_convs: List[{conv_id, has_unread, last_msg_preview}]
        stored_states: Dict[conv_id, {last_msg_preview, stage}]
        approved_reply_ids: List[str]
Output: ToolResult, data = {"input_count": int, "output_count": int}
        额外返回 conversations_to_process 列表
```

过滤规则（严格按 design/tools_catalog.md）：
- **先排除**：stage IN ('closed', 'offer') → 永不处理
- **再进入**（排除后满足任意一条）：
  - has_unread == True
  - conv_id 在 approved_reply_ids 中
  - stored last_msg_preview != current last_msg_preview

### DBTools 规格

**UpsertHRConversation**：
- stage 只升不降约束：数据库层用 CASE WHEN 实现（不在 Python 层判断），新 stage 只有在枚举序号 > 当前时才更新
- 返回 stage_changed: bool（供 ConversationPipeline 判断是否发 stage_advanced 事件）
- data: `{"stage": str, "stage_changed": bool}`

**WriteHRMessages**：
- INSERT OR IGNORE（利用 UNIQUE(conv_id, sender, text, msg_time) 约束跳过重复）
- data: `{"inserted_count": int}`

**UpdateHRAnalysis**：
- 写入 hr_conversations 的 intent / reply_text / reply_status 字段
- CASE WHEN 保护：reply_status IN ('approved', 'sent', 'dismissed') 时不覆写（保护所有终态，不只是 approved）
- reply_status 参数只允许写入 null 或 pending（approved 由用户通过 Dashboard 设置）
- data: `{}`

**GetApprovedReplies**：
- 查询 reply_status = 'approved' 的所有会话
- 返回 conversations 列表（conv_id / hr_name / company / reply_text / boss_conv_id）
- data: `{"count": int}`

**GetConversationStates**：
- Input: conv_ids: List[str]
- 批量查询 last_msg_preview 和 stage
- 返回 states: Dict[conv_id, {last_msg_preview, stage}]
- data: `{"state_count": int}`

**SyncApplicationStatusFromConversations**：
- 根据 hr_conversations.stage 批量更新 applications.status：
  interview → INTERVIEWING，offer → OFFER，closed → REJECTED
- 一次执行更新所有符合条件的记录
- data: `{"updated_count": int}`

**MarkTimeoutStatuses**（原名 MarkTimeoutRejections，实现时用此更准确的命名，注册时保留 "mark_timeout_rejections" 作为 name 供向后兼容）：
- 同时处理两类超时：
  1. applications：no_response_days 天内 stage < interview → status = REJECTED
  2. hr_conversations：stale_conv_days 天内无活动 → stage = closed
- 返回 no_response_rejected: List[job_id] 和 stale_closed: List[conv_id]
- data: `{"no_response_rejected_count": int, "stale_closed_count": int}`

### ToolRegistry 注册

提供 `register_w2_tools(registry, db, llm_client, prompt_manager)` 函数。

## Acceptance Criteria

- [ ] FilterConversations 对 stage='closed' 的会话正确排除，stage='new' + has_unread=True 的正确进入
- [ ] UpdateHRAnalysis 在 reply_status='approved' 时不覆写（CASE 保护验证：调用前写 approved，调用后 SELECT 仍是 approved）
- [ ] UpdateHRAnalysis 在 reply_status='sent' 时同样不覆写
- [ ] WriteHRMessages 对重复消息（相同 conv_id+sender+text+msg_time）不报错，inserted_count=0
- [ ] UpsertHRConversation 将 stage 从 'active' 更新为 'new'（降级）时，DB 中 stage 保持 'active'（只升不降验证）
- [ ] MarkTimeoutStatuses 正确处理 applications 和 hr_conversations 两类记录

## Reference
- design/tools_catalog.md（W2 所有 Tool 章节）
- design/db_schema.md（hr_conversations / hr_messages 结构、stage 状态机）
- design/logging.md（DBTools / LLMTools / BusinessLogicTools data 规格）
- code/services/tracker.py（现有 SQL 逻辑参考）
- code/tools/check_responses.py（现有 W2 逻辑，DetectResumeRequest 和意图分析参考）
- prompts/analyze_intent.md（T032 产出）
