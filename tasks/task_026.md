# Task 026 — Dashboard 页 + WorkflowPanel + WorkflowTrack

## 背景

task_025 完成了 React 骨架（布局、API 层、SSE hook、Context），所有页面目前为空占位。
本 task 实现 Dashboard 页面的完整功能，包括统计卡片、WorkflowPanel（触发 W2/W3 workflow）和 WorkflowTrack（实时进度轨道）。

同时顺手修掉 task_025 review 指出的两处占位文字（Topbar 和 Sidebar 副标题）。

---

## 涉及文件

**新建：**
- `code/dashboard/frontend/src/components/workflow/WorkflowPanel.tsx`
- `code/dashboard/frontend/src/components/workflow/WorkflowTrack.tsx`

**修改：**
- `code/dashboard/frontend/src/pages/Dashboard.tsx` — 从占位升级为完整页面
- `code/dashboard/frontend/src/components/layout/Topbar.tsx` — 去掉 "Frontend scaffold..." 占位文字
- `code/dashboard/frontend/src/components/layout/Sidebar.tsx` — 去掉 "React workspace shell" 占位文字

---

## 一、Topbar.tsx 修改

删除第 39 行的占位 `<p>` 标签（`"Frontend scaffold for upcoming page tasks."`）。
保留 `<h1>` 页面标题，`<div>` 布局结构不变。

---

## 二、Sidebar.tsx 修改

将 `"React workspace shell"` 改为 `"AI 求职助手"`。

---

## 三、WorkflowPanel.tsx

路径：`src/components/workflow/WorkflowPanel.tsx`

### 功能说明

统一参数面板，包含 Apply 参数组、Check 参数组、共享参数（headless）和三个触发按钮。
触发时从 AppContext 读取 `workflowRunning`（如不为 null 则禁用所有按钮）。
触发成功后通过 SSE 事件自动更新状态（Context 中的 `setWorkflowRunning` 已由 App.tsx 的 SSE 监听处理，WorkflowPanel 不需要再主动轮询）。

### 参数布局

```
┌─ Workflow 配置 ──────────────────────────────────────────────────┐
│  Apply ─────────────────────  Check ────────────────────────────  │
│  limit:           [30]       max_conversations:  [30]             │
│  score_threshold:  [0]       days:              [7]               │
│  □ dry_run                                                        │
│  □ generate_resume                                                │
│ ─────────────────────────────────────────────────────────────── │
│  □ 无头模式（不弹出浏览器窗口）                                  │
│ ─────────────────────────────────────────────────────────────── │
│  [▶ 开始投递]    [▶ 扫描回复]    [⚡ 全流程]                      │
└──────────────────────────────────────────────────────────────────┘
```

### 组件接口

```tsx
// 无 props，所有状态内置
export default function WorkflowPanel()
```

### 内部状态

```tsx
const [limit, setLimit] = useState(30)
const [scoreThreshold, setScoreThreshold] = useState(0)
const [dryRun, setDryRun] = useState(false)
const [generateResume, setGenerateResume] = useState(false)
const [maxConversations, setMaxConversations] = useState(30)
const [days, setDays] = useState(7)
const [headless, setHeadless] = useState(true)
const [pending, setPending] = useState<'apply' | 'check' | 'all' | null>(null)
const [error, setError] = useState<string | null>(null)
```

从 Context 读取：`const { workflowRunning, progressEvents } = useAppContext()`

### 三个按钮的行为

**开始投递（apply）：**
```tsx
await API.triggerApplyWorkflow({
  limit,
  score_threshold: scoreThreshold,
  dry_run: dryRun,
  generate_resume: generateResume,
  headless,
})
```

**扫描回复（check）：**
```tsx
await API.triggerCheckWorkflow({
  max_conversations: maxConversations,
  days,
  headless,
})
```

**全流程（all）：**
1. 先调用 `API.triggerApplyWorkflow(...)` 启动 apply
2. 在 `progressEvents` 中监听 `step === 'workflow_done' && workflow === 'apply'`（或 status === 'done' && workflow === 'apply'）触发后，再调用 `API.triggerCheckWorkflow(...)`
3. 用 `useEffect` 监听 `progressEvents` 变化实现链式触发

