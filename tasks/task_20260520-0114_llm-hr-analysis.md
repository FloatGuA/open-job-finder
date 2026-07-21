# Task: LLM HR 消息意图分析 + Dashboard 审批卡片

## 目标

在 W2（check workflow）中新增 Phase 2c：调用 LLM 分析每条 HR 最新消息的意图（greeting/interview_invite/rejection 等），生成建议回复，存回 `hr_conversations`。在 Dashboard 新增"待处理 HR 回复建议"卡片，供用户一键复制并标记已发送。

## 背景

- "scoring" LLM chain 在 `config.yaml` 中已存在，`build_llm_client(config, "scoring")` 可直接调用，无需新增配置
- `tools/check_responses.py` 目前有 Phase 1（扫描）→ Phase 2（sync）→ Phase 2b（状态回写）→ Phase 3（legacy 检查）→ Phase 4（超时拒绝）
- Phase 2c 在 Phase 2b 之后、Phase 3 之前插入，只对本次 `synced_convs` 中 `last_msg_from == "hr"` 的会话执行分析
- LLM 调用模式参照 `tools/score_job.py`：`build_llm_client(config, "scoring")` → `llm.complete(prompt, system)` → `safe_parse_json(response, required_fields={"intent": str})`
- 关键约束：`rejection` 意图**仅存标签**，不修改 `applications.status`；`interview_invite` 意图可自动调用 `tracker.update_status(job_id, AppStatus.INTERVIEW)`（tracker 内有 VALID_TRANSITIONS 守卫）

## 实现要求

### 1. `code/tools/analyze_hr_message.py`（新建）

```python
from schemas import HRConversation
from services.llm_client import build_llm_client
from services.llm_parser import safe_parse_json

INTENTS = ["greeting", "interview_invite", "rejection", "info_request",
           "salary_discussion", "offer", "other"]

SYSTEM_PROMPT = (
    "You are a job-seeker assistant analyzing HR messages on Boss直聘. "
    "Return ONLY valid JSON, no markdown, no explanation."
)

PROMPT_TEMPLATE = """公司：{company}
HR：{hr_name}
最近消息（最新在后，最多 5 条）：
{messages_text}

请返回 JSON：
{{
  "intent": "<{intents}>",
  "confidence": <0.0-1.0>,
  "suggested_reply": "<建议中文回复，不超过 80 字；不需要回复时返回空字符串>"
}}
\nintent 只能为以下之一：{intents}""".format(
    company="{company}", hr_name="{hr_name}", messages_text="{messages_text}",
    intents=" | ".join(INTENTS)
)


class AnalyzeHRMessageTool:
    def __init__(self, config: dict):
        self.llm = build_llm_client(config, "scoring")  # reuse scoring chain

    def execute(self, conv: HRConversation) -> dict:
        """Analyze last HR message. Returns {"intent": str, "suggested_reply": str}."""
        recent = conv.messages[-5:] if len(conv.messages) > 5 else conv.messages
        messages_text = "\n".join(
            f"[{m.get('sender', '?')}] {m.get('text', '')}" for m in recent
        )
        prompt = PROMPT_TEMPLATE.format(
            company=conv.company,
            hr_name=conv.hr_name,
            messages_text=messages_text or conv.last_msg_text,
        )
        response_text, _ = self.llm.complete(prompt, system=SYSTEM_PROMPT)
        parsed = safe_parse_json(response_text, required_fields={"intent": str})
        intent = parsed.get("intent", "other")
        if intent not in INTENTS:
            intent = "other"
        suggested_reply = str(parsed.get("suggested_reply") or "")
        return {"intent": intent, "suggested_reply": suggested_reply}
```

### 2. `code/schemas.py`

在 `HRConversation` dataclass 中新增两个字段（加在 `stage` 之后）：
```python
intent: Optional[str] = None
suggested_reply: Optional[str] = None
```

### 3. `code/services/tracker.py`

**a. `_create_tables()` 迁移**：在 `hr_conversations` 表的 stage 迁移块之后，添加 intent/suggested_reply 迁移：

