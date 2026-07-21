# W3 Pipeline Design — 发送已批准回复

把"对 HR 发送已批准回复"从 W2 抽出成独立 workflow。**只负责出站发送 + 投递验证**，不生成草稿（草稿仍由 W2 起草）、不发简历（仍在 W2）。

> 背景：W2 的 ReplyStep 把"执行了输入框插字+Enter"当成功，不验证真投递 → 假成功（标 sent 还清空正文，实际没发出，多行回复 Enter 被当换行尤甚）；且靠滚动遍历定位会话，沉底/脆匹配会找不到。W3 用**搜索框定位 + 投递验证**根治。

状态说明：✅ 已确认 | ⏳ 实现阶段定

---

## 职责边界 ✅

| 工作流 | 职责 |
|--------|------|
| W2（检查回应） | scan / read / analyze intent / **起草草稿**(needs_reply→pending) / **发简历**(已验证，不动) / finalize |
| **W3（本文，发送回复）** | 取 approved/revision 回复 → **搜索定位** → 发送 → **验证投递** → 仅验证到才 mark_sent |

**状态机零迁移**：`reply_status` 链不变 `null →(W2起草) pending →(人工) approved/revision →(W3验证投递) sent` / `dismissed`。W3 只读 `approved`+`revision`。无新增列。

---

## 总体结构 ✅

```
W3Pipeline.run(config)
│
├── LoadApprovedStep                       [一次：取待发回复 + 导航到聊天列表]
│
├── SendReplyPipeline × replies            [per 已批准回复]
│   ├── LocateStep                         [搜索框定位并打开会话]
│   ├── SendStep                           [输入框发送 reply_text]
│   └── VerifyStep                         [验证投递 → mark_sent / 失败保留 approved]
│
└── (pipeline summary)                     [located / sent / failed 计数]
```

`run_w3()`（`pipeline/w3_runner.py`）仿 `w2_runner`：load profile → `open_browser` → `VerifySessionStep` → 建 `ToolRegistry` → 注册 tools → `W3Pipeline.run()` → `close_browser`。走 registry `set_context` → 自动 trace/SSE，仪表盘可观测。

---

## StepOutput 基类（复用，见 w2_pipeline.md / logging.md）✅

```python
class StepStatus(Enum):
    SUCCESSFUL = "successful"; DEGRADED = "degraded"; SKIPPED = "skipped"; FAILED = "failed"

@dataclass
class StepOutput:
    status: StepStatus
    error: Optional[str] = None
```

---

## W3Config ✅

```python
@dataclass
class W3Config:
    dry_run: bool = False          # True：定位+inspect 但不真正发送/不 mark_sent
    max_replies: int = 50          # 单次最多处理多少条待发回复（保险）
```

---

## LoadApprovedStep ✅（Step 方向定，Tool 复用）

**目的**：取出所有待发回复，并导航到聊天列表（后续 LocateStep 在此页搜索）。

```python
@dataclass
class LoadApprovedStepInput:
    pass

@dataclass
class ApprovedReply:
    conv_id: str
    company: str
    hr_name: str
    reply_text: str
    boss_conv_id: str        # 历史遗留，恒为列表 ID，不可用于直跳；仅透传

@dataclass
class LoadApprovedStepOutput(StepOutput):
    replies: List[ApprovedReply]     # reply_status ∈ (approved, revision) 且 reply_text 非空
    chat_list_ready: bool
```

`on_error`: ABORT_WORKFLOW（取不到列表/导航失败则整轮无意义）
**内部执行**：
```
1. Tool: GetApprovedReplies          → reply_status IN ('approved','revision')，过滤掉 reply_text 为空的（防御）
2. 若 replies 为空 → 直接结束（status=SUCCESSFUL, replies=[]）
3. Tool: NavigateToChatList          → 落到 /web/geek/chat，等列表容器
```

---

## SendReplyPipeline（per reply）✅

