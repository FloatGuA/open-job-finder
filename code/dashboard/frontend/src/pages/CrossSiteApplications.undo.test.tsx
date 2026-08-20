// Checkpoint 1 needs an undo entry for approved/rejected jobs -- 2026-08-20
// incident: a user mis-approved two jobs and there was no way back except a
// maintainer running raw SQL. This only checks the UI wiring (button
// visibility + it calls the undo API + triggers a refresh); the tracker-level
// no-double-send guarantee is covered in tests/test_server.py.
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
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
    manual: null,
  },
}

let mockJobs: PendingJob[] = []
const undoSpy = vi.fn((_id: number) => Promise.resolve({ ok: true }))

vi.mock('@/api', () => ({
  API: {
    getCheckpoint1Jobs: () =>
      Promise.resolve({ jobs: mockJobs, total: mockJobs.length, categories: ['product'], sites: SITES }),
    browseUrl: () => Promise.resolve({ ok: true }),
    undoCheckpoint1Job: (id: number) => undoSpy(id),
  },
}))

import CrossSiteApplications from './CrossSiteApplications'

describe('Checkpoint 1 undo entry', () => {
  afterEach(() => {
    cleanup()
    undoSpy.mockClear()
  })

  it('does not show an undo button for a pending job', async () => {
    mockJobs = [job({ status: 'pending' })]
    render(<CrossSiteApplications />)

    await screen.findByText('Game Design Role')
    expect(screen.queryByText('\u64a4\u9500')).toBeNull()
  })

  it('shows an undo button for an approved job', async () => {
    mockJobs = [job({ status: 'approved', decided_at: '2026-08-20T01:00:00' })]
    render(<CrossSiteApplications />)

    expect(await screen.findByText('\u64a4\u9500')).not.toBeNull()
  })

  it('shows an undo button for a rejected job', async () => {
    mockJobs = [job({ status: 'rejected', reason: 'x', decided_at: '2026-08-20T01:00:00' })]
    render(<CrossSiteApplications />)

    expect(await screen.findByText('\u64a4\u9500')).not.toBeNull()
  })

  it('clicking undo calls the API with the job id and refreshes the list', async () => {
    mockJobs = [job({ status: 'approved', decided_at: '2026-08-20T01:00:00' })]
    render(<CrossSiteApplications />)

    const btn = await screen.findByText('\u64a4\u9500')
    fireEvent.click(btn)

    expect(undoSpy).toHaveBeenCalledWith(1)
  })
})
