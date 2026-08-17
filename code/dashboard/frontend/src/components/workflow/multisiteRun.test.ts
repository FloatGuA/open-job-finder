import { describe, expect, it } from 'vitest'
import type { ProgressEvent } from '@/hooks/useWorkflowStream'
import { agentRows, forWorkflow, stageStatuses } from './multisiteRun'

const STAGES = ['ensure_ready', 'find_jobs', 'write_pending_jobs']

function step(name: string, status: string, ts: number): ProgressEvent {
  return { workflow: 'm1', step: name, status, message: '', ts }
}

describe('forWorkflow', () => {
  // RunView 拿到的 events 是**共享的 SSE 缓冲**，里面混着别的 workflow 的事件
  // （现有 buildTree 自己 filter 了一遍，正说明这一点）。不过滤的后果最直接的一个：
  // 从 events 里找 step==='start' 取 run_id 时，会捞到 w1/w2 那次 run 的 start，
  // 于是失败快照的下载链接指向错误的 run。
  it('drops events belonging to another workflow', () => {
    const mine = step('find_jobs', 'done', 2)
    const foreign: ProgressEvent = {
      workflow: 'w1', step: 'start', status: 'running', message: '', ts: 1,
      detail: { run_id: 'w1_20260817_0900' },
    }
    expect(forWorkflow([foreign, mine], 'm1')).toEqual([mine])
  })

  it('keeps run-level events of the asked workflow', () => {
    const start: ProgressEvent = {
      workflow: 'm1', step: 'start', status: 'running', message: '', ts: 1,
      detail: { run_id: 'm1_20260817_0930' },
    }
    expect(forWorkflow([start], 'm1')).toEqual([start])
  })
})
function agent(name: string, seq: number, tool: string | null, ts: number): ProgressEvent {
  return { workflow: 'm1', step: name, status: 'info', message: '', tool, seq, ts }
}

describe('stageStatuses', () => {
  it('marks an unreached stage as pending', () => {
    expect(stageStatuses([], STAGES).find_jobs).toBe('pending')
  })

  it('marks a stage with agent activity but no terminal event as running', () => {
    const evs = [agent('find_jobs', 0, 'take_snapshot', 1)]
    expect(stageStatuses(evs, STAGES).find_jobs).toBe('running')
  })

  it('marks a stage done on its terminal event', () => {
    const evs = [agent('find_jobs', 0, null, 1), step('find_jobs', 'done', 2)]
    expect(stageStatuses(evs, STAGES).find_jobs).toBe('done')
  })

  it('marks a stage error on failure', () => {
    expect(stageStatuses([step('find_jobs', 'error', 2)], STAGES).find_jobs).toBe('error')
  })
})

describe('agentRows', () => {
  it('keeps every call of the same tool', () => {
    // 这是不能复用现有 buildTree 的原因：它按 tool 名去重，
    // 而 take_snapshot 一次 run 会被调几十次。
    const evs = [
      agent('find_jobs', 0, 'take_snapshot', 1),
      agent('find_jobs', 1, 'take_snapshot', 2),
      agent('find_jobs', 2, 'take_snapshot', 3),
    ]
    expect(agentRows(evs, 'find_jobs')).toHaveLength(3)
  })

  it('only returns rows of the asked stage', () => {
    const evs = [agent('ensure_ready', 0, null, 1), agent('find_jobs', 1, null, 2)]
    expect(agentRows(evs, 'find_jobs').map((e) => e.seq)).toEqual([1])
  })

  it('sorts by seq, not arrival order', () => {
    const evs = [agent('find_jobs', 2, null, 3), agent('find_jobs', 0, null, 1)]
    expect(agentRows(evs, 'find_jobs').map((e) => e.seq)).toEqual([0, 2])
  })

  it('ignores non-agent events', () => {
    expect(agentRows([step('find_jobs', 'done', 1)], 'find_jobs')).toHaveLength(0)
  })
})
