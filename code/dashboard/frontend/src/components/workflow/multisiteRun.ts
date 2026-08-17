import type { ProgressEvent } from '@/hooks/useWorkflowStream'

export type StageStatus = 'pending' | 'running' | 'done' | 'error'

const TERMINAL: Record<string, StageStatus> = {
  done: 'done',
  error: 'error',
  skipped: 'done',
}

// RunView 拿到的 events 是**共享的 SSE 缓冲**，里面混着别的 workflow 的事件——
// 现有 buildTree 自己 filter 了一遍，正说明这一点。三层视图必须先过这一道：
// 不过滤时最直接的后果是从 events 里找 step==='start' 取 run_id，会捞到 w1/w2
// 那次 run 的 start，失败快照的下载链接就指向了错误的 run。
export function forWorkflow(events: ProgressEvent[], workflowId: string): ProgressEvent[] {
  return events.filter((e) => e.workflow === workflowId)
}

// 一个阶段的状态：有终态事件就用它；只有 agent 活动说明正在跑；都没有就是还没走到。
export function stageStatuses(
  events: ProgressEvent[],
  stages: string[],
): Record<string, StageStatus> {
  const out: Record<string, StageStatus> = {}
  for (const s of stages) out[s] = 'pending'
  for (const ev of events) {
    if (!(ev.step in out)) continue
    if (ev.seq != null) {
      if (out[ev.step] === 'pending') out[ev.step] = 'running'
      continue
    }
    const terminal = TERMINAL[ev.status]
    if (terminal) out[ev.step] = terminal
    else if (ev.status === 'running' && out[ev.step] === 'pending') out[ev.step] = 'running'
  }
  return out
}

export interface StageSummary {
  status: StageStatus
  durationMs: number | null
  data: Record<string, unknown>
}

// 一个阶段自己的产出：跑了多久 + 它往 run 日志里记了什么。
//
// **为什么需要它**：第 3 层原来只渲染 `seq != null` 的事件，于是 `ensure_ready`
// （确定性代码，没有 agent 循环）看起来完全是空的，`write_pending_jobs` 跑完也没有
// 任何总结——而这些数据一直都在 step 事件里，只是没有落点。
//
// 只认**终态**的 step 事件（`seq == null` 且状态是终态）。agent 步的 seq 非 null，
// 拿它当总结会把 detail 里的 record 当成阶段产出渲染出去。
export function stageSummary(events: ProgressEvent[], step: string): StageSummary | null {
  const ev = events.find((e) => e.step === step && e.seq == null && TERMINAL[e.status])
  if (!ev) return null
  return {
    status: TERMINAL[ev.status],
    durationMs: ev.duration_ms ?? null,
    data: (ev.detail ?? {}) as Record<string, unknown>,
  }
}

// 整轮 run 的总结（run_end 的 summary）。空对象当没有——渲染一个空块比不渲染更糟。
// 注意实时 SSE 的 done 事件只有 message（字符串化的 dict）、没有 detail；结构化的那份
// 要等 run 停下、WorkflowCard 切到回放事件之后才拿得到。
export function runSummary(events: ProgressEvent[]): Record<string, unknown> | null {
  const ev = events.find((e) => e.step === 'done' && e.seq == null)
  const data = (ev?.detail ?? {}) as Record<string, unknown>
  return Object.keys(data).length > 0 ? data : null
}

// 第 3 层：某个阶段里 agent 的每一轮，按 seq 升序，**不去重**。
// 现有 buildTree 按 tool 名存 Map、后来者覆盖，而 take_snapshot 一次 run 调几十次。
export function agentRows(events: ProgressEvent[], step: string): ProgressEvent[] {
  return events
    .filter((e) => e.seq != null && e.step === step)
    .sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0))
}
