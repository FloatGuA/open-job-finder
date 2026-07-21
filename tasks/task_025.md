# Task 025 — React + Vite + Tailwind 初始化 + 布局骨架 + API 层 + SSE hook

## 背景

现有前端是单文件 vanilla JS（`dashboard/static/app.js` ~1500 行），维护成本高，状态管理混乱。
本 task 搭建新的 React 前端骨架，目标：可运行、可构建、FastAPI 能正常 serve，且包含完整的布局组件和 API 层，后续页面 task 可以直接在此基础上填充内容。

**不实现任何具体页面内容**——只搭架子。

---

## 技术栈

- React 18 + TypeScript
- Vite（构建工具）
- Tailwind CSS v3（样式）
- shadcn/ui（组件库，本 task 仅初始化，不大量使用）

---

## 目录结构目标

```
code/dashboard/frontend/
├── package.json
├── vite.config.ts          # outDir: "../static", base: "/"
├── tailwind.config.ts
├── postcss.config.js
├── tsconfig.json
├── tsconfig.node.json
├── index.html              # Vite 入口 HTML
└── src/
    ├── main.tsx
    ├── App.tsx             # 路由 + 布局
    ├── api/
    │   └── index.ts        # 所有 fetch 调用
    ├── hooks/
    │   └── useWorkflowStream.ts   # SSE + polling
    ├── components/
    │   └── layout/
    │       ├── Sidebar.tsx
    │       └── Topbar.tsx
    └── pages/
        ├── Dashboard.tsx   # 空占位
        ├── Jobs.tsx        # 空占位
        ├── Chat.tsx        # 空占位
        ├── Profile.tsx     # 空占位
        └── Setup.tsx       # 空占位
```

---

## 实施步骤

### Step 1：初始化项目

在 `code/dashboard/` 目录下执行：

```bash
npm create vite@latest frontend -- --template react-ts
cd frontend
npm install
npm install -D tailwindcss@3 postcss autoprefixer
npx tailwindcss init -p
npm install @radix-ui/react-slot class-variance-authority clsx tailwind-merge lucide-react
```

### Step 2：配置文件

**`vite.config.ts`**：
```typescript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/api': 'http://localhost:8765',
    },
  },
})
```

**`tailwind.config.ts`**：
```typescript
import type { Config } from 'tailwindcss'

const config: Config = {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          DEFAULT: '#5B7FFF',
          dim: 'rgba(91,127,255,0.12)',
          glow: 'rgba(91,127,255,0.24)',
        },
        bg: {
          page: '#0B0D17',
          card: '#13162B',
          card2: '#1A1E36',
          input: '#1A1E36',
          hover: '#1F2440',
          active: '#252840',
        },
        text: {
          1: '#F0F2FF',
          2: '#8892BB',
          3: '#555E85',
        },
        border: {
          subtle: 'rgba(255,255,255,0.06)',
          default: 'rgba(255,255,255,0.12)',
        },
      },
    },
  },
  plugins: [],
}

export default config
```

**`src/index.css`**（替换默认内容）：
```css
@tailwind base;
@tailwind components;
@tailwind utilities;

* { box-sizing: border-box; margin: 0; padding: 0; }
body { background-color: #0B0D17; color: #F0F2FF; font-family: 'Inter', system-ui, sans-serif; }
```

**`index.html`**（替换默认 title）：
```html
<!doctype html>
<html lang="zh-CN" class="dark">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>OpenJobFinder</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

---

### Step 3：API 层 `src/api/index.ts`

迁移现有 `static/app.js` 的 `const API = { ... }` 为 TypeScript，完整实现以下函数：

```typescript
// 类型定义
export interface WorkflowStatus { running: string | null }
export interface Stats { stats: Record<string, any>; onboarding: Record<string, any> }
export interface Job { job_id: string; title: string; company: string; city: string; salary: string; score?: number; status: string; applied_at?: string; url: string }
export interface JobsResponse { jobs: Job[]; total: number; page: number; page_size: number }
export interface Conversation { conv_id: string; hr_name: string; company: string; last_msg_preview: string; last_msg_from: string; last_synced: string; stage: string; job_id?: string }
export interface Profile { keywords?: string[]; cities?: string[]; experience?: string[]; degree?: string[]; salary?: string; scale?: string[]; job_types?: string[]; boss_online?: boolean }

