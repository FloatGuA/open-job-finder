// Checkpoint 2 \u7684\u4e09\u4ef6\u4e8b\uff1a\u770b\u5f97\u5230\u6765\u6e90\u5c97\u4f4d\u3001\u770b\u5f97\u5230\u5b83\u7684 JD\u3001run \u8dd1\u5b8c\u81ea\u52a8\u5237\u65b0\u3002
//
// \u7528\u6237 2026-08-21 \u4e00\u6b21\u70b9\u4e86\u4e09\u6837\uff1a\u2460\u8fd0\u884c\u4e2d\u7684\u5b9e\u65f6\u540c\u6b65 \u2461\u5ba1\u6279\u9875\u7f3a\u7684\u4fe1\u606f\uff08C2 \u770b\u4e0d\u5230 JD\uff09
// \u2462\u4e24\u4e2a Checkpoint \u4e4b\u95f4\u7684\u4e32\u8054\u3002\u4e09\u8005\u662f\u4e00\u6761\u7ebf\u2014\u2014\u2462 \u7684 source_job_id \u6253\u901a\u4e86\uff0c
// \u2461 \u7684 JD \u624d\u6709\u5730\u65b9\u6765\u3002
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PendingApplication, PendingJob } from '@/api'

const SOURCE_JOB = {
  id: 75,
  site_name: 'bambulab',
  url: 'https://x/src',
  title: '\u670d\u52a1\u8fd0\u8425 - \u6570\u636e\u5206\u6790',
  company: '\u62d3\u7af9',
  category: '\u8fd0\u8425',
  category_agent: '\u8fd0\u8425',
  why: '\u5bf9\u4e0a\u4e86\u8fd0\u8425\u65b9\u5411',
  jd: '\u5c97\u4f4d\u63cf\u8ff0\n\u8d1f\u8d23\u6570\u636e\u770b\u677f\u642d\u5efa',
  status: 'approved',
  reason: null,
  found_at: '2026-08-20T00:00:00',
  decided_at: '2026-08-20T01:00:00',
  is_golden: false,
  bucket: '',
  resume: { file: '', name: '', matched: false, reason: '', pdf_state: 'missing' },
} as unknown as PendingJob

function anApp(overrides: Partial<PendingApplication> = {}): PendingApplication {
  return {
    id: 1, site_name: 'bambulab', job_title: '\u670d\u52a1\u8fd0\u8425 - \u6570\u636e\u5206\u6790', company: '\u62d3\u7af9',
    job_url: 'https://x/1', fields: [], status: 'pending', reason: null,
    created_at: '2026-08-21T11:02:54', decided_at: null, source_job_id: 75,
    screenshot: '', resume_file: 'r.pdf', ...overrides,
  }
}

let mockApps: PendingApplication[] = []
let sourceJobCalls: number[] = []
let sourceJobOk = true
let streamCb: ((e: { workflow: string; step: string; status: string; message: string }) => void) | null = null
let listCalls = 0

vi.mock('@/hooks/useWorkflowStream', () => ({
  useWorkflowStream: (cb: never) => { streamCb = cb },
}))

vi.mock('@/api', () => ({
  API: {
    getCheckpoint1Jobs: () => Promise.resolve({ jobs: [], total: 0, categories: [], sites: {} }),
    getPendingApplications: () => {
      listCalls += 1
      return Promise.resolve({ applications: mockApps, total: mockApps.length })
    },
    getApplicationSourceJob: (id: number) => {
      sourceJobCalls.push(id)
      return sourceJobOk ? Promise.resolve(SOURCE_JOB) : Promise.reject(new Error('404'))
    },
    browseUrl: () => Promise.resolve({ ok: true }),
  },
}))

import CrossSiteApplications from './CrossSiteApplications'

async function openDetail() {
  render(<CrossSiteApplications />)
  fireEvent.click(screen.getByText('\u5b57\u6bb5\u5ba1\u6279'))
  fireEvent.click(await screen.findByText('\u670d\u52a1\u8fd0\u8425 - \u6570\u636e\u5206\u6790'))
}