**目的**：完整发送一条已批准回复：定位 → 发送 → 验证 → 落状态。

```python
@dataclass
class SendReplyPipelineInput:
    reply: ApprovedReply

@dataclass
class SendReplyPipelineOutput(StepOutput):
    conv_id: str
    located: bool
    submitted: bool          # 动作已执行（不代表投递成功）
    delivered: bool          # 验证到真投递
    marked_sent: bool
    failure_reason: Optional[str]   # locate_failed | submit_failed | deliver_unverified | null
```

`on_error`: SKIP（单条失败不影响其余；失败的**保留 approved、不清正文**）

控制流：
```
loc = LocateStep
if not loc.located:  → 记 failure_reason=locate_failed，结束（保留 approved）
snd = SendStep
if not snd.submitted: → 记 submit_failed，结束（保留 approved）
ver = VerifyStep      （内含：verify → 若 delivered 则 MarkReplySent）
if not ver.delivered: → 记 deliver_unverified，结束（保留 approved、不清正文）
else: marked_sent=True
```

---

## LocateStep ✅（Tool 新增①）

**目的**：用聊天列表搜索框定位并打开指定会话（替代脆弱的滚动遍历）。

```python
@dataclass
class LocateStepInput:
    conv_id: str
    company: str
    hr_name: str

@dataclass
class LocateStepOutput(StepOutput):
    located: bool
    boss_conv_id_confirmed: str     # 打开后从 URL ?conversationId= 读到的真实 ID（可空）
```

`on_error`: SKIP
Tool: `SearchLocateConversation`（兜底回退见"待处理"）

---

## SendStep ✅（Tool 复用，含多行修复）

**目的**：在已打开会话的输入框发送 reply_text。

```python
@dataclass
class SendStepInput:
    conv_id: str
    reply_text: str
    dry_run: bool

@dataclass
class SendStepOutput(StepOutput):
    submitted: bool         # 仅表示"提交动作完成"，真投递由 VerifyStep 判
```

`on_error`: SKIP
Tool: `SendChatMessage`（**多行提交修复**：见"待处理"——优先点发送按钮，而非 insertText 后裸 Enter）
dry_run=True 时跳过实际提交，submitted=False。

---

## VerifyStep ✅（Tool 新增②）

**目的**：验证回复真的作为"我方"消息出现在对话里；仅验证到才把状态翻 sent。

```python
@dataclass
class VerifyStepInput:
    conv_id: str
    reply_text: str
    dry_run: bool

@dataclass
class VerifyStepOutput(StepOutput):
    delivered: bool
    marked_sent: bool
```

`on_error`: CONTINUE_DEGRADED（验证失败 = 不确定投递 → 保留 approved、不清正文）
Tools: `ReadMessages`（重扫会话，最多重试 4 次等气泡渲染）→ `WriteHRMessages`（回写 DB）→（重扫结果里存在 sender==me 且匹配 reply_text 的气泡 且非 dry_run 时）`MarkReplySent`

> **验证机制（2026-06-20 改）**：不再用独立的 DOM 前缀探测 tool（旧 `VerifyReplyDelivered` 已删除——它只看 DOM、不落库，且存在匹配历史气泡的假阳性）。改为复用 W2 的 `read_messages` 重扫整条会话 + `write_hr_messages` 回写 hr_messages，再在**刚读到的消息**里确认存在一条 `sender==me` 且文本（去空白后前 16 字符）匹配 reply_text 的气泡。一举两得：投递验证 + 数据同步（发出去的消息进库）。匹配判定在 Python 端（code decides）。

---

# Tools

## 新增 — BrowserTools（W3 专用）