// API 函数（所有函数抛出错误而非静默失败）
export const API = {
  getStats: (): Promise<Stats> => fetch('/api/stats').then(handleJson),
  getJobs: (status?: string, page = 1, pageSize = 20): Promise<JobsResponse> => { ... },
  getJob: (id: string): Promise<Job> => fetch(`/api/jobs/${id}`).then(handleJson),
  pause: () => fetch('/api/pause', { method: 'POST' }).then(handleJson),
  resume: () => fetch('/api/resume', { method: 'POST' }).then(handleJson),
  getOnboarding: () => fetch('/api/onboarding/status').then(handleJson),
  uploadResume: (file: File) => { ... },
  getConversations: (stage?: string): Promise<{ conversations: Conversation[] }> => { ... },
  getProfile: (): Promise<Profile> => fetch('/api/profile').then(handleJson),
  saveProfile: (data: Profile) => fetch('/api/profile', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then(handleJson),
  getWorkflowStatus: (): Promise<WorkflowStatus> => fetch('/api/workflow/status').then(handleJson),
  checkSession: () => fetch('/api/check/session').then(handleJson),
  triggerApplyWorkflow: (data: Record<string, unknown>) => fetch('/api/workflow/apply', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then(handleJson),
  triggerCheckWorkflow: (data: Record<string, unknown>) => fetch('/api/workflow/check', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) }).then(handleJson),
  stopWorkflow: () => fetch('/api/workflow/stop', { method: 'POST' }).then(handleJson),
  getControlStatus: () => fetch('/api/control/status').then(handleJson),
  getDistricts: (city?: string) => { ... },
  getPositions: () => fetch('/api/filters/positions').then(handleJson),
  getIndustries: () => fetch('/api/filters/industries').then(handleJson),
}

function handleJson(res: Response) {
  if (!res.ok) return res.json().then(e => Promise.reject(new Error(e.detail || res.statusText)))
  return res.json()
}
```

---

### Step 4：SSE hook `src/hooks/useWorkflowStream.ts`

```typescript
import { useEffect, useRef, useCallback } from 'react'

export interface ProgressEvent {
  workflow: string
  step: string
  status: string
  message: string
  ts?: number
}

export function useWorkflowStream(onEvent: (e: ProgressEvent) => void) {
  const esRef = useRef<EventSource | null>(null)
  const onEventRef = useRef(onEvent)
  onEventRef.current = onEvent

  const connect = useCallback(() => {
    if (esRef.current) return
    const es = new EventSource('/api/workflow/stream')
    es.addEventListener('message', (e) => {
      try { onEventRef.current(JSON.parse(e.data)) } catch (_) {}
    })
    es.onerror = () => {
      es.close()
      esRef.current = null
      setTimeout(connect, 2000)
    }
    esRef.current = es
  }, [])

  useEffect(() => {
    connect()
    return () => { esRef.current?.close(); esRef.current = null }
  }, [connect])
}
```

---

### Step 5：状态管理 Context `src/App.tsx`

```typescript
import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'
import { API } from './api'
import { useWorkflowStream, ProgressEvent } from './hooks/useWorkflowStream'
import Sidebar from './components/layout/Sidebar'
import Topbar from './components/layout/Topbar'
import Dashboard from './pages/Dashboard'
import Jobs from './pages/Jobs'
import Chat from './pages/Chat'
import Profile from './pages/Profile'
import Setup from './pages/Setup'

export type Page = 'dashboard' | 'jobs' | 'chat' | 'profile' | 'setup'

interface AppContextValue {
  page: Page
  setPage: (p: Page) => void
  workflowRunning: string | null
  setWorkflowRunning: (v: string | null) => void
  progressEvents: ProgressEvent[]
}

