// Checkpoint 1 (job-approval screen) must show which resume will be sent if a
// job gets approved -- see services/resume_matcher.py and the resume field
// added to GET /api/checkpoint1/jobs. This test only checks that the page
// renders what the backend already decided; it does not re-implement any
// matching logic.
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { PendingJob } from '@/api'

function job(overrides: Partial<PendingJob> = {}): PendingJob {
  return {
    id: 1,
    site_name: 'bambulab',
    url: 'https://x/1',
    title: 'Game Design Role',
    company: 'TestCo',
    category: 'product',
    category_agent: 'product',
    why: '',
    jd: '',
    status: 'pending',
    reason: null,
    found_at: '2026-08-20T00:00:00',
    decided_at: null,
    is_golden: false,
    bucket: '',
    resume: { slug: 'game01', name: '\u6e38\u620f\u5c97\u7248', matched: true, reason: '', pdf_state: 'ready' },
    ...overrides,
  }
}

const SITES = {
  bambulab: {
    site_name: 'bambulab',
    approved_here: 0,
    approved_by_bucket: {},
    buckets: [],
    fill_pending: 0,
    limits: [],
    brief: null,
  },
}

let mockJobs: PendingJob[] = []

vi.mock('@/api', () => ({
  API: {
    getCheckpoint1Jobs: () =>
      Promise.resolve({ jobs: mockJobs, total: mockJobs.length, categories: ['product'], sites: SITES }),
    browseUrl: () => Promise.resolve({ ok: true }),
  },
}))

import CrossSiteApplications from './CrossSiteApplications'

describe('Checkpoint 1 job row shows which resume will be sent', () => {
  afterEach(cleanup)

  it('shows the matched resume name and a ready pdf state', async () => {
    mockJobs = [job()]
    render(<CrossSiteApplications />)

    expect(await screen.findByText('\u6e38\u620f\u5c97\u7248')).not.toBeNull()
    expect(screen.getByText('\u53ef\u53d1\u9001')).not.toBeNull()
    expect(screen.queryByText('\u515c\u5e95')).toBeNull()
  })

  it('marks a fallback pick (matched=false) visibly', async () => {
    mockJobs = [
      job({
        title: 'Ops Specialist',
        resume: { slug: 'game01', name: '\u6e38\u620f\u5c97\u7248', matched: false, reason: 'no match', pdf_state: 'ready' },
      }),
    ]
    render(<CrossSiteApplications />)

    expect(await screen.findByText('\u515c\u5e95')).not.toBeNull()
  })

  it('makes a non-ready pdf state (e.g. missing) visible', async () => {
    mockJobs = [
      job({ resume: { slug: 'game01', name: '\u6e38\u620f\u5c97\u7248', matched: true, reason: '', pdf_state: 'missing' } }),
    ]
    render(<CrossSiteApplications />)

    expect(await screen.findByText('\u672a\u5bfc\u51fa')).not.toBeNull()
  })

  it('renders gracefully when there is no resume at all (slug empty)', async () => {
    mockJobs = [
      job({ resume: { slug: '', name: '', matched: false, reason: 'no resume', pdf_state: 'missing' } }),
    ]
    render(<CrossSiteApplications />)

    expect(await screen.findByText('\u6ca1\u6709\u53ef\u53d1\u7684\u7b80\u5386')).not.toBeNull()
  })
})
