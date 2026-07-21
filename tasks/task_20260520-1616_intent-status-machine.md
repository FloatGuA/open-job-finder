# Task: 意图→状态自动推进 + REJECTED 复活 + LLM 回复审批系统

## 目标

补全状态机缺口：rejection/offer 意图自动更新 applications.status；RESPONDED/RESUME_REQUESTED 7 天无 HR 回复自动 REJECTED；REJECTED 可被复活为 RESPONDED。同时新增 LLM 回复审批系统，让用户在 Dashboard 和 Chat 页面对 LLM 建议回复进行四态审批（pending / approved / revision / dismissed）。

## 背景

Feature 2 已实现 LLM 意图分析，但：
1. rejection/offer 意图只写 intent 字段，未更新 applications.status
2. APPLIED 有 3 天超时，RESPONDED/RESUME_REQUESTED 无超时保护
3. REJECTED 是终态，HR 主动重新联系时无法处理
4. suggested_reply 无审批流程，用户只能手动复制粘贴

设计决策（已确认）：
- 不引入 WAITING 状态；RESPONDED/RESUME_REQUESTED 承担沟通+等待语义
- REJECTED 复活路径：REJECTED → RESPONDED（新 HR 消息且意图正向）
- 审批四态：pending → approved / revision（附用户编辑稿） / dismissed
- [已发送] 按钮调用 mark-sent，清空建议回复并标记 dismissed

## 实现要求

### 1. `code/schemas.py`

在 `HRConversation` dataclass 中新增三个可选字段（在 `suggested_reply` 之后）：

```python
needs_reply: Optional[bool] = None
reply_status: Optional[str] = None   # None | 'pending' | 'approved' | 'revision' | 'dismissed'
reply_draft: Optional[str] = None
```

### 2. `code/services/tracker.py`

**2a. DB 迁移**（在 `_init_db` 中，每条 ALTER 用 try/except OperationalError 保证幂等）：
```sql
ALTER TABLE hr_conversations ADD COLUMN needs_reply INTEGER;
ALTER TABLE hr_conversations ADD COLUMN reply_status TEXT;
ALTER TABLE hr_conversations ADD COLUMN reply_draft TEXT;
```

**2b. VALID_TRANSITIONS 新增**：
```python
"REJECTED": {"RESPONDED"},   # 复活路径，原为终态
```

**2c. get_hr_conversations() 或 get_conversation()** 从查询结果读取新增的三列，填充到 HRConversation 对象。

**2d. update_hr_analysis() 方法签名扩展**，新增 `needs_reply` 和 `reply_status` 参数：
```python
def update_hr_analysis(self, conv_id: str, intent: str, suggested_reply: str,
                       needs_reply: bool = False, reply_status: Optional[str] = None) -> None:
    self.conn.execute(
        """UPDATE hr_conversations
           SET intent=?, suggested_reply=?, needs_reply=?, reply_status=?
           WHERE conv_id=?""",
        (intent, suggested_reply, int(needs_reply), reply_status, conv_id),
    )
    self.conn.commit()
```

**2e. 新增 `update_reply_approval` 方法**：
```python
def update_reply_approval(self, conv_id: str, reply_status: str, reply_draft: str = "") -> None:
    self.conn.execute(
        "UPDATE hr_conversations SET reply_status=?, reply_draft=? WHERE conv_id=?",
        (reply_status, reply_draft, conv_id),
    )
    self.conn.commit()
```

**2f. 新增 `mark_stale_conversations_rejected` 方法**：
```python
def mark_stale_conversations_rejected(self, days: int = 7) -> int:
    """Mark RESPONDED/RESUME_REQUESTED jobs with no new HR message as REJECTED after N days."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    rows = self.conn.execute(
        """SELECT job_id FROM applications
           WHERE status IN (?, ?) AND updated_at < ?""",
        (AppStatus.RESPONDED.value, AppStatus.RESUME_REQUESTED.value, cutoff),
    ).fetchall()
    rejected = 0
    for row in rows:
        job_id = row["job_id"]
        recent = self.conn.execute(
            """SELECT 1 FROM hr_conversations
               WHERE job_id = ? AND last_synced > ? LIMIT 1""",
            (job_id, cutoff),
        ).fetchone()
        if recent:
            continue
        self.update_status(job_id, AppStatus.REJECTED)
        rejected += 1
    return rejected
```

### 3. `code/tools/analyze_hr_message.py`

**3a. 在 LLM prompt 中增加 `needs_reply` 输出字段**：

系统提示不变，用户 prompt 末尾的 JSON 格式改为：
```
返回 JSON：
{
  "intent": "<意图>",
  "needs_reply": <true 或 false>,
  "suggested_reply": "<建议中文回复，不超过 80 字；needs_reply=false 时为空字符串>"
}
```

