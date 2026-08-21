// 骨架从后端拉，而且**整个页面只拉一次**。
//
// WorkflowTrack 里有两个组件要用它（run 级步骤列表、循环卡片的判定），
// 每个组件各拉一次就是同一份数据的 N 次请求——而这份数据在一次会话里不会变。
import { renderHook, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

let calls = 0

vi.mock('@/api', () => ({
  API: {
    workflowSkeleton: () => {
      calls += 1
      return Promise.resolve({
        steps: { w1: ['navigate', 'scan'] },
        run_steps: { w1: ['navigate'] },
        loop_steps: { w1: ['scan'] },
      })
    },
  },
}))

import { __resetSkeletonCache, useWorkflowSkeleton } from './useWorkflowSkeleton'

describe('useWorkflowSkeleton', () => {
  afterEach(() => {
    calls = 0
    __resetSkeletonCache()
  })

  it('returns what the backend declared', async () => {
    const { result } = renderHook(() => useWorkflowSkeleton())
    await waitFor(() => expect(result.current.run_steps.w1).toEqual(['navigate']))
    expect(result.current.loop_steps.w1).toEqual(['scan'])
  })

  it('starts with empty maps so callers never read undefined', () => {
    // 第一帧还没拿到数据。调用方写的是 `run_steps[workflowId] ?? []`，
    // 但 run_steps 本身是 undefined 的话那行就炸了。
    const { result } = renderHook(() => useWorkflowSkeleton())
    expect(result.current.steps).toEqual({})
    expect(result.current.run_steps).toEqual({})
  })

  it('fetches once no matter how many components use it', async () => {
    const a = renderHook(() => useWorkflowSkeleton())
    const b = renderHook(() => useWorkflowSkeleton())
    await waitFor(() => expect(a.result.current.run_steps.w1).toBeTruthy())
    await waitFor(() => expect(b.result.current.run_steps.w1).toBeTruthy())
    expect(calls).toBe(1)
  })
})
