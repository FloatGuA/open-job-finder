import { useEffect, useState } from 'react'
import { API, type Job, type JobsResponse } from '@/api'
import DevLabel from '@/components/dev/DevLabel'

const PAGE_SIZE = 20

// Keys MUST match schemas.py AppStatus enum (FOUND/APPLIED/INTERVIEWING/OFFER/
// REJECTED). Ordered as the pipeline funnel. FOUND is a pre-apply in-memory state
// that never lands in the DB, so it is not shown as a filter tab.
const STATUS_TABS: Array<{ label: string; value: string | undefined }> = [
  { label: '\u5168\u90e8', value: undefined },
  { label: '\u5df2\u6295\u9012', value: 'APPLIED' },
  { label: '\u9762\u8bd5\u4e2d', value: 'INTERVIEWING' },
  { label: 'Offer', value: 'OFFER' },
  { label: '\u5df2\u62d2\u7edd', value: 'REJECTED' },
]

type ByStatus = Record<string, number>

const STATUS_LABEL: Record<string, string> = {
  FOUND: '\u5df2\u53d1\u73b0',
  APPLIED: '\u5df2\u6295\u9012',
  INTERVIEWING: '\u9762\u8bd5\u4e2d',
  OFFER: 'Offer',
  REJECTED: '\u5df2\u62d2\u7edd',
}

function statusBadgeCls(status: string): string {
  switch (status) {
    case 'APPLIED':
      return 'bg-signal-blue/16 text-signal-bright'
    case 'INTERVIEWING':
      return 'bg-signal-amber/16 text-signal-amber'
    case 'OFFER':
      return 'text-[#ffd60a]'
    case 'REJECTED':
      return 'bg-signal-red/16 text-signal-red'
    default:
      return 'bg-white/[0.06] text-text-3'
  }
}

// Score color by band: strong (>=80) green, mid (>=60) bright text, weak dim.
function scoreCls(score?: number | null): string {
  if (score == null) return 'text-text-3'
  if (score >= 80) return 'text-signal-green'
  if (score >= 60) return 'text-text-1'
  return 'text-text-3'
}

function formatDate(iso?: string): string {
  if (!iso) return '\u2014'
  try {
    return new Date(iso).toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    })
  } catch {
    return iso
  }
}

function StatusPill({ status }: { status: string }) {
  return (
    <span
      className={`inline-block rounded-md px-2 py-0.5 font-mono text-[11.5px] font-medium ${statusBadgeCls(status)}`}
      style={status === 'OFFER' ? { background: 'rgba(255,214,10,0.16)' } : undefined}
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  )
}