具体实现方式：
```tsx
const runAllPhase = useRef<'idle' | 'waiting_for_apply_done'>('idle')

// 在 apply 按钮 handler 中，如果是全流程模式：
runAllPhase.current = 'waiting_for_apply_done'
await API.triggerApplyWorkflow(...)

// 在 useEffect 监听 progressEvents 中：
useEffect(() => {
  if (runAllPhase.current !== 'waiting_for_apply_done') return
  const last = progressEvents[progressEvents.length - 1]
  if (last && last.workflow === 'apply' && last.step === 'workflow_done') {
    runAllPhase.current = 'idle'
    API.triggerCheckWorkflow({ max_conversations: maxConversations, days, headless })
      .catch(e => setError(e.message))
  }
}, [progressEvents, maxConversations, days, headless])
```

### 错误处理

任何 `API.trigger*` 抛出时，捕获并将 `e.message` 设置到 `error` state，显示在面板顶部（红色小字）。

### 禁用逻辑

- `workflowRunning !== null`：三个按钮全部 disabled
- `pending !== null`：三个按钮全部 disabled
- 正在 pending 的按钮显示 loading 文字（"投递中..." / "扫描中..." / "执行中..."）

### 样式

- 卡片：`rounded-2xl border border-border-subtle bg-bg-card p-6`
- 参数组 label：`text-xs font-medium uppercase tracking-wider text-text-3 mb-3`
- 参数行 label：`text-sm text-text-2 w-36`
- 数字输入框：`w-20 rounded-lg border border-border-default bg-bg-input px-3 py-1.5 text-sm text-text-1`
- checkbox label：`flex items-center gap-2 text-sm text-text-2 cursor-pointer select-none`
- 分割线：`border-t border-border-subtle my-4`
- 按钮行：`flex items-center gap-3 mt-4`
- 开始投递：`rounded-xl border border-border-default bg-bg-card2 px-5 py-2.5 text-sm font-medium text-text-1 hover:bg-bg-hover disabled:opacity-50 disabled:cursor-not-allowed transition`
- 扫描回复：同上
- 全流程：`rounded-xl bg-brand px-5 py-2.5 text-sm font-medium text-white shadow-[0_0_24px_rgba(91,127,255,0.24)] hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition`

---

## 四、WorkflowTrack.tsx

路径：`src/components/workflow/WorkflowTrack.tsx`

### 功能说明

实时展示最近一次 workflow 的分步进度。从 AppContext 的 `progressEvents` 读取事件，
渲染成"地铁线路图"风格的步骤列表。

### 步骤定义

```tsx
// W2 (apply) 步骤
const W2_STEPS = ['search', 'score', 'resume', 'apply'] as const

// W3 (check) 步骤
const W3_STEPS = ['open_chat', 'classify', 'update_status'] as const

type StepStatus = 'pending' | 'running' | 'done' | 'skipped' | 'error'

interface StepState {
  status: StepStatus
  message: string
}
```

### 渲染逻辑

从 `progressEvents` 中提取两个 workflow 的各步骤最新状态：

```tsx
const w2Steps = useMemo(() => buildStepStates(W2_STEPS, progressEvents, 'apply'), [progressEvents])
const w3Steps = useMemo(() => buildStepStates(W3_STEPS, progressEvents, 'check'), [progressEvents])

function buildStepStates<S extends string>(
  steps: readonly S[],
  events: ProgressEvent[],
  workflow: string,
): Record<S, StepState> {
  const result = Object.fromEntries(steps.map(s => [s, { status: 'pending', message: '' }])) as Record<S, StepState>
  for (const ev of events) {
    if (ev.workflow !== workflow) continue
    if (steps.includes(ev.step as S)) {
      result[ev.step as S] = {
        status: ev.status as StepStatus,
        message: ev.message,
      }
    }
  }
  return result
}
```

### 步骤节点样式

每个步骤节点包含：竖线（连接线）+ 圆点（状态颜色）+ 步骤名 + 最新消息

状态点颜色：
- `pending`：`bg-text-3`（灰色）
- `running`：`bg-brand animate-pulse`（品牌蓝，闪烁）
- `done`：`bg-emerald-400`（绿色）
- `skipped`：`bg-text-3`（灰色，与 pending 相同）
- `error`：`bg-rose-400`（红色）

步骤名标签：
```
search → 搜索
score  → 评分
resume → 简历
apply  → 投递
open_chat → 扫描会话
classify  → 分类处理
update_status → 状态更新
```

