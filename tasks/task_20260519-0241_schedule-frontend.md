# Task: Schedule Frontend — Dashboard Schedule Card

## 目标

在 Dashboard 主页（`dashboard/frontend/src/pages/Dashboard.tsx`）底部新增 ScheduleCard 组件，展示 W1/W2 自动调度配置、下次触发时间、近期调度日志。调度运行时的进度条复用现有 WorkflowPanel（SSE 已常驻，无需改动）。

## 背景

- Task `task_20260519-0241_schedule-backend` 已实现后端 API：`GET /api/schedule`、`PUT /api/schedule`、`GET /api/schedule/log`
- `WorkflowPanel` / `WorkflowTrack` 已通过 `useWorkflowStream` 常驻 SSE，无需修改
- 现有 API 方法 `triggerApplyWorkflow`（POST /api/workflow/apply）和 `triggerCheckWorkflow`（POST /api/workflow/check）已在 `src/api/index.ts` 行 121-132 定义，直接复用，**禁止修改**
- 项目使用 React 18 + TypeScript + Tailwind CSS v3，卡片风格：`rounded-2xl bg-bg-card p-5 shadow-card`

## 关键约束：CJK 字符串转义

所有写入 .tsx/.ts 文件的字符串字面量中的 CJK 字符必须用 `\uXXXX` 形式（Windows GBK 工具链会静默损坏裸 UTF-8 中文）。由于本 spec 本身无法预先转义代码模板（Write 工具会将 `\uXXXX` 解码为实际 Unicode 字符），代码模板中的 CJK 字面量**必须通过 Section 3 的后处理脚本转义**。Section 3 是强制步骤，不可跳过。

## 实现要求

### 1. `code/dashboard/frontend/src/api/index.ts`

在已有 `export interface Profile` 之后新增（纯 ASCII，无 CJK）：

```typescript
export interface ScheduleWorkflowConfig {
  enabled: boolean
  times: string[]
  interval_hours: number
  params: Record<string, unknown>
}

export interface ScheduleConfig {
  apply: ScheduleWorkflowConfig
  check: ScheduleWorkflowConfig
  _next_runs?: Record<string, string | null>
  _scheduler_running?: boolean
}

export type SchedulePayload = {
  apply?: Partial<ScheduleWorkflowConfig>
  check?: Partial<ScheduleWorkflowConfig>
}

export interface ScheduleLogEntry {
  workflow: string
  trigger_type: string
  triggered_at: string
  result: 'success' | 'skipped' | 'error'
  skipped_reason: string | null
  summary: string | null
  duration_seconds: number
}
```

在 `API` 对象末尾（`saveLlmConfig` 之后，闭合 `}` 之前）新增：

```typescript
  getSchedule: (): Promise<ScheduleConfig> =>
    requestJson('/api/schedule'),

  updateSchedule: (body: SchedulePayload): Promise<ScheduleConfig> =>
    requestJson<{ ok: boolean; config: ScheduleConfig }>('/api/schedule', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((r) => r.config),

  getScheduleLog: (limit = 20): Promise<ScheduleLogEntry[]> =>
    requestJson<{ log: ScheduleLogEntry[] }>(`/api/schedule/log?limit=${limit}`)
      .then((r) => r.log),
```

### 2. `code/dashboard/frontend/src/pages/Dashboard.tsx`

#### 2a. 修改顶部 import

将 `import { useEffect, useState } from 'react'` 改为：
```typescript
import { useCallback, useEffect, useState } from 'react'
```

在 `import { API } from '@/api'` 之后追加：
```typescript
import type { ScheduleConfig, ScheduleLogEntry } from '@/api'
```

#### 2b. 辅助函数（放在 `export default function Dashboard` 之前）

以下代码直接原样写入文件（其中含有字面中文），**必须在所有文件编辑完成后执行 Section 3 的后处理脚本转义，不得跳过**：

```typescript
function formatNextRun(iso: string | null | undefined): string {
  if (!iso) return '暂无计划'
  const d = new Date(iso)
  const diffMin = Math.round((d.getTime() - Date.now()) / 60000)
  if (diffMin < 1) return '即将触发'
  if (diffMin < 60) return `${diffMin}分钟后`
  const h = Math.floor(diffMin / 60)
  const m = diffMin % 60
  return m > 0 ? `${h}h ${m}min 后` : `${h}h 后`
}

function formatLogTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}
```

