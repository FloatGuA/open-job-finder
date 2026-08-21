// \u7ad9\u70b9\u624b\u518c\u8981\u80fd\u4f5c\u5e9f\u91cd\u63a2\u3002
//
// \u624b\u518c\u662f survey_structure \u7684\u7ed3\u8bba\u7f13\u5b58\uff0cvalidate_manual \u53ea\u9a8c\u4e09\u6761\u2014\u2014\u4e00\u4efd\u624b\u518c\u53ef\u4ee5\u5728
// \u5b83\u53d1\u73b0\u4e0d\u4e86\u7684\u5730\u65b9\u662f\u9519\u7684\uff08\u771f\u673a 2026-08-21\uff1ajoinqq \u7684\u624b\u518c\u5728 set_filter_option
// \u5b58\u5728\u4e4b\u524d\u63a2\u7684\uff0c\u90a3\u65f6\u52fe\u4efb\u4f55 checkbox \u90fd\u5931\u8d25\uff0c\u505a\u4e0d\u4e86"\u52fe\u4e00\u4e2a\u3001\u56de\u8bfb\u603b\u6570"\u7684\u5b9e\u6d4b\uff0c
// \u4e8e\u662f multi_select \u4e09\u4e2a\u5b57\u6bb5\u5168\u9760\u731c\uff09\uff0c\u7136\u540e\u88ab\u540e\u7eed\u6bcf\u4e00\u6b21 run \u65e0\u9650\u671f\u7ee7\u627f\u3002
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { PendingJob, SiteManualInfo } from '@/api'

const cleared: string[] = []

const MANUAL: SiteManualInfo = {
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
}

const JOB: PendingJob = {
  id: 1, site_name: 'bambulab', url: 'https://x/1', title: '\u540e\u7aef\u5de5\u7a0b\u5e08',
  company: 'TestCo', category: '\u5f00\u53d1', category_agent: '\u5f00\u53d1', why: '', jd: '',
  status: 'pending', reason: null, found_at: '2026-08-21T00:00:00', decided_at: null,
  is_golden: false, bucket: '',
  resume: { file: 'a.pdf', name: '\u540e\u7aef\u7248', matched: true, reason: '', state: 'ready' },
}

let mockManual: SiteManualInfo | null = MANUAL

vi.mock('@/api', () => ({
  API: {
    getCheckpoint1Jobs: () =>
      Promise.resolve({
        jobs: [JOB], total: 1, categories: ['\u5f00\u53d1'],
        sites: {
          bambulab: {
            site_name: 'bambulab', approved_here: 0, approved_by_bucket: {},
            buckets: [], fill_pending: 0, limits: [], brief: null, manual: mockManual,
          },
        },
      }),
    browseUrl: () => Promise.resolve({ ok: true }),
    clearSiteManual: (site: string) => {
      cleared.push(site)
      return Promise.resolve({ deleted: 1, site })
    },
  },
}))

import CrossSiteApplications from './CrossSiteApplications'

describe('re-surveying a site', () => {
  beforeEach(() => {
    cleared.length = 0
    mockManual = MANUAL
  })
  afterEach(cleanup)

  it('does NOT clear on the first click', async () => {
    render(<CrossSiteApplications />)
    fireEvent.click(await screen.findByText('\u91cd\u65b0\u52d8\u5bdf'))
    expect(cleared).toEqual([])
  })

  it('asks first, then clears the named site', async () => {
    render(<CrossSiteApplications />)
    fireEvent.click(await screen.findByText('\u91cd\u65b0\u52d8\u5bdf'))
    fireEvent.click(await screen.findByText(/\u786e\u8ba4\u4f5c\u5e9f/))
    await vi.waitFor(() => expect(cleared).toEqual(['bambulab']))
  })

  it('offers nothing when the site was never surveyed', async () => {
    mockManual = null
    render(<CrossSiteApplications />)
    await screen.findByText('\u540e\u7aef\u5de5\u7a0b\u5e08')
    expect(screen.queryByText('\u91cd\u65b0\u52d8\u5bdf')).toBeNull()
  })
})
