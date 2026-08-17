import { describe, expect, it } from 'vitest'
import type { ProgressEvent } from '@/hooks/useWorkflowStream'
import { agentRows, stageStatuses } from './multisiteRun'

const STAGES = ['ensure_ready', 'find_jobs', 'write_pending_jobs']

function step(name: string, status: string, ts: number): ProgressEvent {
  return { workflow: 'm1', step: name, status, message: '', ts }
}
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
