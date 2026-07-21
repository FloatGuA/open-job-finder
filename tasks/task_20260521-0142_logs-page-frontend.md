# Task: 前端 Logs 页（历史运行记录查看）

## 目标

新增 `src/pages/Logs.tsx`，展示历史 workflow run 列表及每次 run 的分层事件流；在 `Sidebar.tsx` 和 `App.tsx` 中注册新页面。

## 背景

`task_20260521-0140_event-log-core` 已实现 `GET /api/runs` 和 `GET /api/runs/{run_id}` 端点。前端需要一个专用页面消费这两个 API。

**注意**：所有 CJK 字符串必须使用 `\uXXXX` 转义（JSX 文本节点用 `{'\uXXXX'}`，JS 字符串字面量直接转义，JSX 属性用 JS 表达式 `label={'\uXXXX'}` 不能用双引号字符串）。

## 实现要求

### 1. `code/dashboard/frontend/src/api/index.ts` — 新增类型和函数

```typescript
export interface RunSummary {
  run_id: string
  workflow: 'apply' | 'check'
  filename: string
  started_at: string
  ended_at: string | null
  status: 'done' | 'error' | 'running'
  summary: Record<string, unknown> | null
}

export interface RunsResponse {
  runs: RunSummary[]
  total: number
}

export interface RunEvent {
  ts: string
  run_id: string
  workflow: string
  event_type: string
  visible: boolean
  data: Record<string, unknown>
}

export interface RunDetailResponse {
  run_id: string
  events: RunEvent[]
  total: number
}
```

新增 API 方法（加入现有 `API` 对象）：

```typescript
getRuns: (params?: { workflow?: string }): Promise<RunsResponse>
getRunDetail: (runId: string, params?: { visible_only?: boolean }): Promise<RunDetailResponse>
```

---

### 2. `code/dashboard/frontend/src/pages/Logs.tsx`（新建）

**布局**：左右双栏，与 Chat.tsx 的双栏结构类似。

**左栏（run 列表，宽约 260px，固定高度可滚动）**：
- 顶部 workflow 筛选器：三个按钮 `全部 / Apply / Check`（`全部` / `Apply` / `Check`）
- 每个 RunSummary 渲染一行，点击后加载详情：
  - 主行：workflow badge（Apply=蓝，Check=绿）+ 开始时间（本地时间格式 `MM-DD HH:mm`）
  - 副行：status badge（done=绿/error=红/running=amber）+ summary 关键字段（如 `applied: 5, seen: 30`）

**右栏（事件详情，flex-1）**：
- 顶部：run_id（前8位）+ 时间范围 + 展开开关（`仅显示摘要 / 显示全部` = `仅显示摘要` / `显示全部`）
- 事件列表（时间线样式，时间戳 + 事件 badge + data 摘要）：
  - 默认只渲染 `visible=true` 的事件（Job 层）
  - 展开后渲染全部事件（含 Action 层 `visible=false`）
  - `workflow_start` / `workflow_end`：全宽行，加粗显示 workflow + 状态
  - `card_scored` / `card_applied`：显示 `company · title · score/decision`
  - `card_skipped`：显示 reason
  - `hr_checked` / `intent_analyzed`：显示 hr_name + company + intent
  - 其他：event_type + JSON.stringify(data) 截断到 120 字符
- 无选中 run 时：居中提示文字 `选择左侧的运行记录查看详情`（选择左侧的运行记录查看详情）

**状态管理**（局部 useState，无需 context）：
- `runs: RunSummary[]`
- `selectedRunId: string | null`
- `events: RunEvent[]`
- `showAll: boolean`（展开开关）
- `wfFilter: '' | 'apply' | 'check'`
- `loading: boolean`（events 加载中）

**数据加载**：
- `useEffect([])` 时调用 `API.getRuns()` 加载列表
- 点击 run 时调用 `API.getRunDetail(runId)` 加载全量事件（不过滤，本地按 showAll 切换）

---

### 3. `code/dashboard/frontend/src/components/layout/Sidebar.tsx` — 新增 Logs 导航项

在现有 `items` 数组中，在 `chat` 之后、`profile` 之前插入：

```typescript
{ page: 'logs', title: '运行日志', icon: ScrollText },
```

从 `lucide-react` 导入 `ScrollText`。

---

### 4. `code/dashboard/frontend/src/App.tsx` — 注册 logs 页

在 `Page` 类型中添加 `'logs'`：
- `app-context.tsx`（若 Page 类型定义在此）或 `App.tsx` 中的 `PAGE_COMPONENTS`

`PAGE_COMPONENTS` 添加：
```typescript
logs: <Logs />,
```

---

### 5. `code/dashboard/frontend/src/context/app-context.ts`

将 `Page` 类型扩展为包含 `'logs'`：

```typescript
export type Page = 'dashboard' | 'jobs' | 'chat' | 'logs' | 'profile' | 'setup'
```

---

## 验收标准

- [ ] `npm run build` 零错误
- [ ] 侧边栏出现"运行日志"导航项，点击切换到 Logs 页
- [ ] Logs 页左栏列出 `logs/runs/` 下的 run 记录（后端无记录时显示空列表，无报错）
- [ ] 点击 run 后右栏渲染事件时间线
- [ ] 展开开关切换"仅摘要/全部"正确过滤 visible 事件
- [ ] `pytest tests/` 全部通过（无回归）