```python
# existing_cols 已在前面定义
if existing_cols and "intent" not in existing_cols:
    self.conn.execute(
        "ALTER TABLE hr_conversations ADD COLUMN intent TEXT"
    )
if existing_cols and "suggested_reply" not in existing_cols:
    self.conn.execute(
        "ALTER TABLE hr_conversations ADD COLUMN suggested_reply TEXT NOT NULL DEFAULT ''"
    )
```

注意：需检查 `existing_cols` 不为空（即表已存在）才能 ALTER。对于新建表，CREATE TABLE 语句中直接加上这两列：
```sql
intent            TEXT,
suggested_reply   TEXT NOT NULL DEFAULT ''
```

**b. `upsert_hr_conversation()` 修改**：INSERT 和 ON CONFLICT DO UPDATE 中均**不包含** `intent` 和 `suggested_reply`，保护 LLM 分析结果不被会话同步覆盖。INSERT 中不传这两列，ON CONFLICT UPDATE 子句也不更新这两列。

**c. `_row_to_hr_conv()` 修改**：读取 `intent` 和 `suggested_reply`，带 fallback：
```python
cols = row.keys()
intent = row["intent"] if "intent" in cols else None
suggested_reply = row["suggested_reply"] if "suggested_reply" in cols else ""
return HRConversation(
    ...,  # 现有字段不变
    intent=intent,
    suggested_reply=suggested_reply,
)
```

**d. 新增方法 `update_hr_analysis()`**：
```python
def update_hr_analysis(self, conv_id: str, intent: str, suggested_reply: str) -> None:
    """Store LLM analysis results for an HR conversation."""
    with self.conn:
        self.conn.execute(
            "UPDATE hr_conversations SET intent = ?, suggested_reply = ? WHERE conv_id = ?",
            (intent, suggested_reply, conv_id),
        )
```

**e. 新增方法 `get_pending_replies()`**：
```python
def get_pending_replies(self) -> List[HRConversation]:
    """Return conversations that have a non-empty suggested_reply."""
    rows = self.conn.execute(
        "SELECT * FROM hr_conversations WHERE suggested_reply IS NOT NULL AND suggested_reply != '' ORDER BY last_synced DESC",
    ).fetchall()
    return [self._row_to_hr_conv(row) for row in rows]
```

**f. 新增方法 `dismiss_reply()`**：
```python
def dismiss_reply(self, conv_id: str) -> None:
    """Clear suggested_reply to mark as handled."""
    with self.conn:
        self.conn.execute(
            "UPDATE hr_conversations SET suggested_reply = '' WHERE conv_id = ?",
            (conv_id,),
        )
```

### 4. `code/tools/check_responses.py`

**a. `__init__` 新增 `config` 参数**：
```python
def __init__(self, tracker: ApplicationTracker, aggressive_resume: bool = False, config: dict = None):
    self.tracker = tracker
    self.aggressive_resume = aggressive_resume
    self.config = config or {}
```

**b. Phase 2c 插入**（在 Phase 2b emit 之后、Phase 3 开始之前）：

```python
# ── Phase 2c: LLM intent analysis ─────────────────────────────────────
if synced_convs and self.config:
    from tools.analyze_hr_message import AnalyzeHRMessageTool
    analyze_tool = AnalyzeHRMessageTool(self.config)
    analyzed_count = 0
    for conv in synced_convs:
        if _stop_check():
            break
        if conv.last_msg_from != "hr":
            continue
        try:
            result = analyze_tool.execute(conv)
            self.tracker.update_hr_analysis(
                conv.conv_id, result["intent"], result["suggested_reply"]
            )
            if result["intent"] == "interview_invite" and conv.job_id:
                self.tracker.update_status(conv.job_id, AppStatus.INTERVIEW)
            analyzed_count += 1
        except Exception as exc:
            # 分析失败：不存储任何 intent，仅记录 warning，不影响其他会话处理
            logger.warning("HR analysis failed for %s: %s", conv.conv_id, exc)
    if analyzed_count:
        _emit("phase2c", "done", f"LLM 分析了 {analyzed_count} 条 HR 消息意图")
```

### 5. `code/tools/registry.py`

