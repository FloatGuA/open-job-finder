// Checkpoint 1 \u5fc5\u987b\u628a\u5c97\u4f4d\u539f\u6587\uff08JD\uff09\u4e00\u8d77\u663e\u793a\u51fa\u6765\u2014\u2014\u5ba1\u6279\u8fd9\u4e00\u6b65\u552f\u4e00\u7684\u4eba\u5de5\u51b3\u7b56\u662f
// "\u8fd9\u4e2a\u5c97\u4f4d\u8be5\u4e0d\u8be5\u6295"\uff0c\u800c\u5224\u65ad\u6240\u9700\u7684\u4fe1\u606f\u5fc5\u987b\u90fd\u5728\u8fd9\u4e00\u9875\u4e0a\u3002JD \u662f Plan B \u624d\u5f00\u59cb\u843d\u5e93\u7684
// \uff08job_url_online \u53d6 URL \u65f6\u540c\u4e00\u6b21\u8bbf\u95ee\u987a\u624b\u8bfb\u56de\u6765\uff09\uff0c\u6b64\u524d\u5ba1\u6279\u9875\u53ea\u6709\u4e00\u53e5 why\u3002
//
// \u8fd9\u4e2a\u6d4b\u8bd5\u53ea\u9a8c\u6e32\u67d3\uff1aJD \u4ece\u540e\u7aef\u6765\uff0c\u524d\u7aef\u4e0d\u505a\u4efb\u4f55\u52a0\u5de5\u3002
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { PendingJob } from '@/api'

const JD = `\u5c97\u4f4d\u63cf\u8ff0
1\u3001\u8d1f\u8d23\u540e\u7aef\u670d\u52a1\u5f00\u53d1\uff1b
\u5c97\u4f4d\u8981\u6c42
1\u3001\u719f\u6089\u5206\u5e03\u5f0f\u7cfb\u7edf\uff1b`

function job(overrides: Partial<PendingJob> = {}): PendingJob {
  return {
    id: 1,
    site_name: 'joinqq',
    url: 'https://x/1',
    title: '\u540e\u7aef\u5de5\u7a0b\u5e08',
    company: 'TestCo',
    category: '\u5f00\u53d1',
    category_agent: '\u5f00\u53d1',
    why: '',
    jd: JD,
    status: 'pending',
    reason: null,
    found_at: '2026-08-21T00:00:00',
    decided_at: null,
    is_golden: false,
    bucket: '',
    resume: { slug: 'a', name: '\u540e\u7aef\u7248', matched: true, reason: '', pdf_state: 'ready' },
    ...overrides,
  }
}

const SITES = {
  joinqq: {
    site_name: 'joinqq',
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
      Promise.resolve({ jobs: mockJobs, total: mockJobs.length, categories: ['\u5f00\u53d1'], sites: SITES }),
    browseUrl: () => Promise.resolve({ ok: true }),
  },
}))

import CrossSiteApplications from './CrossSiteApplications'

describe('Checkpoint 1 shows the job description', () => {
  afterEach(cleanup)

  it('renders the jd text so it can be reviewed together with the decision', async () => {
    mockJobs = [job()]
    render(<CrossSiteApplications />)
    // \u6298\u53e0\u8d77\u6765\u4e5f\u5fc5\u987b\u5728 DOM \u91cc\u2014\u2014\u5ba1\u6279\u4eba\u5c55\u5f00\u5c31\u80fd\u770b\uff0c\u4e0d\u9700\u8981\u518d\u53d1\u4e00\u6b21\u8bf7\u6c42
    expect(await screen.findByText(/\u8d1f\u8d23\u540e\u7aef\u670d\u52a1\u5f00\u53d1/)).toBeTruthy()
  })

  it('shows how long the jd is, so an empty-looking one is obvious', async () => {
    mockJobs = [job()]
    render(<CrossSiteApplications />)
    const label = await screen.findByText(new RegExp(String(JD.length)))
    expect(label).toBeTruthy()
  })

  it('renders no jd block at all when there is no jd', async () => {
    mockJobs = [job({ jd: '' })]
    render(<CrossSiteApplications />)
    await screen.findByText('\u540e\u7aef\u5de5\u7a0b\u5e08')
    expect(screen.queryByText(/\u5c97\u4f4d\u539f\u6587/)).toBeNull()
  })
})