#### 2c. WfScheduleState interface + WorkflowScheduleSection 组件

以下代码直接原样写入文件（其中含有字面中文），**必须通过 Section 3 后处理步骤转义**：

```typescript
interface WfScheduleState {
  enabled: boolean
  times: string[]
  interval_hours: number
  params: Record<string, unknown>
}

function WorkflowScheduleSection({
  label,
  state,
  onChange,
  nextRun,
  log,
  onApply,
  saving,
}: {
  label: string
  state: WfScheduleState
  onChange: (u: Partial<WfScheduleState>) => void
  nextRun: string | null | undefined
  log: ScheduleLogEntry[]
  onApply: (runNow: boolean) => void
  saving: boolean
}) {
  const [runNow, setRunNow] = useState(false)
  const [newTime, setNewTime] = useState('')

  const addTime = () => {
    if (!newTime) return
    if (!state.times.includes(newTime))
      onChange({ times: [...state.times, newTime].sort() })
    setNewTime('')
  }

  return (
    <div
      className="rounded-xl p-4"
      style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }}
    >
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm font-semibold text-text-1">{label}</span>
        <button
          type="button"
          onClick={() => onChange({ enabled: !state.enabled })}
          className="flex h-5 w-9 items-center rounded-full transition-colors"
          style={{ background: state.enabled ? '#0071e3' : 'rgba(255,255,255,0.15)' }}
          aria-label={state.enabled ? '关闭' : '启用'}
        >
          <span
            className="ml-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform"
            style={{ transform: state.enabled ? 'translateX(16px)' : 'translateX(0)' }}
          />
        </button>
      </div>

      <div className="mb-2">
        <p className="mb-1 text-xs text-text-3">{'定时触发'}</p>
        <div className="mb-1.5 flex flex-wrap gap-1.5">
          {state.times.map((t) => (
            <span
              key={t}
              className="flex items-center gap-1 rounded-lg px-2 py-0.5 text-xs"
              style={{ background: 'rgba(0,113,227,0.18)', color: '#60a5fa' }}
            >
              {t}
              <button
                type="button"
                onClick={() => onChange({ times: state.times.filter((x) => x !== t) })}
                className="leading-none text-text-3 hover:text-red-400"
              >
                &times;
              </button>
            </span>
          ))}
        </div>
        <div className="flex items-center gap-1.5">
          <input
            type="time"
            value={newTime}
            onChange={(e) => setNewTime(e.target.value)}
            className="rounded-lg px-2 py-1 text-xs text-white"
            style={{
              background: 'rgba(255,255,255,0.08)',
              border: '1px solid rgba(255,255,255,0.12)',
              width: '100px',
            }}
          />
          <button
            type="button"
            onClick={addTime}
            className="rounded-lg px-2 py-1 text-xs text-text-2 transition hover:text-white"
            style={{ background: 'rgba(255,255,255,0.08)' }}
          >
            {`+ 添加`}
          </button>
        </div>
      </div>

      <div className="mb-3 flex items-center gap-2">
        <p className="whitespace-nowrap text-xs text-text-3">{'间隔'}</p>
        <input
          type="number"
          min={0}
          max={168}
          value={state.interval_hours}
          onChange={(e) =>
            onChange({ interval_hours: Math.max(0, parseInt(e.target.value, 10) || 0) })
          }
          className="w-14 rounded-lg px-2 py-1 text-xs text-white"
          style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)' }}
        />
        <span className="text-xs text-text-3">{'小时一次 (0=不启用)'}</span>
      </div>

      <div className="mb-3 flex items-center gap-2">
        <span className="text-xs text-text-3">{'下次触发：'}</span>
        <span
          className="text-xs font-medium"
          style={{ color: nextRun ? '#34d399' : 'rgba(255,255,255,0.35)' }}
        >
          {formatNextRun(nextRun)}
        </span>
      </div>

      <div className="mb-3 flex items-center gap-3">
        <label className="flex cursor-pointer items-center gap-1.5">
          <input
            type="checkbox"
            checked={runNow}
            onChange={(e) => setRunNow(e.target.checked)}
            className="rounded"
          />
          <span className="text-xs text-text-2">{'保存后立刻启动一次'}</span>
        </label>
        <button
          type="button"
          disabled={saving}
          onClick={() => onApply(runNow)}
          className="ml-auto rounded-xl px-4 py-1.5 text-xs font-semibold text-white transition disabled:opacity-50"
          style={{ background: '#0071e3' }}
        >
          {saving ? '保存中…' : '应用'}
        </button>
      </div>

      {log.length > 0 && (
        <div>
          <p className="mb-1 text-xs text-text-3">{'近期记录'}</p>
          <div className="space-y-0.5">
            {log.slice(0, 5).map((entry, i) => {
              const icon =
                entry.result === 'success' ? '✓' : entry.result === 'skipped' ? '▷' : '✕'
              const color =
                entry.result === 'success'
                  ? '#34d399'
                  : entry.result === 'skipped'
                  ? '#94a3b8'
                  : '#f87171'
              return (
                <div key={i} className="flex items-start gap-2 text-xs leading-relaxed">
                  <span style={{ color, minWidth: '12px' }}>{icon}</span>
                  <span className="shrink-0 text-text-3">{formatLogTime(entry.triggered_at)}</span>
                  <span className="truncate text-text-2">
                    {entry.result === 'skipped'
                      ? `跳过：${entry.skipped_reason ?? ''}`
                      : entry.result === 'error'
                      ? `错误：${entry.summary ?? ''}`
                      : `${entry.summary ?? ''} ${entry.duration_seconds ? `(${entry.duration_seconds}s)` : ''}`}
                  </span>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
```