`CheckResponsesTool` 注册时传入 `config`：
```python
register_tool(CheckResponsesTool(
    tracker=tracker,
    aggressive_resume=config.get("apply", {}).get("aggressive_resume", False),
    config=config,
))
```

### 6. `code/dashboard/server.py`

**a. 修改 `get_conversations` 返回值**：在每条 conversation dict 中加上 `"intent": c.intent` 和 `"suggested_reply": c.suggested_reply`。

**b. 新增端点 `GET /api/conversations/pending-replies`**：
```python
@app.get("/api/conversations/pending-replies")
async def get_pending_replies() -> JSONResponse:
    _initialize_state()
    convs = app.state.tracker.get_pending_replies()
    return JSONResponse({
        "replies": [
            {
                "conv_id": c.conv_id,
                "hr_name": c.hr_name,
                "company": c.company,
                "intent": c.intent or "",
                "suggested_reply": c.suggested_reply or "",
                "last_synced": c.last_synced,
            }
            for c in convs
        ]
    })
```

**c. 新增端点 `POST /api/conversations/{conv_id}/dismiss-reply`**：
```python
@app.post("/api/conversations/{conv_id}/dismiss-reply")
async def dismiss_reply(conv_id: str) -> JSONResponse:
    _initialize_state()
    app.state.tracker.dismiss_reply(conv_id)
    return JSONResponse({"ok": True})
```

### 7. `code/dashboard/frontend/src/api/index.ts`

**a. 扩展 `Conversation` interface**（加在 `stage` 之后）：
```typescript
intent?: string
suggested_reply?: string
```

**b. 新增 `PendingReply` interface**：
```typescript
export interface PendingReply {
  conv_id: string
  hr_name: string
  company: string
  intent: string
  suggested_reply: string
  last_synced: string
}
```

**c. 新增 API 方法**（加入 `API` 对象）：
```typescript
getPendingReplies: (): Promise<{ replies: PendingReply[] }> =>
  fetch('/api/conversations/pending-replies').then(r => r.json()),

dismissReply: (conv_id: string): Promise<{ ok: boolean }> =>
  fetch(`/api/conversations/${conv_id}/dismiss-reply`, { method: 'POST' }).then(r => r.json()),
```

### 8. `code/dashboard/frontend/src/pages/Dashboard.tsx`

**新增 `PendingRepliesCard` 组件**（放在 `ScheduleCard` 组件定义之前）：

```tsx
// CJK 全部用 \uXXXX 转义
const INTENT_LABELS: Record<string, string> = {
  greeting: '打招呼',        // 打招呼
  interview_invite: '面试邀请', // 面试邀请
  rejection: '已拒绝',         // 已拒绝
  info_request: '请求信息', // 请求信息
  salary_discussion: '薪资洽谈', // 薪资洽谈
  offer: 'Offer',
  other: '其他',                    // 其他
}

const INTENT_COLORS: Record<string, string> = {
  interview_invite: '#10b981',   // green
  rejection: '#ef4444',          // red
  offer: '#f59e0b',              // amber
  info_request: '#6366f1',       // indigo
  salary_discussion: '#8b5cf6',  // violet
  greeting: '#64748b',           // slate
  other: '#64748b',
}

function PendingRepliesCard() {
  const [items, setItems] = useState<PendingReply[]>([])
  const [copied, setCopied] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const data = await API.getPendingReplies()
      setItems(data.replies ?? [])
    } catch { /* offline */ }
  }, [])

  useEffect(() => {
    void load()
    const id = window.setInterval(() => void load(), 15_000)
    return () => window.clearInterval(id)
  }, [load])

  const handleCopy = async (item: PendingReply) => {
    await navigator.clipboard.writeText(item.suggested_reply)
    setCopied(item.conv_id)
    setTimeout(() => setCopied(null), 2000)
  }

  const handleDismiss = async (conv_id: string) => {
    setItems(prev => prev.filter(i => i.conv_id !== conv_id))  // optimistic
    try { await API.dismissReply(conv_id) } catch { void load() }
  }

  if (items.length === 0) return null  // 无待处理时隐藏卡片

  return (
    <section ...>
      <header>
        {/* 待处理 HR 回复建议 */}
        <h2>待处理 HR 回复建议</h2>
        <span>{items.length}</span>
      </header>
      {items.map(item => (
        <div key={item.conv_id}>
          {item.intent && (
            <span style={{ background: INTENT_COLORS[item.intent] }}>
              {INTENT_LABELS[item.intent] ?? item.intent}
            </span>
          )}
          <span>{item.company} · {item.hr_name}</span>
          <p>{item.suggested_reply}</p>
          <button onClick={() => void handleCopy(item)}>
            {copied === item.conv_id ? '已复制✓' : '复制'}
          </button>
          <button onClick={() => void handleDismiss(item.conv_id)}>
            {/* 已发送 */}
            已发送
          </button>
        </div>
      ))}
    </section>
  )
}
```