消息文字：`text-xs text-text-3`，最多显示 2 行，超出省略。

### 无事件时

如果 `progressEvents.length === 0`，显示：
```tsx
<p className="text-sm text-text-3">尚无进度数据，触发 Workflow 后显示。</p>
```

### 布局

两个 workflow 并排（Apply / Check），各自一列，用 `grid grid-cols-1 gap-6 sm:grid-cols-2`。

---

## 五、Dashboard.tsx

路径：`src/pages/Dashboard.tsx`

### 布局结构

```
┌── Dashboard ───────────────────────────────────────────────────┐
│  [Stats 卡片行：4个]                                            │
│                                                                 │
│  ┌─ WorkflowPanel ──────────────────┐  ┌─ WorkflowTrack ────┐  │
│  └───────────────────────────────────┘  └────────────────────┘  │
└────────────────────────────────────────────────────────────────┘
```

下方两栏用 `grid grid-cols-1 gap-6 lg:grid-cols-[2fr_1fr]`。

### Stats 卡片

用 `API.getStats()` 获取，`useEffect` 挂载时调用一次，加 30s 轮询刷新。

显示 4 张卡片：

| 标题 | 数据字段 |
|------|---------|
| 总职位 | `stats.total` |
| 今日投递 | `stats.applied_today` / `stats.daily_limit`（显示为 "X / Y"） |
| 已获回复 | `stats.responded` |
| 面试/Offer | `stats.interviews + stats.offers` |

卡片样式：
```
rounded-2xl border border-border-subtle bg-bg-card p-5
标题：text-sm text-text-2
数字：text-2xl font-semibold text-text-1 mt-1
```

stats 加载中显示 `--`，加载失败显示 `-`。

### 完整代码骨架

```tsx
export default function Dashboard() {
  const [stats, setStats] = useState<Stats['stats'] | null>(null)

  useEffect(() => {
    const load = () => API.getStats().then(d => setStats(d.stats)).catch(() => {})
    load()
    const id = window.setInterval(load, 30_000)
    return () => window.clearInterval(id)
  }, [])

  return (
    <div className="space-y-6">
      {/* Stats 卡片行 */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard title="总职位" value={stats?.total} />
        <StatCard title="今日投递" value={stats ? `${stats.applied_today} / ${stats.daily_limit}` : undefined} />
        <StatCard title="已获回复" value={stats?.responded} />
        <StatCard title="面试/Offer" value={stats ? (stats.interviews ?? 0) + (stats.offers ?? 0) : undefined} />
      </div>

      {/* 主内容区 */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[2fr_1fr]">
        <WorkflowPanel />
        <WorkflowTrack />
      </div>
    </div>
  )
}

function StatCard({ title, value }: { title: string; value?: string | number }) {
  return (
    <div className="rounded-2xl border border-border-subtle bg-bg-card p-5">
      <p className="text-sm text-text-2">{title}</p>
      <p className="mt-1 text-2xl font-semibold text-text-1">
        {value === undefined ? '--' : value}
      </p>
    </div>
  )
}
```

---

## 六、构建验证

完成后在 `code/dashboard/frontend/` 执行：

```bash
npm run build
```

确认无 TypeScript 错误，`../static/` 正常生成。

---

## 约束

- 不修改 `server.py`、后端任何文件
- 不安装新的 npm 包（使用已有的 lucide-react、clsx、tailwind-merge）
- SSE 全流程链路已由 App.tsx 处理，WorkflowPanel 只需监听 `progressEvents`（从 Context 读取）
- 所有字符串直接写 UTF-8 中文，不使用 `\uXXXX` escape
- `API.getStats()` 的返回类型中 `stats` 字段已在 `api/index.ts` 定义为 `Record<string, unknown>`，Dashboard 使用时用 `as` 断言或局部 interface

---

## 验证点

1. `npm run build` 通过
2. Dashboard 页显示 4 个统计卡片（显示 `--` 时 API 未返回也不报错）
3. WorkflowPanel 参数可修改，按钮在有 workflow 运行时禁用
4. 开始投递/扫描回复触发后，WorkflowTrack 实时显示步骤进度
5. Topbar 不再显示 "Frontend scaffold..." 占位文字
6. Sidebar 副标题显示 "AI 求职助手"