#### 2d. ScheduleCard 组件（紧接 WorkflowScheduleSection 之后）

以下代码直接原样写入文件（其中含有字面中文），**必须通过 Section 3 后处理步骤转义**：

```typescript
function ScheduleCard() {
  const [apply, setApply] = useState<WfScheduleState>({
    enabled: false,
    times: [],
    interval_hours: 0,
    params: {
      limit: 30,
      score_threshold: 60,
      apply_limit: 0,
      dry_run: false,
      headless: true,
      generate_resume: false,
    },
  })
  const [check, setCheck] = useState<WfScheduleState>({
    enabled: false,
    times: [],
    interval_hours: 0,
    params: { max_conversations: 200, days: 7, headless: true },
  })
  const [nextRuns, setNextRuns] = useState<Record<string, string | null>>({})
  const [log, setLog] = useState<ScheduleLogEntry[]>([])
  const [schedulerRunning, setSchedulerRunning] = useState(false)
  const [savingApply, setSavingApply] = useState(false)
  const [savingCheck, setSavingCheck] = useState(false)

  const load = useCallback(async () => {
    try {
      const [cfg, logEntries] = await Promise.all([
        API.getSchedule() as Promise<ScheduleConfig>,
        API.getScheduleLog(20),
      ])
      setApply({
        enabled: cfg.apply.enabled,
        times: cfg.apply.times,
        interval_hours: cfg.apply.interval_hours,
        params: cfg.apply.params,
      })
      setCheck({
        enabled: cfg.check.enabled,
        times: cfg.check.times,
        interval_hours: cfg.check.interval_hours,
        params: cfg.check.params,
      })
      setNextRuns(cfg._next_runs ?? {})
      setSchedulerRunning(cfg._scheduler_running ?? false)
      setLog(logEntries)
    } catch {
      // non-fatal
    }
  }, [])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const id = window.setInterval(() => void load(), 30_000)
    return () => window.clearInterval(id)
  }, [load])

  const handleApply = async (
    wf: 'apply' | 'check',
    state: WfScheduleState,
    setSaving: (v: boolean) => void,
    runNow: boolean,
  ) => {
    setSaving(true)
    try {
      await API.updateSchedule({
        [wf]: {
          enabled: state.enabled,
          times: state.times,
          interval_hours: state.interval_hours,
          params: state.params,
        },
      })
      if (runNow) {
        if (wf === 'apply') {
          await API.triggerApplyWorkflow({ ...state.params })
        } else {
          await API.triggerCheckWorkflow({ ...state.params })
        }
      }
      await load()
    } catch {
      // non-fatal
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-2xl bg-bg-card p-5 shadow-card">
      <div className="mb-4 flex items-center justify-between">
        <p className="text-xs text-text-3" style={{ letterSpacing: '-0.12px' }}>
          {'自动调度'}
        </p>
        <span
          className="flex items-center gap-1.5 text-xs"
          style={{ color: schedulerRunning ? '#34d399' : '#94a3b8' }}
        >
          <span
            className="inline-block h-1.5 w-1.5 rounded-full"
            style={{ background: schedulerRunning ? '#34d399' : '#94a3b8' }}
          />
          {schedulerRunning ? '调度器运行中' : '未启动'}
        </span>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <WorkflowScheduleSection
          label={'W1 投递'}
          state={apply}
          onChange={(u) => setApply((p) => ({ ...p, ...u }))}
          nextRun={nextRuns['apply']}
          log={log.filter((e) => e.workflow === 'apply')}
          onApply={(runNow) => void handleApply('apply', apply, setSavingApply, runNow)}
          saving={savingApply}
        />
        <WorkflowScheduleSection
          label={'W2 检查'}
          state={check}
          onChange={(u) => setCheck((p) => ({ ...p, ...u }))}
          nextRun={nextRuns['check']}
          log={log.filter((e) => e.workflow === 'check')}
          onApply={(runNow) => void handleApply('check', check, setSavingCheck, runNow)}
          saving={savingCheck}
        />
      </div>
    </div>
  )
}
```