在 `Dashboard` 组件 return JSX 中，在 `<ScheduleCard />` 之前插入 `<PendingRepliesCard />`。

### 9. `code/dashboard/frontend/src/pages/Chat.tsx`

**a. 意图徽章**：在会话列表项的 stage 徽章之后，渲染 `conv.intent` 对应标签：

```tsx
// 在 Chat.tsx 顶部定义（与 Dashboard 相同映射，CJK \uXXXX）
const INTENT_LABELS: Record<string, string> = { ... }  // 同上
const INTENT_COLORS: Record<string, string> = { ... }  // 同上

// 会话列表中，stage 徽章之后：
{conv.intent && (
  <span className="rounded px-1.5 py-0.5 text-xs text-white"
        style={{ background: INTENT_COLORS[conv.intent] ?? '#64748b' }}>
    {INTENT_LABELS[conv.intent] ?? conv.intent}
  </span>
)}
```

**b. 建议回复卡片**：在会话详情面板的 header 底部分割线之后、消息气泡列表之前：

```tsx
{selectedConv?.suggested_reply && (
  <div className="mx-4 mb-3 rounded-xl p-3"
       style={{ background: 'rgba(99,102,241,0.1)', border: '1px solid rgba(99,102,241,0.25)' }}>
    <p className="mb-1.5 text-xs" style={{ color: 'rgba(255,255,255,0.45)' }}>
      {/* 建议回复 */}
      建议回复
    </p>
    <p className="text-sm text-text-1">{selectedConv.suggested_reply}</p>
    <button disabled
      className="mt-2 rounded-lg bg-brand px-3 py-1 text-xs text-white opacity-40 cursor-not-allowed">
      {/* 发送（在 Boss直聘 App 手动发送） */}
      发送
    </button>
  </div>
)}
```

## 验收标准

- [ ] `cd code && pytest` 全部通过，无新增 failure
- [ ] `cd code/dashboard/frontend && npm run build` 无报错、无 TypeScript 错误
- [ ] 新建 `hr_conversations` 表时包含 `intent` 和 `suggested_reply` 列
- [ ] 已存在的 `hr_conversations` 表经迁移后也有这两列
- [ ] `upsert_hr_conversation` 不会覆盖 `intent` 和 `suggested_reply`（LLM 分析结果持久化）
- [ ] W2 check workflow Phase 2c 正确执行：有 HR 消息的会话会调用 LLM 分析
- [ ] `GET /api/conversations/pending-replies` 返回有 `suggested_reply` 的会话列表
- [ ] `POST /api/conversations/{conv_id}/dismiss-reply` 清空 suggested_reply
- [ ] `GET /api/conversations` 在每条记录中包含 `intent` 和 `suggested_reply` 字段
- [ ] Dashboard 的 `PendingRepliesCard` 仅在有待处理回复时显示
- [ ] "复制"按钮点击后短暂显示"已复制✓"，"已发送"后条目消失
- [ ] Chat 页面会话列表显示意图徽章（仅对有 intent 的会话）
- [ ] Chat 页面详情面板显示建议回复卡片，"发送"按钮 disabled
- [ ] `rejection` 意图不改变 `applications.status`（仅存 `intent` 字段）
- [ ] `interview_invite` 意图调用 `tracker.update_status(job_id, AppStatus.INTERVIEW)`
