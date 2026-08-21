// Checkpoint 2\uff08\u586b\u8868\u5ba1\u6279\uff09\u8981\u663e\u793a\u300c\u8fd9\u6b21\u5b9e\u9645\u4f20\u4e0a\u53bb\u7684\u662f\u54ea\u4e00\u4efd\u7b80\u5386\u300d\u3002
//
// \u5ba1\u6279\u4eba\u5728\u8fd9\u4e00\u6b65\u5224\u65ad\u7684\u662f"\u8fd9\u4efd\u7533\u8bf7\u80fd\u4e0d\u80fd\u63d0\u4ea4"\uff0c\u800c**\u53d1\u51fa\u53bb\u7684\u662f\u54ea\u4efd\u7b80\u5386**\u8ddf\u586b\u7684\u5b57\u6bb5
// \u540c\u7b49\u91cd\u8981\u2014\u2014\u5e93\u91cc\u53ef\u80fd\u52fe\u4e86\u597d\u51e0\u4efd\uff0c\u515c\u5e95\u4e5f\u4f1a\u6539\u30022026-08-21 \u771f\u673a\u8dd1\u5b8c m2 \u60f3\u6838\u5bf9
// "\u521a\u624d\u53d1\u7684\u662f\u54ea\u4efd"\uff0c\u53ea\u80fd\u7ffb run \u65e5\u5fd7\u3002
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { PendingApplication } from '@/api'

function app(overrides: Partial<PendingApplication> = {}): PendingApplication {
  return {
    id: 1,
    site_name: 'bambulab',
    job_title: '\u670d\u52a1\u8fd0\u8425 - \u6570\u636e\u5206\u6790',
    company: '\u62d3\u7af9',
    job_url: 'https://x/1',
    fields: [],
    status: 'pending',
    reason: null,
    created_at: '2026-08-21T11:02:54',
    decided_at: null,
    source_job_id: 75,
    screenshot: '',
    resume_file: 'Agent\u5f00\u53d1_2026-08-17.pdf',
    ...overrides,
  }
}

let mockApps: PendingApplication[] = []

vi.mock('@/api', () => ({
  API: {
    getCheckpoint1Jobs: () =>
      Promise.resolve({ jobs: [], total: 0, categories: [], sites: {} }),
    getPendingApplications: () =>
      Promise.resolve({ applications: mockApps, total: mockApps.length }),
    browseUrl: () => Promise.resolve({ ok: true }),
  },
}))

import CrossSiteApplications from './CrossSiteApplications'

// \u8be6\u60c5\u9762\u677f\u53ea\u5728\u9009\u4e2d\u67d0\u6761\u65f6\u6e32\u67d3\uff0c\u800c\u9875\u9762\u9ed8\u8ba4\u505c\u5728\u9009\u5c97\u5ba1\u6279 tab
async function openDetail() {
  render(<CrossSiteApplications />)
  fireEvent.click(screen.getByText('\u5b57\u6bb5\u5ba1\u6279'))
  fireEvent.click(await screen.findByText('\u670d\u52a1\u8fd0\u8425 - \u6570\u636e\u5206\u6790'))
}

describe('Checkpoint 2 shows which resume was uploaded', () => {
  afterEach(cleanup)

  it('names the uploaded resume file', async () => {
    mockApps = [app()]
    await openDetail()
    expect(await screen.findByText(/Agent\u5f00\u53d1_2026-08-17/)).toBeTruthy()
  })

  it('says nothing when no resume was recorded', async () => {
    // \u8001\u8bb0\u5f55\u3001\u4ee5\u53ca\u4e0d\u4f20\u7b80\u5386\u7684\u8def\u5f84 \u2014\u2014 \u7a7a\u4e32\u662f\u8bda\u5b9e\u7684\u7a7a\uff0c\u4e0d\u8be5\u663e\u793a\u6210"\u53d1\u4e86\u4e2a\u7a7a\u7b80\u5386"
    mockApps = [app({ resume_file: '' })]
    await openDetail()
    expect(screen.queryByText(/\u4f20\u7684\u7b80\u5386/)).toBeNull()
  })
})
