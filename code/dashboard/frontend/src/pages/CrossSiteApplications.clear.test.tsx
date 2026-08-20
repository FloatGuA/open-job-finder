// \u6309\u7ad9\u70b9\u6e05\u6389\u5019\u9009\u6c60\uff0c\u662f"\u91cd\u6536\u4e00\u4e2a\u7ad9"\u7684\u524d\u63d0\uff1aknown_urls \u4e0d\u770b\u72b6\u6001\uff0c\u4e0d\u771f\u5220\u5c31\u6c38\u8fdc
// \u6536\u4e0d\u56de\u6765\u3002\u800c\u5220\u9664\u4e0d\u53ef\u9006\uff0c\u6240\u4ee5\u6309\u94ae\u5fc5\u987b\u4e24\u6b65\u2014\u2014**\u7b2c\u4e00\u4e0b\u7edd\u4e0d\u80fd\u771f\u5220**\u3002
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PendingJob } from '@/api'

const cleared: string[] = []

const JOB: PendingJob = {
  id: 1,
  site_name: 'joinqq',
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

vi.mock('@/api', () => ({
  API: {
    getCheckpoint1Jobs: () =>
      Promise.resolve({
        jobs: [JOB],
        total: 1,
        categories: ['\u5f00\u53d1'],
        sites: {
          joinqq: {
            site_name: 'joinqq',
            approved_here: 0,
            approved_by_bucket: {},
            buckets: [],
            fill_pending: 0,
            limits: [],
            brief: null,
            manual: null,
          },
        },
      }),
    browseUrl: () => Promise.resolve({ ok: true }),
    clearSiteCandidates: (site: string) => {
      cleared.push(site)
      return Promise.resolve({ deleted: 1, site })
    },
  },
}))

import CrossSiteApplications from './CrossSiteApplications'

describe('clearing one site candidate pool', () => {
  beforeEach(() => {
    cleared.length = 0
  })
  afterEach(cleanup)

  it('does NOT delete on the first click', async () => {
    render(<CrossSiteApplications />)
    fireEvent.click(await screen.findByText('\u6e05\u6389\u5019\u9009'))
    expect(cleared).toEqual([])
  })

  it('asks for confirmation first, then deletes the named site', async () => {
    render(<CrossSiteApplications />)
    fireEvent.click(await screen.findByText('\u6e05\u6389\u5019\u9009'))
    fireEvent.click(await screen.findByText(/\u786e\u8ba4\u6e05\u6389/))
    await vi.waitFor(() => expect(cleared).toEqual(['joinqq']))
  })
})