export const AppContext = createContext<AppContextValue>({} as AppContextValue)
export const useAppContext = () => useContext(AppContext)

export default function App() {
  const [page, setPage] = useState<Page>('dashboard')
  const [workflowRunning, setWorkflowRunning] = useState<string | null>(null)
  const [progressEvents, setProgressEvents] = useState<ProgressEvent[]>([])

  // SSE
  useWorkflowStream((event) => {
    setProgressEvents(prev => [...prev.slice(-200), event])
    if (event.step === 'done' || event.step === 'start') {
      API.getWorkflowStatus().then(d => setWorkflowRunning(d.running)).catch(() => {})
    }
  })

  // 10s polling for state sync
  useEffect(() => {
    const id = setInterval(() => {
      API.getWorkflowStatus().then(d => setWorkflowRunning(d.running)).catch(() => {})
    }, 10_000)
    return () => clearInterval(id)
  }, [])

  // Initial status check
  useEffect(() => {
    API.getWorkflowStatus().then(d => setWorkflowRunning(d.running)).catch(() => {})
  }, [])

  const ctx: AppContextValue = { page, setPage, workflowRunning, setWorkflowRunning, progressEvents }

  return (
    <AppContext.Provider value={ctx}>
      <div className="flex h-screen overflow-hidden bg-bg-page text-text-1">
        <Sidebar />
        <div className="flex flex-col flex-1 overflow-hidden">
          <Topbar />
          <main className="flex-1 overflow-y-auto p-6">
            {page === 'dashboard' && <Dashboard />}
            {page === 'jobs' && <Jobs />}
            {page === 'chat' && <Chat />}
            {page === 'profile' && <Profile />}
            {page === 'setup' && <Setup />}
          </main>
        </div>
      </div>
    </AppContext.Provider>
  )
}
```

---

### Step 6：Sidebar `src/components/layout/Sidebar.tsx`

导航项：Dashboard（◈）/ 职位进度（⊞）/ HR 会话（◎）/ 环境配置（✦）

活跃状态用 `bg-brand-dim text-brand` 高亮，非活跃 `text-text-2 hover:bg-bg-hover hover:text-text-1`。

侧边栏宽度：`w-56`，背景 `bg-bg-card`，右侧 `border-r border-border-subtle`。

底部：Agent 状态点（绿/橙/红）+ 标签文字。

---

### Step 7：Topbar `src/components/layout/Topbar.tsx`

显示当前页面标题，右侧：暂停按钮 + 恢复按钮（调用 `API.pause()` / `API.resume()`）。

---

### Step 8：页面占位

每个页面文件只返回一个带标题的空 div：

```tsx
// Dashboard.tsx
export default function Dashboard() {
  return <div className="text-text-2">Dashboard 页面（task_026 实现）</div>
}
// 其余页面类似
```

---

### Step 9：main.tsx

```typescript
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
)
```

---

### Step 10：构建验证

在 `code/dashboard/frontend/` 目录执行：

```bash
npm run build
```

确认：
1. 无 TypeScript 编译错误
2. `code/dashboard/static/` 目录生成 `index.html` + `assets/` 文件夹
3. 旧的 `static/app.js` 和 `static/style.css` 被 `emptyOutDir: true` 清除

---

## 验证点

1. `npm run build` 成功，无错误
2. 启动 FastAPI：`python -m uvicorn dashboard.server:app --host 0.0.0.0 --port 8765`
3. 访问 `http://localhost:8765`，看到 React 渲染的布局（Sidebar + Topbar + 占位内容）
4. 侧边栏导航点击可切换页面
5. `http://localhost:8765/api/stats` 仍正常返回 JSON（FastAPI API 路由不受影响）

---

## 约束

- 不删除 `dashboard/static/index.html`、`app.js`、`style.css` ——由 `npm run build` 的 `emptyOutDir: true` 自动处理
- 不修改 `dashboard/server.py`
- 不实现任何具体页面功能（留给 task_026~029）
- 所有字符串用英文或直接写 UTF-8 中文（codex 运行环境编码正常，不需要 \uXXXX escape）