**3b. execute() 返回值**新增 `needs_reply` 字段（bool），从 LLM JSON 响应中读取，缺失时默认 `False`。

### 4. `code/tools/check_responses.py`

**4a. Phase 2c 扩展**（在现有 `interview_invite` 分支后补全，并在循环开头跳过 REJECTED 会话）：

```python
for conv in synced_convs:
    if conv.last_msg_from != "hr":
        continue
    # REJECTED 会话的复活逻辑在 Phase 2d，此处跳过
    if conv.job_id:
        app = self.tracker.get_application(conv.job_id)
        if app and app.status == AppStatus.REJECTED:
            continue

    result = analyze_tool.execute(conv)

    # 意图 → 状态映射
    intent = result["intent"]
    if conv.job_id:
        if intent == "interview_invite":
            _safe_update_status(self.tracker, conv.job_id, AppStatus.INTERVIEW)
        elif intent == "rejection":
            _safe_update_status(self.tracker, conv.job_id, AppStatus.REJECTED)
        elif intent == "offer":
            _safe_update_status(self.tracker, conv.job_id, AppStatus.OFFER)
        # 其余意图不改 status

    # 审批记录
    reply_status = "pending" if result.get("needs_reply") else None
    self.tracker.update_hr_analysis(
        conv.conv_id, intent, result.get("suggested_reply", ""),
        needs_reply=result.get("needs_reply", False),
        reply_status=reply_status,
    )
    analyzed_count += 1
```

注：`_safe_update_status` 是一个本地辅助函数，包裹 `tracker.update_status` 并 catch ValueError（防止非法转移抛出）：
```python
def _safe_update_status(tracker, job_id, status):
    try:
        tracker.update_status(job_id, status)
    except (ValueError, Exception):
        pass
```

**4b. 新增 Phase 2d（在 Phase 2c 之后）**：

```python
# Phase 2d: REJECTED 会话复活
reactivated = 0
for conv in synced_convs:
    if conv.last_msg_from != "hr" or not conv.job_id:
        continue
    app = self.tracker.get_application(conv.job_id)
    if app is None or app.status != AppStatus.REJECTED:
        continue
    result = analyze_tool.execute(conv)
    self.tracker.update_hr_analysis(
        conv.conv_id, result["intent"], result.get("suggested_reply", ""),
        needs_reply=result.get("needs_reply", False),
        reply_status="pending" if result.get("needs_reply") else None,
    )
    if result["intent"] == "rejection":
        continue  # 维持 REJECTED
    _safe_update_status(self.tracker, conv.job_id, AppStatus.RESPONDED)
    reactivated += 1
emit_progress("phase2d", f"复活了 {reactivated} 条 REJECTED 会话")
```

**4c. Phase 4b（在现有 Phase 4 mark_no_response_rejected 调用之后）**：

```python
stale_rejected = self.tracker.mark_stale_conversations_rejected(days=7)
if stale_rejected:
    emit_progress("phase4b", f"{stale_rejected} 条沟通中会话超时转 REJECTED")
```

### 5. `code/dashboard/server.py`

新增五个审批端点（路由前缀 `/api/conversations`）：

```python
GET  /api/conversations/pending-replies
     查询：needs_reply = 1 AND reply_status IN ('pending', 'revision', 'approved')
     返回：List[{conv_id, hr_name, company, intent, suggested_reply,
                 reply_status, reply_draft, last_synced}]

POST /api/conversations/{conv_id}/approve-reply
     调用：tracker.update_reply_approval(conv_id, 'approved')
     返回：{ok: true}

POST /api/conversations/{conv_id}/revise-reply
     body: {draft: str}
     调用：tracker.update_reply_approval(conv_id, 'revision', body.draft)
     返回：{ok: true}

POST /api/conversations/{conv_id}/dismiss-reply
     调用：tracker.update_reply_approval(conv_id, 'dismissed')
     返回：{ok: true}

POST /api/conversations/{conv_id}/mark-sent
     直接 SQL：UPDATE hr_conversations SET reply_status='dismissed',
               suggested_reply='', reply_draft='' WHERE conv_id=?
     返回：{ok: true}
```

pending-replies 端点通过 `app.state.tracker` 访问 tracker，与其他会话端点保持一致。

### 6. `code/dashboard/frontend/src/api/index.ts`

在 `Conversation` interface 中追加（已有 intent/suggested_reply，补充新增字段）：
```typescript
needs_reply?: boolean
reply_status?: 'pending' | 'approved' | 'revision' | 'dismissed'
reply_draft?: string
```

新增 `PendingReply` interface：
```typescript
interface PendingReply {
  conv_id: string
  hr_name: string
  company: string
  intent: string
  suggested_reply: string
  reply_status: 'pending' | 'approved' | 'revision'
  reply_draft: string
  last_synced: string
}
```

