// \u6bcf\u4e2a\u6876\u6293\u591a\u5c11\u4efd\u5019\u9009\uff0c\u8981\u80fd\u5728\u63a7\u5236\u53f0\u4e0a\u8c03\u3002
//
// \u8fd9\u662f**\u6210\u672c\u65cb\u94ae**\uff1a\u5019\u9009\u6570\u76f4\u63a5\u51b3\u5b9a scan_buckets \u8981\u70b9\u5f00\u591a\u5c11\u4e2a\u8be6\u60c5\u9875\uff0c\u800c\u6bcf\u4e2a\u5c97\u4f4d
// \u5927\u7ea6 8 \u79d2\u3002\u6293\u5c11\u4e86\u4e00\u5c4f\u6ca1\u51e0\u6761\u53ef\u5ba1\uff0c\u6293\u591a\u4e86\u4e00\u6b21 run \u62d6\u6210\u5341\u51e0\u5206\u949f\u2014\u2014\u5408\u9002\u7684\u503c\u8ddf\u7ad9\u70b9
// \u548c\u5f53\u65f6\u60f3\u5e72\u4ec0\u4e48\u6709\u5173\uff08\u5148\u6478\u5f62\u72b6 vs \u6512\u4e00\u6279\u6765\u5ba1\uff09\uff0c\u6ca1\u6709\u4e00\u4e2a\u653e\u4e4b\u56db\u6d77\u7686\u51c6\u7684\u9ed8\u8ba4\u503c\u3002
// \u6b64\u524d\u5b83\u53ea\u80fd\u4ece\u961f\u5217\u53c2\u6570\u4f20\uff0c\u7b49\u4e8e\u53ea\u6709\u6211\u80fd\u8c03\u3001\u4f60\u8c03\u4e0d\u4e86\u3002
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/context/app-context', () => ({
  useAppContext: () => ({ workflowRunning: null }),
}))

const enqueued: Array<[string, Record<string, unknown>]> = []
const savedDefaults: Array<[string, Record<string, unknown>]> = []

vi.mock('@/api', () => ({
  API: {
    getWorkflowDefaults: () => Promise.resolve({ w1: {}, w2: {}, m1: {} }),
    saveWorkflowDefault: (wf: string, updates: Record<string, unknown>) => {
      savedDefaults.push([wf, updates])
      return Promise.resolve({ w1: {}, w2: {}, m1: {} })
    },
    enqueueWorkflow: (wf: string, params: Record<string, unknown>) => {
      enqueued.push([wf, params])
      return Promise.resolve({ status: 'started' })
    },
    triggerApplyWorkflow: () => Promise.resolve({ status: 'started' }),
    triggerCheckWorkflow: () => Promise.resolve({ status: 'started' }),
    triggerReplyWorkflow: () => Promise.resolve({ status: 'started' }),
    enqueueWorkflowChain: () => Promise.resolve({}),
    stopWorkflow: () => Promise.resolve({}),
    clearPendingJobs: () => Promise.resolve({ deleted: 0 }),
  },
}))

import WorkflowPanel from './WorkflowPanel'

let root: HTMLElement
const tab = (id: string) => root.querySelector(`[data-tab="${id}"]`) as HTMLElement
const numberInput = (label: RegExp) =>
  screen.getByText(label).parentElement!.querySelector('input')! as HTMLInputElement
const textInput = (label: string) =>
  screen.getByText(label).parentElement!.querySelector('input')! as HTMLInputElement

describe('candidates_per_bucket is adjustable from the console', () => {
  beforeEach(() => {
    enqueued.length = 0
    savedDefaults.length = 0
    root = render(<WorkflowPanel />).container
    fireEvent.click(tab('m1'))
  })
  afterEach(cleanup)

  it('shows the field on the M1 tab', () => {
    expect(screen.queryByText(/candidates_per_bucket/)).not.toBeNull()
  })

  it('sends what was typed, not the built-in default', async () => {
    // \u7ad9\u70b9 / \u5165\u53e3\u9875 \u4e0d\u586b\u7684\u8bdd\u6309\u94ae\u662f\u7981\u7528\u7684
    fireEvent.change(textInput('\u7ad9\u70b9\u6807\u8bc6'), { target: { value: 'bambulab' } })
    fireEvent.change(textInput('\u5165\u53e3\u9875 URL'), { target: { value: 'https://x/jobs' } })
    fireEvent.change(numberInput(/candidates_per_bucket/), { target: { value: '5' } })
    fireEvent.click(screen.getByText('\u5f00\u59cb\u9009\u5c97'))
    await vi.waitFor(() => expect(enqueued.length).toBe(1))
    expect(enqueued[0][0]).toBe('m1')
    expect(enqueued[0][1].candidates_per_bucket).toBe(5)
  })

  it('is part of what gets saved as the m1 default', async () => {
    fireEvent.change(numberInput(/candidates_per_bucket/), { target: { value: '7' } })
    fireEvent.click(screen.getByText('\u8bbe\u4e3a\u9ed8\u8ba4'))
    await vi.waitFor(() => expect(savedDefaults.length).toBe(1))
    expect(savedDefaults[0][1].candidates_per_bucket).toBe(7)
  })
})