#### 2e. 在 Dashboard 主函数 return 中插入 ScheduleCard

在 `export default function Dashboard()` 的 return JSX 末尾（外层容器闭合之前）追加：
```tsx
<ScheduleCard />
```

### 3. CJK 转义后处理（必须执行，不可省略，即使文件看起来已经正确）

Sections 2b/2c/2d 的代码模板中含有字面中文。所有文件编辑完成后，**无论如何**都必须在 `code/dashboard/frontend` 目录下运行以下命令，将两个文件中所有非 ASCII 字符替换为 `\uXXXX` 字面序列。不允许以"已经转义"为由跳过本步骤：

```bash
cd dashboard/frontend && python -c "
import re
for path in ['src/pages/Dashboard.tsx', 'src/api/index.ts']:
    with open(path, 'r', encoding='utf-8') as f:
        text = f.read()
    def esc(m):
        return ''.join(chr(92) + 'u' + format(ord(ch), '04x') for ch in m.group())
    escaped = re.sub(r'[^\x00-\x7f]+', esc, text)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(escaped)
    print('Escaped:', path)
"
```

运行后验证（在同一 `code/dashboard/frontend` 目录下，应输出 `OK: no bare CJK found`）：
```bash
cd dashboard/frontend && python -c "
import re
files = ['src/pages/Dashboard.tsx', 'src/api/index.ts']
found = False
for p in files:
    with open(p, encoding='utf-8') as f:
        text = f.read()
    m = re.search(r'[^\x00-\x7f]', text)
    if m:
        print('FAIL:', p, repr(m.group()))
        found = True
if not found:
    print('OK: no bare CJK found')
"
```

### 4. 细节约束

- `ScheduleCard.load()` 用 `useCallback([])` 包裹（空依赖），30s 刷新 effect 依赖 `[load]`
- `WorkflowScheduleSection` 不直接调用 API，所有 API 调用集中在 `ScheduleCard.handleApply`
- `API.triggerApplyWorkflow` / `API.triggerCheckWorkflow` 已存在，禁止修改
- Step 3 的 CJK 后处理脚本必须在所有文件编辑完成后执行，且必须验证通过（输出 `OK: no bare CJK found`）才视为完成
- 后端响应结构（已在后端 task 中定义）：`PUT /api/schedule` → `{ ok: bool, config: ScheduleConfig }`；`GET /api/schedule/log` → `{ log: ScheduleLogEntry[], total: int }`；api 层写法与此一致

## 验收标准

- [ ] Dashboard 主页底部出现"自动调度"卡片，W1/W2 两栏并列（md 宽度以上）
- [ ] 每个区块：enable 开关、时间点标签（可删除）、添加时间点、间隔小时数输入、下次触发时间、"保存后立刻启动一次"复选框、"应用"按鈕
- [ ] 近期记录：✓/▷/✕ 图标、时间、摘要（skipped 显示跳过原因）
- [ ] 卡片右上角：调度器状态 + 绿/灰色指示点
- [ ] 点击"应用"调用 `PUT /api/schedule`，成功后刷新；保存中按鈕 disabled
- [ ] 勾选"保存后立刻启动一次"点击"应用"，额外调用对应 trigger API
- [ ] `npm run build` 无 TypeScript 编译错误
- [ ] `grep -P "[\x{4e00}-\x{9fff}]" src/pages/Dashboard.tsx src/api/index.ts` 返回空
