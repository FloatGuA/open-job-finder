# Task 028 — Chat 页（HR 会话列表 + 消息 Thread）

## 背景

task_027 完成了 Jobs 页。本 task 实现"HR 会话"页面（`pages/Chat.tsx`），
展示双栏布局：左侧会话列表，右侧选中会话的消息时间线。

---

## 涉及文件

**修改：**
- `code/dashboard/frontend/src/pages/Chat.tsx` — 从占位升级为完整页面

---

## 一、API 数据结构

`GET /api/conversations` 返回：

```typescript
interface ConversationFull {
  conv_id: string
  hr_name: string
  company: string
  messages: Array<{ sender: 'me' | 'hr'; text: string; time: string }>
  last_msg_text: string
  last_msg_from: string
  last_msg_preview: string
  last_synced: string
  job_id?: string
  status: string   // "new" | "read" | "replied" | "resume_sent"
  stage: string    // "general" | "resume_sent" | "interview" | "closed"
  message_count: number
}
```

现有 `api/index.ts` 的 `Conversation` 接口不含 `messages` 字段，需在 `Chat.tsx` 内定义扩展接口，或直接在 `api/index.ts` 中扩展（推荐后者以便类型共享）。

---

## 二、页面布局

```
┌── HR 会话 ─────────────────────────────────────────────┐
│ ┌─ 会话列表（左列，w-72）──┐ ┌─ 消息 Thread（右列）──┐  │
│ │ [Stage Tabs]            │ │ 标题：company · hr_name│  │
│ │ ─────────────────────── │ │ ──────────────────────── │  │
│ │ 公司名                  │ │ [消息气泡列表]          │  │
│ │ HR名 · 最新消息预览      │ │                         │  │
│ │ ...                     │ │                         │  │
│ └─────────────────────────┘ └─────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

整体：`flex h-full gap-0`（占满 main 区域高度）

左列：`w-72 shrink-0 flex flex-col border-r border-border-subtle`

右列：`flex-1 flex flex-col overflow-hidden`

---

## 三、左列：会话列表

### Stage Tabs

顶部显示 Stage 筛选 Tab 行：

| Tab 标签 | `stage` 参数 |
|----------|-------------|
| 全部     | `undefined` |
| 一般     | `general`   |
| 已发简历 | `resume_sent` |
| 面试     | `interview` |
| 已关闭   | `closed`    |

切换 Tab 时重新调用 `API.getConversations(stage)`。

### 会话列表项

每个会话显示：
- 第一行：`company`（粗体）+ 右侧 `stage` Badge
- 第二行：`hr_name`
- 第三行：`last_msg_preview`（灰色，截断 1 行）

选中状态：`bg-brand-dim`，非选中：`hover:bg-bg-hover`

stage Badge 颜色：
- `interview`：`bg-amber-500/20 text-amber-400`
- `resume_sent`：`bg-emerald-500/20 text-emerald-400`
- `closed`：`bg-text-3/20 text-text-3`
- `general` 或其他：不显示 Badge（或 `bg-text-3/20 text-text-3`）

### 空状态

无会话时显示：`"暂无会话数据"`

---

## 四、右列：消息 Thread

### 未选中时

显示：`"← 选择左侧会话查看消息"`（居中，灰色）

### 已选中时

**顶部标题栏**：`company · hr_name`（`text-sm font-medium`）+ 右侧 `message_count` 条

**消息列表**（可滚动，`overflow-y-auto flex-1`）：

每条消息根据 `sender` 区分：
- `sender === 'me'`：右对齐，蓝色气泡（`bg-brand text-white`）
- `sender === 'hr'`：左对齐，卡片气泡（`bg-bg-card2 text-text-1`）

气泡下方显示 `time`（`text-xs text-text-3`）。

消息时间线从上到下按 `messages` 数组顺序显示（数组已按时间排序）。

---

## 五、数据加载

```tsx
// 顶层：加载所有会话
const [stage, setStage] = useState<string | undefined>(undefined)
const [conversations, setConversations] = useState<ConversationFull[]>([])
const [loading, setLoading] = useState(false)
const [error, setError] = useState<string | null>(null)
const [selectedId, setSelectedId] = useState<string | null>(null)

useEffect(() => {
  setLoading(true)
  setError(null)
  API.getConversations(stage)
    .then(d => setConversations(d.conversations as ConversationFull[]))
    .catch((e: Error) => setError(e.message))
    .finally(() => setLoading(false))
}, [stage])

const selected = conversations.find(c => c.conv_id === selectedId) ?? null
```

选中第一个会话（可选）：当 `conversations` 加载完且当前 `selectedId` 不在新列表中，自动选中第一个。

---

## 六、样式细节

- 左列顶部 tabs：`border-b border-border-subtle px-3 py-2 flex gap-2`，Tab 按钮同 Jobs 页 Tab 样式（`text-xs`）
- 会话列表项：`px-4 py-3 cursor-pointer border-b border-border-subtle last:border-0`
- 消息气泡（我方）：`ml-auto max-w-[75%] rounded-2xl rounded-tr-sm bg-brand px-4 py-2.5 text-sm text-white`
- 消息气泡（HR）：`mr-auto max-w-[75%] rounded-2xl rounded-tl-sm bg-bg-card2 px-4 py-2.5 text-sm text-text-1`
- 消息区域外层：`flex-1 overflow-y-auto px-4 py-4 space-y-4`

---

## 七、api/index.ts 扩展（推荐）

在 `Conversation` 接口中补充 `messages` 和 `message_count` 字段：

```typescript
export interface Conversation {
  conv_id: string
  hr_name: string
  company: string
  last_msg_preview: string
  last_msg_from: string
  last_synced: string
  stage: string
  status: string
  job_id?: string
  message_count?: number
  messages?: Array<{ sender: 'me' | 'hr'; text: string; time: string }>
}
```

---

## 八、构建验证

```bash
cd code/dashboard/frontend
npm run build
```

确认无 TypeScript 错误。

---

## 约束

- 不修改后端任何文件
- 不安装新的 npm 包
- 右列消息区域的滚动用原生 CSS overflow（不引入虚拟滚动库）
- 所有字符串直接写 UTF-8 中文

---

## 验证点

1. `npm run build` 通过
2. 点击"HR 会话"显示左列会话列表（无数据时显示空状态）
3. Stage Tab 切换重新过滤
4. 点击会话列表项，右列显示该会话的消息气泡
5. 我方消息右对齐蓝色，HR 消息左对齐灰色