### ① SearchLocateConversation
**目的**：往聊天列表搜索框输入关键词，过滤后点中目标会话卡片打开它。
搜索框实测：`input.boss-search-input`（在 `.boss-search-container`/`.boss-search-top` 内），placeholder「搜索30天内的联系人」——**按联系人搜、仅覆盖 30 天内**。
```json
Input:  { "conv_id": "string", "company": "string", "hr_name": "string" }
Output: {
  "ok": "bool",
  "located": "bool",
  "boss_conv_id_confirmed": "string  // 打开后 URL 的 conversationId，可空",
  "matched_count": "int  // 搜索过滤后命中的卡片数",
  "error": "string|null"
}
```
执行：清空并输入 company → 等列表过滤（轮询 `.friend-content-warp` 变化）→ 在过滤结果里按 `company`(name-box span[1]) + `hr_name`(.name-text) 精确匹配 → 点内层 `.friend-content` → 等会话打开 → 读 URL `?conversationId=`。company 无果时再试 hr_name。均无 → located=False（含 >30 天搜不到）。

> ~~② VerifyReplyDelivered~~ — **已删除（2026-06-20）**。投递验证改为复用 W2 的 `read_messages`+`write_hr_messages`（见上方 Verify step 说明）。W3 只剩 1 个专用 tool（SearchLocateConversation）。

## 复用 — 已有 Tools（不新写）

| Tool | 位置 | Input → Output（要点） |
|------|------|------------------------|
| GetApprovedReplies | db/w2 | `{}` → `{ conversations:[{conv_id,hr_name,company,reply_text,boss_conv_id}], count }`，WHERE reply_status IN ('approved','revision') |
| NavigateToChatList | browser/w2 | `{force?}` → `{ ok, loaded_url, navigated }` |
| SendChatMessage | browser/w2 | `{conv_id, text}` → `{ ok, error }`（**多行提交待修**） |
| MarkReplySent | db/w2 | `{conv_id}` → `{ ok }`，UPDATE reply_status='sent', reply_text='' |
| ReadMessages | browser/w2 | `{}` → `{ message_count, messages:[{sender,text,time}] }`（Verify 重扫会话） |
| WriteHRMessages | db/w2 | `{conv_id, messages}` → `{ inserted_count }`，INSERT OR IGNORE 去重（Verify 回写） |
| VerifySessionStep | pipeline/common | — → `{status, username, reason, error}`（run_w3 开场校验） |

---

## 触发 & 接线 ✅

- 后端入口：`POST /api/workflow/reply` → `_run_reply_workflow` → `run_w3`（仿 apply/check 三触发路径：手动 / 定时 / CLI `main.py --reply`）。
- 前端：会话页或控制台加「发送已批准回复」按钮（触发 W3）。
- 串联（可选）：人工审批后手动触发；不与 W2 自动串联（发送须人工批准在前）。

---

## 已确认
- ✅ 边界：W2 起草 + 发简历不动；W3 只做"发送已批准回复 + 验证投递"
- ✅ 状态机零迁移；W3 读 approved/revision
- ✅ 结构：LoadApprovedStep → SendReplyPipeline(Locate→Send→Verify) per reply
- ✅ 假成功根治：Verify 必须在重扫会话里看到我方已发消息才 MarkReplySent，否则保留 approved 不清正文
- ✅ 新增 1 个 tool：SearchLocateConversation；投递验证复用 w2 的 read_messages+write_hr_messages（2026-06-20 弃用独立的 VerifyReplyDelivered）

## 待处理（实现阶段）
- [ ] **SendChatMessage 多行提交**：先 inspect 聊天输入框 + 发送按钮 DOM；优先点发送按钮，或正确 Enter keydown（排查"多行被当换行未提交"）
- [ ] **SearchLocateConversation 兜底**：搜不到时是否回退旧滚动 `NavigateToConversation`（覆盖 >30 天会话）——v1 先不回退、报 located=False，后续评估
- [ ] 各 Step/Tool 的 emits 规格（logging.md，实现阶段填）
- [ ] 前端触发按钮 + `/api/workflow/reply` 接线（实现阶段）
