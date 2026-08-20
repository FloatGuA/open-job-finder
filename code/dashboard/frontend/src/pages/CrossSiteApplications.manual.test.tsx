// \u7ad9\u70b9\u64cd\u4f5c\u624b\u518c\u8981\u5728\u5ba1\u6279\u9875\u770b\u5f97\u89c1\uff0cimportant_notes \u5c24\u5176\u8981\u663e\u773c\u3002
//
// important_notes \u662f agent \u552f\u4e00\u7684\u9003\u751f\u8231\uff1a\u624b\u518c\u5b57\u6bb5\u90fd\u662f\u95ed\u96c6\uff0c\u9047\u5230\u8bbe\u8ba1\u6ca1\u8986\u76d6\u7684\u60c5\u51b5
// \u53ea\u80fd\u5199\u8fdb\u8fd9\u91cc\u3002\u5b83\u6b64\u524d\u5199\u8fdb\u5e93\u4e86\u4f46\u96f6\u6d88\u8d39\u65b9\u2014\u2014\u5199\u4e86\u6ca1\u4eba\u770b\u5f97\u5230\uff0c\u9003\u751f\u8231\u901a\u5411\u4e00\u5835\u5899\u3002
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { PendingJob, SiteManualInfo } from '@/api'

function manual(overrides: Partial<SiteManualInfo> = {}): SiteManualInfo {
  return {
    job_url_source: 'link_in_row',
    url_template: '',
    pagination: 'none',
    filter_interaction: 'direct_click',
    filters_survive_reload: false,
    total_count_locator: '',
    row_split: 'container_per_row',
    row_anchor: 'Apply',
    dimensions: [],
    important_notes: '',
    updated_at: '2026-08-21T01:00:00',
    ...overrides,
  }
}

const JOB: PendingJob = {
  id: 1,
  site_name: 'bambulab',
  url: 'https://x/1',
  title: '\u540e\u7aef\u5de5\u7a0b\u5e08',
  company: 'TestCo',
  category: '\u5f00\u53d1',
  category_agent: '\u5f00\u53d1',
  why: '',
  jd: '',
  status: 'pending',
  reason: null,
  found_at: '2026-08-21T00:00:00',
  decided_at: null,
  is_golden: false,
  bucket: '',
  resume: { slug: 'a', name: '\u540e\u7aef\u7248', matched: true, reason: '', pdf_state: 'ready' },
}

let mockManual: SiteManualInfo | null = null

vi.mock('@/api', () => ({
  API: {
    getCheckpoint1Jobs: () =>
      Promise.resolve({
        jobs: [JOB],
        total: 1,
        categories: ['\u5f00\u53d1'],
        sites: {
          bambulab: {
            site_name: 'bambulab',
            approved_here: 0,
            approved_by_bucket: {},
            buckets: [],
            fill_pending: 0,
            limits: [],
            brief: null,
            manual: mockManual,
          },
        },
      }),
    browseUrl: () => Promise.resolve({ ok: true }),
  },
}))

import CrossSiteApplications from './CrossSiteApplications'

describe('site manual on the approval page', () => {
  afterEach(cleanup)

  it('shows important_notes prominently when the agent wrote one', async () => {
    mockManual = manual({ important_notes: '\u7b5b\u9009\u5668\u8981\u5148\u5c55\u5f00\u5206\u7ec4\u624d\u70b9\u5f97\u5230\uff0c\u5c55\u5f00\u52a8\u4f5c\u6ca1\u6709\u53ef\u89c1\u53cd\u9988' })
    render(<CrossSiteApplications />)
    expect(await screen.findByText(/\u5c55\u5f00\u5206\u7ec4/)).toBeTruthy()
  })

  it('shows nothing about notes when there are none', async () => {
    mockManual = manual()
    render(<CrossSiteApplications />)
    await screen.findByText('\u540e\u7aef\u5de5\u7a0b\u5e08')
    expect(screen.queryByText(/\u73b0\u573a\u53d1\u73b0/)).toBeNull()
  })

  it('renders no manual block for a site that was never surveyed', async () => {
    mockManual = null
    render(<CrossSiteApplications />)
    await screen.findByText('\u540e\u7aef\u5de5\u7a0b\u5e08')
    expect(screen.queryByText(/\u7ad9\u70b9\u624b\u518c/)).toBeNull()
  })

  it('exposes the manual itself so the recorded structure can be checked', async () => {
    mockManual = manual()
    render(<CrossSiteApplications />)
    expect(await screen.findByText(/container_per_row/)).toBeTruthy()
  })
})