function JobDetailDialog({ job, onClose }: { job: Job; onClose: () => void }) {
  const fields: Array<{ label: string; value: string | number | undefined | null; mono?: boolean }> = [
    { label: '\u516c\u53f8', value: job.company },
    { label: '\u804c\u4f4d', value: job.title },
    { label: 'HR', value: job.hr_name },
    { label: '\u57ce\u5e02', value: job.city },
    { label: '\u85aa\u8d44', value: job.salary, mono: true },
    { label: '\u8bc4\u5206', value: job.score, mono: true },
    { label: '\u6295\u9012\u65f6\u95f4', value: formatDate(job.applied_at), mono: true },
  ]

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.72)' }}
      onClick={onClose}
    >
      <div
        className="relative w-full max-w-lg overflow-hidden rounded-2xl bg-bg-card p-6 shadow-dialog"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="pointer-events-none absolute inset-0 rounded-2xl" style={{ border: '1px solid rgba(255,255,255,0.08)' }} />
        <DevLabel name="JobDetailDialog" float />
        <div className="mb-5 flex items-start justify-between">
          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-white" style={{ letterSpacing: '-0.374px' }}>
              {job.company}
            </h2>
            <p className="mt-0.5 text-sm text-text-2" style={{ letterSpacing: '-0.224px' }}>
              {job.title}
            </p>
          </div>
          <div className="ml-4 flex shrink-0 items-center gap-2">
            <StatusPill status={job.status} />
            <button
              type="button"
              onClick={onClose}
              className="rounded-full p-1 text-text-3 transition hover:bg-bg-hover hover:text-text-1"
              aria-label={'\u5173\u95ed'}
            >
              {'\u2715'}
            </button>
          </div>
        </div>

        <div className="space-y-2">
          {fields.map(({ label, value, mono }) =>
            value !== undefined && value !== null && value !== '' ? (
              <div key={label} className="flex gap-3 text-sm" style={{ letterSpacing: '-0.224px' }}>
                <span className="w-20 shrink-0 text-text-3">{label}</span>
                <span className={`break-all text-text-1 ${mono ? 'font-mono' : ''}`}>{String(value)}</span>
              </div>
            ) : null,
          )}
          {job.url && (
            <div className="flex gap-3 text-sm" style={{ letterSpacing: '-0.224px' }}>
              <span className="w-20 shrink-0 text-text-3">{'\u94fe\u63a5'}</span>
              <button
                type="button"
                onClick={() => API.browseUrl(job.url).catch((e: Error) => alert(e.message))}
                className="break-all text-left font-mono text-signal-bright hover:underline"
              >
                {job.url}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default function Jobs() {
  const [activeStatus, setActiveStatus] = useState<string | undefined>(undefined)
  const [page, setPage] = useState(1)
  const [data, setData] = useState<JobsResponse | null>(null)
  const [byStatus, setByStatus] = useState<ByStatus>({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null)

  // Load per-status counts once (and after each tab navigation to keep fresh).
  useEffect(() => {
    API.getStats()
      .then((d) => {
        const s = d.stats as Record<string, unknown>
        if (s.by_status) setByStatus(s.by_status as ByStatus)
      })
      .catch(() => {})
  }, [activeStatus])

  useEffect(() => {
    setLoading(true)
    setError(null)
    API.getJobs(activeStatus, page, PAGE_SIZE)
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [activeStatus, page])

  const jobs = data?.jobs ?? []
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const selectedJob = jobs.find((j) => j.job_id === selectedJobId)

  const handleTabChange = (status: string | undefined) => {
    setActiveStatus(status)
    setPage(1)
  }

  return (
    <div className="space-y-4">
      {/* STATUS FILTER */}
      <div>
        <p className="mb-2 flex items-center gap-2 text-[10px] font-medium tracking-widest text-text-3 uppercase select-none">
          STATUS FILTER
          <DevLabel name="StatusFilter" />
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          {STATUS_TABS.map((tab) => {
            const active = tab.value === activeStatus
            const count = tab.value
              ? (byStatus[tab.value] ?? 0)
              : Object.values(byStatus).reduce((a, b) => a + b, 0)
            return (
              <button
                key={tab.label}
                type="button"
                onClick={() => handleTabChange(tab.value)}
                className={
                  active
                    ? 'flex items-center gap-2 rounded-full bg-signal-blue px-3.5 py-1.5 text-xs font-medium text-white'
                    : 'flex items-center gap-2 rounded-full bg-bg-card2 px-3.5 py-1.5 text-xs font-medium text-text-2 transition hover:bg-bg-hover hover:text-text-1'
                }
                style={{ letterSpacing: '-0.12px' }}
              >
                <span>{tab.label}</span>
                {count > 0 && (
                  <span className={`rounded-full px-1.5 py-0.5 font-mono text-[11px] leading-none ${active ? 'bg-white/20 text-white' : 'bg-white/10 text-text-3'}`}>
                    {count}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {error && <p className="rounded-lg bg-signal-red/10 px-3 py-2 text-xs text-signal-red">{error}</p>}

      {/* RECORDS */}
      <div>
        <p className="mb-2 flex items-center gap-2 text-[10px] font-medium tracking-widest text-text-3 uppercase select-none">
          RECORDS
          <DevLabel name="JobsTable" />
        </p>
        <div className="relative overflow-hidden rounded-2xl bg-bg-card shadow-card">
          <div className="pointer-events-none absolute inset-0 z-10 rounded-2xl" style={{ border: '1px solid rgba(255,255,255,0.08)' }} />
          {loading ? (
            <div className="px-4 py-8 text-center text-sm text-text-3">{'\u52a0\u8f7d\u4e2d\u2026'}</div>
          ) : jobs.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-text-3">{'\u6682\u65e0\u6570\u636e'}</div>
          ) : (
            <table className="w-full">
              <thead>
                <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.06)', background: '#2c2c2e' }}>
                  {['\u516c\u53f8', 'HR', '\u804c\u4f4d', '\u57ce\u5e02', '\u85aa\u8d44', '\u72b6\u6001', '\u8bc4\u5206', '\u6295\u9012\u65f6\u95f4', '\u64cd\u4f5c'].map((h) => (
                    <th key={h} className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-text-3">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr
                    key={job.job_id}
                    onClick={() => setSelectedJobId(job.job_id)}
                    className="cursor-pointer text-sm text-text-1 transition even:bg-white/[0.012] hover:bg-bg-hover"
                    style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}
                  >
                    <td className="px-4 py-3 font-medium" style={{ letterSpacing: '-0.224px' }}>{job.company}</td>
                    <td className="px-4 py-3 whitespace-nowrap text-text-2" style={{ letterSpacing: '-0.224px' }}>{job.hr_name || '\u2014'}</td>
                    <td className="max-w-[180px] truncate px-4 py-3" title={job.title} style={{ letterSpacing: '-0.224px' }}>{job.title}</td>
                    <td className="px-4 py-3 text-text-2">{job.city || '\u2014'}</td>
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-text-2">{job.salary || '\u2014'}</td>
                    <td className="px-4 py-3"><StatusPill status={job.status} /></td>
                    <td className={`px-4 py-3 font-mono ${scoreCls(job.score)}`}>{job.score ?? '\u2014'}</td>
                    <td className="whitespace-nowrap px-4 py-3 font-mono text-text-2">{formatDate(job.applied_at)}</td>
                    <td className="px-4 py-3">
                      <button
                        type="button"
                        onClick={(e) => { e.stopPropagation(); setSelectedJobId(job.job_id) }}
                        className="rounded-lg bg-transparent px-3 py-1 text-xs text-text-3 transition hover:bg-bg-card2 hover:text-text-1"
                      >
                        {'\u8be6\u60c5'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* PAGINATION */}
      <div className="flex items-center justify-between text-xs text-text-3" style={{ letterSpacing: '-0.12px' }}>
        <span className="flex items-center gap-2 font-mono">
          <DevLabel name="Pagination" />
          {'\u5171 '}{total}{' \u6761 \u00b7 \u7b2c '}{page}{' / '}{totalPages}{' \u9875'}
        </span>
        <div className="flex gap-2">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((p) => p - 1)}
            className="rounded-lg bg-bg-card2 px-4 py-1.5 text-sm text-text-1 transition hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
            style={{ letterSpacing: '-0.224px' }}
          >
            {'\u4e0a\u4e00\u9875'}
          </button>
          <button
            type="button"
            disabled={page >= totalPages}
            onClick={() => setPage((p) => p + 1)}
            className="rounded-lg bg-bg-card2 px-4 py-1.5 text-sm text-text-1 transition hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-40"
            style={{ letterSpacing: '-0.224px' }}
          >
            {'\u4e0b\u4e00\u9875'}
          </button>
        </div>
      </div>

      {selectedJob && <JobDetailDialog job={selectedJob} onClose={() => setSelectedJobId(null)} />}
    </div>
  )
}
