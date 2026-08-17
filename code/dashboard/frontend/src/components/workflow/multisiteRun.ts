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

// 第 3 层：某个阶段里 agent 的每一轮，按 seq 升序，**不去重**。
// 现有 buildTree 按 tool 名存 Map、后来者覆盖，而 take_snapshot 一次 run 调几十次。
export function agentRows(events: ProgressEvent[], step: string): ProgressEvent[] {
  return events
    .filter((e) => e.seq != null && e.step === step)
    .sort((a, b) => (a.seq ?? 0) - (b.seq ?? 0))
}