新增 API 方法（在 API 对象中）：
```typescript
getPendingReplies: (): Promise<PendingReply[]>
approveReply: (conv_id: string): Promise<void>
reviseReply: (conv_id: string, draft: string): Promise<void>
dismissReply: (conv_id: string): Promise<void>
markSent: (conv_id: string): Promise<void>
```

所有 CJK 字符串使用 `\uXXXX` 转义。

### 7. `code/dashboard/frontend/src/pages/Dashboard.tsx`

在 ScheduleCard 之前新增 `ReplyApprovalCard` 组件：

**数据流**：
- `load()` 调用 `API.getPendingReplies()`，每 15 秒自动刷新
- 本地 state：`items: PendingReply[]`，`editingId: string | null`，`draftText: string`

**卡片 UI（三列内容）**：
```
┌─ HR 回复审批  N 条 ─────────────────────────────────────┐
│                                                           │
│  [意图强调色] 公司名 · HR 姓名  [状态强调色] pending/revision/approved  │
│  "建议回复或用户编辑稿文本"                             │
│  [批准] [修改] [驳回]   ← pending 状态                           │
│  [已发送] [驳回]       ← approved/revision 状态                  │
│                                                           │
│  暂无待审批建议回复                                    ← 空状态        │
└───────────────────────────────────────────────────────────┘
```

**交互逻辑**：
- pending：[批准] → approveReply → 本地更新 reply_status='approved'；[修改] → 展开内联编辑 textarea，保存后 reviseReply → 本地更新为 revision；[驳回] → dismissReply → 乐观从列表移除
- revision/approved：[已发送] → markSent → 乐观移除；[驳回] → dismissReply → 乐观移除
- 内联编辑时初始值为 suggested_reply（pending）或 reply_draft（revision）

**意图标签颜色**（`intentBadgeStyle` 辅助函数）：
- interview_invite：绿色
- rejection：红色
- offer：金色
- 其余：蓝紫色

所有 CJK 用 `\uXXXX` 转义，JSX 属性用 `={'\u...'}` 形式。

### 8. `code/dashboard/frontend/src/pages/Chat.tsx`

在会话详情面板的消息气泡列表上方（已有 suggested_reply 展示区域的位置），将原有的静态显示替换为可交互的审批卡片：

```tsx
{selectedConv && (selectedConv.reply_status === 'pending' ||
                  selectedConv.reply_status === 'revision' ||
                  selectedConv.reply_status === 'approved') && (
  <div className="审批卡片样式">
    <p>建议回复</p>
    <p>{selectedConv.reply_status === 'revision'
        ? selectedConv.reply_draft
        : selectedConv.suggested_reply}</p>
    {/* pending: 批准/修改/驳回 */}
    {/* revision/approved: 已发送/驳回 */}
  </div>
)}
```

操作后通过回调更新父组件的 conversations 列表（或重新 fetch 单条会话）。

所有 CJK 用 `\uXXXX` 转义，JSX 属性用 `={'\u...'}` 形式。

### 9. `TECHNICAL.md`

更新 AppStatus 状态机章节，将现有图替换为：

```
APPLIED
  │ (HR 主动联系)
  ▼
RESPONDED ↔ RESUME_REQUESTED      ← 沟通阶段，LLM 持续分析建议回复
  │              │
  └──────┬───────┘
         │ (HR 给明确信号 / 超时)
         ├──→ INTERVIEW   (intent = interview_invite)
         ├──→ OFFER       (intent = offer)
         └──→ REJECTED    (intent = rejection / 7天无回复)
                │
                └──→ RESPONDED     (复活：新HR消息 + intent ≠ rejection)
```

触发条件补充说明（文字段落）。

## 验收标准

- [ ] `pytest code/` 全部通过（无新增 failure）
- [ ] `cd code/dashboard/frontend && npm run build` 无报错
- [ ] HR 回复 rejection 意图 → job status 自动 REJECTED
- [ ] HR 回复 offer 意图 → job status 自动 OFFER
- [ ] RESPONDED/RESUME_REQUESTED 7 天无新 HR 消息 → 自动 REJECTED
- [ ] REJECTED 会话收到新 HR 消息且意图正向 → status 变 RESPONDED，Dashboard 显示审批卡片
- [ ] needs_reply=true → reply_status='pending'，出现在 Dashboard 审批队列
- [ ] needs_reply=false → 不出现在审批队列
- [ ] [批准] → reply_status='approved'，显示 [已发送] 按钮
- [ ] [修改] → 内联编辑，保存后 reply_status='revision'，显示用户编辑稿
- [ ] [驳回] → 乐观从队列移除
- [ ] [已发送] → 调用 mark-sent，乐观从队列移除
- [ ] Chat 页面会话详情内嵌相同的审批操作