describe('Checkpoint 2 links back to the job it came from', () => {
  beforeEach(() => { sourceJobCalls = []; sourceJobOk = true; listCalls = 0; streamCb = null })
  afterEach(cleanup)

  it('fetches the source job only when a row is selected', async () => {
    mockApps = [anApp()]
    render(<CrossSiteApplications />)
    fireEvent.click(screen.getByText('\u5b57\u6bb5\u5ba1\u6279'))
    await screen.findByText('\u670d\u52a1\u8fd0\u8425 - \u6570\u636e\u5206\u6790')
    // \u8fd8\u6ca1\u70b9\u5f00\u4efb\u4f55\u4e00\u6761 \u2014\u2014 JD \u6709\u51e0\u5343\u5b57\uff0c\u4e0d\u8be5\u5728\u5217\u8868\u9636\u6bb5\u5c31\u62c9
    expect(sourceJobCalls).toEqual([])

    fireEvent.click(screen.getByText('\u670d\u52a1\u8fd0\u8425 - \u6570\u636e\u5206\u6790'))
    await waitFor(() => expect(sourceJobCalls).toEqual([1]))
  })

  it('shows the jd of the source job', async () => {
    mockApps = [anApp()]
    await openDetail()
    expect(await screen.findByText(/\u8d1f\u8d23\u6570\u636e\u770b\u677f\u642d\u5efa/)).toBeTruthy()
  })

  it('shows why that job was picked', async () => {
    mockApps = [anApp()]
    await openDetail()
    expect(await screen.findByText(/\u5bf9\u4e0a\u4e86\u8fd0\u8425\u65b9\u5411/)).toBeTruthy()
  })

  it('renders nothing about the source when there is none', async () => {
    // --job-url \u8c03\u8bd5\u8def\u5f84\uff0c\u6216\u6765\u6e90\u5c97\u4f4d\u5df2\u88ab\u5220 \u2014\u2014 \u8bda\u5b9e\u7684\u7a7a\uff0c\u4e0d\u662f\u663e\u793a\u4e00\u4e2a\u7a7a\u58f3
    sourceJobOk = false
    mockApps = [anApp({ source_job_id: null })]
    await openDetail()
    await waitFor(() => expect(screen.queryByText(/\u8d1f\u8d23\u6570\u636e\u770b\u677f\u642d\u5efa/)).toBeNull())
    expect(screen.queryByText(/\u6765\u6e90\u5c97\u4f4d/)).toBeNull()
  })
})

describe('Checkpoint 2 refreshes while a run is going', () => {
  beforeEach(() => { sourceJobCalls = []; sourceJobOk = true; listCalls = 0; streamCb = null })
  afterEach(cleanup)

  it('re-fetches when a run finishes', async () => {
    mockApps = [anApp()]
    render(<CrossSiteApplications />)
    fireEvent.click(screen.getByText('\u5b57\u6bb5\u5ba1\u6279'))
    await screen.findByText('\u670d\u52a1\u8fd0\u8425 - \u6570\u636e\u5206\u6790')
    const before = listCalls

    streamCb?.({ workflow: 'm2', step: 'done', status: 'done', message: '' })
    await waitFor(() => expect(listCalls).toBeGreaterThan(before))
  })

  it('does not re-fetch on every tool event', async () => {
    // SSE \u4f1a\u6210\u767e\u4e0a\u5343\u6761\u5730\u6d8c\u8fdb\u6765\uff08debug \u6a21\u5f0f\u6bcf\u6b21 registry.call \u4e00\u6761\uff09\u2014\u2014
    // \u6bcf\u6761\u90fd\u5237\u65b0\u4f1a\u628a\u5ba1\u6279\u9875\u5237\u7206\u3002\u53ea\u5728 run \u7ed3\u675f/\u5199\u5e93\u90a3\u51e0\u4e2a\u8282\u70b9\u5237\u3002
    mockApps = [anApp()]
    render(<CrossSiteApplications />)
    fireEvent.click(screen.getByText('\u5b57\u6bb5\u5ba1\u6279'))
    await screen.findByText('\u670d\u52a1\u8fd0\u8425 - \u6570\u636e\u5206\u6790')
    const before = listCalls

    for (let i = 0; i < 50; i++) {
      streamCb?.({ workflow: 'm2', step: 'open_application', status: 'running', message: '' })
    }
    await new Promise((r) => setTimeout(r, 50))
    expect(listCalls).toBe(before)
  })
})
