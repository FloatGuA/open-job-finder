// 控制台按 workflow 分页之后要守住的两件事。
//
// ① **切 tab 不能丢掉正在编辑的参数**。现在所有参数都是 panel 顶层的同一组
//    state，所以"什么都不做"就是保留——正因为它是**不做事**换来的，才特别容易在
//    以后某次重构里（把 state 挪进各 tab 子组件）被无声地破坏掉，而表现只是
//    "填了一半切过去看一眼就没了"，没人会觉得那是 bug。
// ② **headless / debug 常驻在 tab 外**：三条流程共用同一个浏览器策略，各 tab
//    一份会出现"在 W1 页关了、切到 M1 又是开的"，而真正传给队列的只有一个值。
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/context/app-context', () => ({
  useAppContext: () => ({ workflowRunning: null }),
}))

vi.mock('@/api', () => ({
  API: {
    getWorkflowDefaults: () => Promise.resolve({ w1: {}, w2: {}, m1: {} }),
    saveWorkflowDefault: () => Promise.resolve({ w1: {}, w2: {}, m1: {} }),
    enqueueWorkflow: () => Promise.resolve({ status: 'started' }),
    triggerApplyWorkflow: () => Promise.resolve({ status: 'started' }),
    triggerCheckWorkflow: () => Promise.resolve({ status: 'started' }),
    triggerReplyWorkflow: () => Promise.resolve({ status: 'started' }),
    enqueueWorkflowChain: () => Promise.resolve({}),
    stopWorkflow: () => Promise.resolve({}),
    clearPendingJobs: () => Promise.resolve({ deleted: 0 }),
  },
}))

import WorkflowPanel from './WorkflowPanel'

// 按 data-tab 定位而不是按文案：「⚡ W1+W2」按钮的文本里也有 "W1"，
// 按名字匹配会同时命中两个元素。
let root: HTMLElement
const tab = (id: string) => root.querySelector(`[data-tab="${id}"]`) as HTMLElement
const numberInput = (label: RegExp) =>
  screen.getByText(label).parentElement!.querySelector('input')! as HTMLInputElement

describe('WorkflowPanel tabs', () => {
  beforeEach(() => {
    root = render(<WorkflowPanel />).container
  })

  // vitest 没开 globals，RTL 的自动 cleanup 不生效——不清理的话上一个用例的 DOM
  // 会留在文档里，表现是"Found multiple elements"而不是断言失败，很容易误诊。
  afterEach(cleanup)

  it('shows one workflow at a time', () => {
    expect(screen.queryByText(/score_threshold/)).not.toBeNull()      // W1 默认页
    expect(screen.queryByText(/max_conversations/)).toBeNull()        // W2 的参数不同时出现
    expect(screen.queryByText(/max_pages/)).toBeNull()                // M1 的也不
  })

  it('switches to the M1 tab', () => {
    fireEvent.click(tab('m1'))
    expect(screen.queryByText(/max_pages/)).not.toBeNull()
    expect(screen.queryByText(/score_threshold/)).toBeNull()
  })

  it('keeps an in-progress edit when you switch away and back', () => {
    const input = numberInput(/score_threshold/)
    fireEvent.change(input, { target: { value: '77' } })

    fireEvent.click(tab('m1'))
    fireEvent.click(tab('w1'))

    expect(numberInput(/score_threshold/).value).toBe('77')
  })

  it('keeps the runtime switches visible on every tab', () => {
    expect(screen.queryByText(/headless/)).not.toBeNull()
    fireEvent.click(tab('m1'))
    expect(screen.queryByText(/headless/)).not.toBeNull()
    fireEvent.click(tab('w2'))
    expect(screen.queryByText(/headless/)).not.toBeNull()
  })
})
