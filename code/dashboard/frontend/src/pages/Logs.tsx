import { useEffect, useState } from 'react'
import { API, type RunSummaryItem, type RunDetail, type StepEntry, type ToolEntry, type BusinessEvent, type RunDiagnosis, type OpsArtifactsResponse } from '@/api'
import DevLabel from '@/components/dev/DevLabel'
import { RunView } from '@/components/workflow/WorkflowTrack'
import type { ProgressEvent } from '@/hooks/useWorkflowStream'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmtTime(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  const hh = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  return `${mm}-${dd} ${hh}:${min}`
}

function fmtTs(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  const hh = String(d.getHours()).padStart(2, '0')
  const min = String(d.getMinutes()).padStart(2, '0')
  const ss = String(d.getSeconds()).padStart(2, '0')
  return `${hh}:${min}:${ss}`
}

function fmtDuration(ms: number | null | undefined): string {
  if (ms == null) return ''
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

// ---------------------------------------------------------------------------
// Badge components
// ---------------------------------------------------------------------------

function PipelineBadge({ pipeline }: { pipeline: string }) {
  const isW1 = pipeline === 'w1'
  return (
    <span
      className={`inline-block rounded px-1.5 py-0.5 font-mono text-xs font-bold ${
        isW1
          ? 'bg-signal-blue/16 text-signal-bright'
          : 'bg-signal-purple/16 text-signal-purple'
      }`}
    >
      {isW1 ? 'W1' : 'W2'}
    </span>
  )
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    done: 'bg-signal-green/16 text-signal-green',
    failed: 'bg-signal-red/16 text-signal-red',
    running: 'bg-signal-amber/16 text-signal-amber',
    successful: 'bg-signal-green/16 text-signal-green',
    degraded: 'bg-signal-amber/16 text-signal-amber',
    skipped: 'bg-white/[0.06] text-text-3',
    error: 'bg-signal-red/16 text-signal-red',
  }
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 font-mono text-xs font-medium ${map[status] ?? 'bg-white/[0.06] text-text-2'}`}>
      {status}
    </span>
  )
}

function EventNameBadge({ name }: { name: string }) {
  // W1 business events
  const w1Events = new Set(['job_scored', 'job_applied', 'job_skipped'])
  // W2 business events
  const w2Events = new Set([
    'intent_analyzed',
    'resume_sent',
    'reply_sent',
    'stage_advanced',
    'conv_timeout_closed',
    'job_no_response_rejected',
  ])
  let cls = 'bg-white/[0.06] text-text-2'
  if (w1Events.has(name)) cls = 'bg-signal-blue/16 text-signal-bright'
  else if (w2Events.has(name)) cls = 'bg-signal-purple/16 text-signal-purple'
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-mono ${cls}`}>{name}</span>
  )
}

// ---------------------------------------------------------------------------
// Tool row (inside Step expand)
// ---------------------------------------------------------------------------

function ToolRow({ tool }: { tool: ToolEntry }) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div className="ml-4 border-l border-bg-hover pl-3">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 py-1.5 text-left transition hover:bg-bg-hover rounded"
      >
        <span className="text-xs text-text-3 w-16 shrink-0">{fmtTs(tool.ts)}</span>
        <StatusBadge status={tool.status} />
        <span className="font-mono text-xs text-text-2">{tool.tool}</span>
        {tool.duration_ms != null && (
          <span className="ml-auto text-xs text-text-3">{fmtDuration(tool.duration_ms)}</span>
        )}
      </button>
      {expanded && (
        <div className="mb-2 ml-2 rounded bg-bg-page px-3 py-2">
          {tool.error && (
            <p className="mb-1 text-xs text-signal-red">{'\u9519\u8bef'}: {tool.error}</p>
          )}
          {Object.keys(tool.data).length > 0 && (
            <pre className="text-xs text-text-2 leading-relaxed whitespace-pre-wrap break-all">
              {JSON.stringify(tool.data, null, 2)}
            </pre>
          )}
          {Object.keys(tool.scope).length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {Object.entries(tool.scope).map(([k, v]) => (
                <span key={k} className="rounded bg-bg-hover px-1.5 py-0.5 text-xs text-text-3">
                  {k}: {v}
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Step row
// ---------------------------------------------------------------------------

function StepRow({ step }: { step: StepEntry }) {
  const [expanded, setExpanded] = useState(false)
  const hasSub = step.tools.length > 0 || step.error || Object.keys(step.data).length > 0

  return (
    <div className="border-b border-bg-hover last:border-0">
      <button
        type="button"
        onClick={() => hasSub && setExpanded((v) => !v)}
        className={`flex w-full items-center gap-2 px-1 py-2.5 text-left transition ${hasSub ? 'hover:bg-bg-hover cursor-pointer' : 'cursor-default'} rounded`}
      >
        {/* Timeline dot */}
        <div className="mt-0.5 flex w-3 shrink-0 items-center justify-center">
          <div className="h-1.5 w-1.5 rounded-full bg-text-3" />
        </div>
        <span className="w-16 shrink-0 text-xs text-text-3">{fmtTs(step.ts)}</span>
        <StatusBadge status={step.status} />
        <span className="font-mono text-xs text-text-1">{step.step}</span>
        {/* Scope hints */}
        {step.scope && Object.keys(step.scope).length > 0 && (
          <span className="ml-1 truncate text-xs text-text-3">
            {Object.values(step.scope).slice(0, 2).join(' \u00b7 ')}
          </span>
        )}
        <span className="ml-auto text-xs text-text-3">{fmtDuration(step.duration_ms)}</span>
        {hasSub && (
          <span className="ml-1 text-xs text-text-3">{expanded ? '\u25b2' : '\u25bc'}</span>
        )}
      </button>

      {expanded && (
        <div className="pb-2">
          {step.error && (
            <p className="ml-7 mb-1 text-xs text-signal-red">{'\u9519\u8bef'}: {step.error}</p>
          )}
          {Object.keys(step.data).length > 0 && (
            <pre className="ml-7 mb-2 rounded bg-bg-page px-3 py-2 text-xs text-text-2 leading-relaxed whitespace-pre-wrap break-all">
              {JSON.stringify(step.data, null, 2)}
            </pre>
          )}
          {step.tools.map((t, idx) => (
            // eslint-disable-next-line react/no-array-index-key
            <ToolRow key={`${t.tool}-${idx}`} tool={t} />
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Flow tab
// ---------------------------------------------------------------------------

function FlowTab({ detail }: { detail: RunDetail }) {
  if (detail.steps.length === 0) {
    return (
      <p className="py-8 text-center text-xs text-text-3">{'\u6682\u65e0 Step \u8bb0\u5f55'}</p>
    )
  }
  return (
    <div className="px-2 py-2">
      {detail.steps.map((step, idx) => (
        // eslint-disable-next-line react/no-array-index-key
        <StepRow key={`${step.step}-${idx}`} step={step} />
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Business event row
// ---------------------------------------------------------------------------

// W1 events and their key data fields to display
const W1_EVENTS = new Set(['job_scored', 'job_applied', 'job_skipped'])
const W2_EVENTS = new Set([
  'intent_analyzed',
  'resume_sent',
  'reply_sent',
  'stage_advanced',
  'conv_timeout_closed',
  'job_no_response_rejected',
])

function summarizeEventData(event: string, data: Record<string, unknown>): string {
  const parts: string[] = []
  if (event === 'job_scored') {
    if (data.score !== undefined) parts.push(`score: ${data.score}`)
    if (data.above_threshold !== undefined) parts.push(`pass: ${data.above_threshold}`)
    if (data.reason) parts.push(String(data.reason).slice(0, 40))
  } else if (event === 'job_applied') {
    if (data.status) parts.push(String(data.status))
  } else if (event === 'job_skipped') {
    if (data.reason) parts.push(String(data.reason).slice(0, 60))
  } else if (event === 'intent_analyzed') {
    if (data.intent) parts.push(`intent: ${data.intent}`)
    if (data.stage) parts.push(`stage: ${data.stage}`)
  } else if (event === 'resume_sent' || event === 'reply_sent') {
    if (data.status) parts.push(String(data.status))
  } else if (event === 'stage_advanced') {
    if (data.from_stage) parts.push(`${data.from_stage} \u2192 ${data.to_stage}`)
  } else {
    const keys = Object.keys(data).slice(0, 3)
    for (const k of keys) {
      parts.push(`${k}: ${data[k]}`)
    }
  }
  return parts.join(' \u00b7 ')
}

function BusinessEventRow({ be }: { be: BusinessEvent }) {
  const [expanded, setExpanded] = useState(false)
  const summary = summarizeEventData(be.event, be.data)
  const scopeStr = Object.entries(be.scope)
    .slice(0, 2)
    .map(([, v]) => v)
    .join(' \u00b7 ')

  return (
    <div className="border-b border-bg-hover last:border-0 py-2">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-start gap-2 text-left transition hover:bg-bg-hover rounded px-1"
      >
        <span className="w-16 shrink-0 text-xs text-text-3 pt-0.5">{fmtTs(be.ts)}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <EventNameBadge name={be.event} />
            {scopeStr && <span className="text-xs text-text-3">{scopeStr}</span>}
          </div>
          {summary && (
            <p className="mt-0.5 truncate text-xs text-text-2">{summary}</p>
          )}
        </div>
        <span className="ml-1 shrink-0 text-xs text-text-3">{expanded ? '\u25b2' : '\u25bc'}</span>
      </button>
      {expanded && (
        <pre className="mt-1 ml-[4.5rem] rounded bg-bg-page px-3 py-2 text-xs text-text-2 leading-relaxed whitespace-pre-wrap break-all">
          {JSON.stringify({ scope: be.scope, data: be.data }, null, 2)}
        </pre>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Decisions tab
// ---------------------------------------------------------------------------

function DecisionsTab({ detail }: { detail: RunDetail }) {
  const w1Events = detail.business_events.filter((be) => W1_EVENTS.has(be.event))
  const w2Events = detail.business_events.filter((be) => W2_EVENTS.has(be.event))
  const otherEvents = detail.business_events.filter(
    (be) => !W1_EVENTS.has(be.event) && !W2_EVENTS.has(be.event),
  )

  if (detail.business_events.length === 0) {
    return (
      <p className="py-8 text-center text-xs text-text-3">{'\u6682\u65e0\u4e1a\u52a1\u4e8b\u4ef6'}</p>
    )
  }

  return (
    <div className="px-2 py-2 space-y-4">
      {w1Events.length > 0 && (
        <div>
          <p className="mb-1 px-1 text-[10px] font-medium tracking-widest text-signal-bright uppercase select-none">
            {'W1 \u00b7 \u6c42\u804c\u51b3\u7b56'}
          </p>
          {w1Events.map((be, idx) => (
            // eslint-disable-next-line react/no-array-index-key
            <BusinessEventRow key={`w1-${be.event}-${idx}`} be={be} />
          ))}
        </div>
      )}
      {w2Events.length > 0 && (
        <div>
          <p className="mb-1 px-1 text-[10px] font-medium tracking-widest text-signal-purple uppercase select-none">
            {'W2 \u00b7 \u5bf9\u8bdd\u51b3\u7b56'}
          </p>
          {w2Events.map((be, idx) => (
            // eslint-disable-next-line react/no-array-index-key
            <BusinessEventRow key={`w2-${be.event}-${idx}`} be={be} />
          ))}
        </div>
      )}
      {otherEvents.length > 0 && (
        <div>
          <p className="mb-1 px-1 text-[10px] font-medium tracking-widest text-text-3 uppercase select-none">
            {'\u5176\u4ed6\u4e8b\u4ef6'}
          </p>
          {otherEvents.map((be, idx) => (
            // eslint-disable-next-line react/no-array-index-key
            <BusinessEventRow key={`other-${be.event}-${idx}`} be={be} />
          ))}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

type PipelineFilter = '' | 'w1' | 'w2' | 'w3'
type DetailTab = 'overview' | 'flow' | 'decisions' | 'diagnosis'
type PageTab = 'runs' | 'cleanup'
const PAGE_TABS: Array<{ key: PageTab; label: string }> = [
  { key: 'runs', label: '\u8fd0\u884c\u8bb0\u5f55' },
  { key: 'cleanup', label: '\u5931\u8d25\u65e5\u5fd7\u6e05\u7406' },
]

/** Deterministic verdict for one run, read straight from its JSONL log.
 *  See docs/run-log-guide.md for how to read the report. */
function DiagnosisTab({ runId }: { runId: string }) {
  const [diag, setDiag] = useState<RunDiagnosis | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let alive = true
    setLoading(true)
    API.diagnoseRun(runId)
      .then((d) => { if (alive) setDiag(d) })
      .catch(() => { if (alive) setDiag(null) })
      .finally(() => { if (alive) setLoading(false) })
    return () => { alive = false }
  }, [runId])

  if (loading) return <p className="py-8 text-center text-xs text-text-3">{'\u8bca\u65ad\u4e2d…'}</p>
  if (!diag) return <p className="py-8 text-center text-xs text-text-3">{'\u8bca\u65ad\u5931\u8d25'}</p>

  // Three states, not two: a legacy log we cannot judge is NOT a failure.
  const undiagnosable = diag.diagnosable === false
  const tone = undiagnosable
    ? { bg: 'rgba(255,255,255,0.06)', fg: '#98989d', text: '\u65e0\u6cd5\u8bca\u65ad' }
    : diag.ok
      ? { bg: 'rgba(48,209,88,0.14)', fg: '#30d158', text: '\u65e0\u5f02\u5e38' }
      : { bg: 'rgba(255,69,58,0.16)', fg: '#ff453a', text: '\u6709\u5f02\u5e38' }

  return (
    <div className="space-y-3 px-2 py-2">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded px-2 py-0.5 text-xs font-medium" style={{ background: tone.bg, color: tone.fg }}>
          {tone.text}
        </span>
        {diag.trigger && (
          <span className="rounded px-2 py-0.5 text-[11px] text-text-3" style={{ background: 'rgba(255,255,255,0.05)' }}>
            {'\u89e6\u53d1\uff1a'}{diag.trigger}
          </span>
        )}
        {diag.outbound && Object.keys(diag.outbound).length > 0 && (
          <span className="rounded px-2 py-0.5 text-[11px] font-medium" style={{ background: 'rgba(255,159,10,0.16)', color: '#ff9f0a' }}>
            {'\u771f\u5b9e\u5916\u53d1'}
          </span>
        )}
      </div>

      {(diag.anomalies?.length ?? 0) > 0 && (
        <div className="space-y-1 rounded-lg p-3" style={{ background: 'rgba(255,69,58,0.08)', border: '1px solid rgba(255,69,58,0.25)' }}>
          {diag.anomalies?.map((a, i) => (
            <p key={i} className="text-xs leading-relaxed" style={{ color: '#ff8a80' }}>{'! '}{a}</p>
          ))}
        </div>
      )}

      <pre className="overflow-x-auto rounded-lg p-3 text-[11px] leading-relaxed text-text-2" style={{ background: 'rgba(0,0,0,0.25)' }}>
        {diag.report}
      </pre>

      <p className="text-[11px] text-text-3">
        {'\u5b57\u6bb5\u542b\u4e49\u4e0e\u5e38\u89c1\u75c5\u56e0\u89c1 docs/run-log-guide.md'}
      </p>
    </div>
  )
}


function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

// Manual review-then-delete entry point for the two file-based artifact types that
// accumulate real HR/company PII with no automatic cleanup: failed-run JSONL logs
// and W1 apply-failure screenshots (precommit_pii_scan.py only guards what goes
// into git, not what sits on disk). Deliberately NOT an automatic purge \u2014 the
// user looks at what is there and decides what is still worth keeping.
function OpsCleanupSection() {
  const [data, setData] = useState<OpsArtifactsResponse | null>(null)
  const [selectedLogs, setSelectedLogs] = useState<Set<string>>(new Set())
  const [selectedShots, setSelectedShots] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const load = () => {
    API.getOpsArtifacts()
      .then((d) => {
        setData(d)
        setSelectedLogs(new Set())
        setSelectedShots(new Set())
      })
      .catch(() => setData({ run_logs: [], screenshots: [] }))
  }

  useEffect(() => { load() }, [])

  const toggle = (set: Set<string>, setter: (s: Set<string>) => void, name: string) => {
    const next = new Set(set)
    if (next.has(name)) next.delete(name)
    else next.add(name)
    setter(next)
  }

  const selectOlderThan = (days: number) => {
    if (!data) return
    const cutoff = Date.now() - days * 86400000
    setSelectedLogs(new Set(
      data.run_logs.filter((r) => new Date(r.started_at).getTime() < cutoff).map((r) => r.filename)
    ))
    setSelectedShots(new Set(
      data.screenshots.filter((s) => new Date(s.mtime).getTime() < cutoff).map((s) => s.filename)
    ))
  }

  const selectAll = () => {
    if (!data) return
    setSelectedLogs(new Set(data.run_logs.map((r) => r.filename)))
    setSelectedShots(new Set(data.screenshots.map((s) => s.filename)))
  }

  const clearSelection = () => {
    setSelectedLogs(new Set())
    setSelectedShots(new Set())
  }

  const totalSelected = selectedLogs.size + selectedShots.size

  const handleDelete = async () => {
    if (totalSelected === 0) return
    setBusy(true)
    setNotice(null)
    try {
      const res = await API.deleteOpsArtifacts({
        run_logs: [...selectedLogs],
        screenshots: [...selectedShots],
      })
      setNotice(`\u5df2\u5220\u9664 ${res.deleted_count} \u4e2a\u6587\u4ef6`)
      load()
    } catch (e) {
      setNotice('\u5220\u9664\u5931\u8d25\uff1a' + (e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!data) return <p className="px-4 py-6 text-xs text-text-3">\u52a0\u8f7d\u4e2d\u2026</p>

  const empty = data.run_logs.length === 0 && data.screenshots.length === 0
  const btnCls = "rounded-lg px-3 py-1.5 text-xs font-medium transition bg-white/[0.04] text-text-2 hover:bg-white/[0.08] disabled:opacity-40 disabled:cursor-not-allowed"

  return (
    <div className="space-y-4">
      <p className="text-[11px] text-text-3">\u5931\u8d25\u7684 run \u65e5\u5fd7\uff08\u542b HR \u59d3\u540d/\u804a\u5929\u539f\u6587\uff09\u4e0e W1 \u6295\u9012\u5931\u8d25\u622a\u56fe\uff08\u542b\u516c\u53f8/HR \u4fe1\u606f\uff09\u53ea\u5728\u8fd9\u91cc\u624b\u52a8\u67e5\u770b\u548c\u6e05\u7406\uff0c\u4e0d\u4f1a\u81ea\u52a8\u5220\u9664\u3002</p>
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={selectAll} className={btnCls}>\u5168\u9009</button>
        <button type="button" onClick={() => selectOlderThan(7)} className={btnCls}>\u9009\u4e2d 7 \u5929\u524d</button>
        <button type="button" onClick={() => selectOlderThan(30)} className={btnCls}>\u9009\u4e2d 30 \u5929\u524d</button>
        <button type="button" onClick={clearSelection} className={btnCls}>\u6e05\u7a7a\u9009\u62e9</button>
        <button
          type="button"
          onClick={handleDelete}
          disabled={busy || totalSelected === 0}
          className="rounded-lg px-3 py-1.5 text-xs font-medium transition bg-signal-red/16 text-signal-red hover:bg-signal-red/24 disabled:opacity-40 disabled:cursor-not-allowed"
        >
          \u5220\u9664\u5df2\u9009\uff08{totalSelected}\uff09
        </button>
        {notice && <span className="text-xs text-text-3">{notice}</span>}
      </div>

      {empty && <p className="px-4 py-6 text-center text-xs text-text-3">\u6ca1\u6709\u9700\u8981\u6e05\u7406\u7684\u6587\u4ef6</p>}

      {data.run_logs.length > 0 && (
        <div>
          <p className="mb-2 text-[10px] font-medium tracking-widest text-text-3 uppercase select-none">
            \u5931\u8d25\u7684 RUN \u65e5\u5fd7\uff08{data.run_logs.length}\uff09
          </p>
          <div className="divide-y divide-bg-hover rounded-xl bg-bg-card2">
            {data.run_logs.map((r) => (
              <label key={r.filename} className="flex cursor-pointer items-center gap-3 px-3 py-2 text-xs hover:bg-bg-hover">
                <input
                  type="checkbox"
                  checked={selectedLogs.has(r.filename)}
                  onChange={() => toggle(selectedLogs, setSelectedLogs, r.filename)}
                />
                <PipelineBadge pipeline={r.pipeline} />
                <span className="font-mono text-text-2">{r.run_id}</span>
                <StatusBadge status={r.status} />
                <span className="ml-auto text-text-3">{fmtTime(r.started_at)} \u00b7 {fmtBytes(r.size_bytes)}</span>
              </label>
            ))}
          </div>
        </div>
      )}

      {data.screenshots.length > 0 && (
        <div>
          <p className="mb-2 text-[10px] font-medium tracking-widest text-text-3 uppercase select-none">
            \u5931\u8d25\u622a\u56fe\uff08{data.screenshots.length}\uff09
          </p>
          <div className="divide-y divide-bg-hover rounded-xl bg-bg-card2">
            {data.screenshots.map((s) => (
              <label key={s.filename} className="flex cursor-pointer items-center gap-3 px-3 py-2 text-xs hover:bg-bg-hover">
                <input
                  type="checkbox"
                  checked={selectedShots.has(s.filename)}
                  onChange={() => toggle(selectedShots, setSelectedShots, s.filename)}
                />
                <a
                  href={`/api/apply-failure/${s.filename}`}
                  target="_blank"
                  rel="noreferrer"
                  className="font-mono text-signal-bright hover:underline"
                  onClick={(e) => e.stopPropagation()}
                >
                  {s.label}
                </a>
                <span className="ml-auto text-text-3">{fmtTime(s.mtime)} \u00b7 {fmtBytes(s.size_bytes)}</span>
              </label>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function Logs() {
  const [runs, setRuns] = useState<RunSummaryItem[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [detail, setDetail] = useState<RunDetail | null>(null)
  const [runEvents, setRunEvents] = useState<ProgressEvent[]>([])
  const [pipelineFilter, setPipelineFilter] = useState<PipelineFilter>('')
  const [detailTab, setDetailTab] = useState<DetailTab>('overview')
  const [loading, setLoading] = useState(false)
  const [pageTab, setPageTab] = useState<PageTab>('runs')

  const [diagMap, setDiagMap] = useState<Record<string, RunDiagnosis>>({})

  // Initial load. The batch diagnosis runs alongside: it parses the JSONL of ~200
  // runs in well under a second, and it is what lets the list flag the runs that
  // ended badly (interrupted mid-send, DB writes lost) instead of making you open
  // them one by one.
  useEffect(() => {
    API.getRuns()
      .then((r) => setRuns(r.runs))
      .catch(() => setRuns([]))
    API.diagnoseRecentRuns({ limit: 200 })
      .then((d) => {
        const m: Record<string, RunDiagnosis> = {}
        for (const r of d.runs) if (r.run_id) m[r.run_id] = r
        setDiagMap(m)
      })
      .catch(() => setDiagMap({}))
  }, [])

  // Load both the flat event stream (overview / live-style replay) and the grouped
  // detail (raw Flow / Decisions drill-down) when a run is selected.
  useEffect(() => {
    if (selectedRunId === null) {
      setDetail(null)
      setRunEvents([])
      return
    }
    setLoading(true)
    setDetail(null)
    setRunEvents([])
    void Promise.all([
      API.getRunEvents(selectedRunId)
        .then((d) => setRunEvents(d.events))
        .catch(() => setRunEvents([])),
      API.getRunDetail(selectedRunId)
        .then((d) => setDetail(d))
        .catch(() => setDetail(null)),
    ]).finally(() => setLoading(false))
  }, [selectedRunId])

  const filteredRuns = pipelineFilter
    ? runs.filter((r) => r.pipeline === pipelineFilter)
    : runs

  const selectedRun = selectedRunId ? runs.find((r) => r.run_id === selectedRunId) ?? null : null

  return (
    <div className="flex h-full flex-col gap-4 overflow-hidden">
      <div className="flex shrink-0 gap-1 rounded-xl p-1" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}>
        {PAGE_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setPageTab(t.key)}
            className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
              pageTab === t.key ? 'text-text-1' : 'text-text-3 hover:text-text-2'
            }`}
            style={pageTab === t.key ? { background: 'rgba(10,132,255,0.16)', boxShadow: 'inset 0 0 0 1px rgba(10,132,255,0.3)' } : undefined}
          >
            {t.label}
          </button>
        ))}
      </div>

      {pageTab === 'cleanup' && (
        <div className="flex-1 overflow-y-auto rounded-2xl bg-bg-card p-4 shadow-card" style={{ border: '1px solid rgba(255,255,255,0.08)' }}>
          <OpsCleanupSection />
        </div>
      )}

      <div className={`flex flex-1 gap-4 overflow-hidden ${pageTab === 'runs' ? '' : 'hidden'}`}>
      {/* ------------------------------------------------------------------ */}
      {/* Left: run list                                                       */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex w-96 shrink-0 flex-col overflow-hidden rounded-2xl bg-bg-card shadow-card" style={{ border: '1px solid rgba(255,255,255,0.08)' }}>
        {/* Filter tabs */}
        <div className="flex items-center gap-1 border-b border-bg-hover px-3 py-3">
          <p className="mr-auto flex items-center gap-2 text-[10px] font-medium tracking-widest text-text-3 uppercase select-none">
            RUNS
            <DevLabel name="RunList" />
          </p>
          {(['', 'w1', 'w2', 'w3'] as PipelineFilter[]).map((pf) => {
            const labelMap: Record<PipelineFilter, string> = {
              '': '\u5168\u90e8',
              w1: 'W1',
              w2: 'W2',
              w3: 'W3',
            }
            return (
              <button
                key={pf}
                type="button"
                onClick={() => setPipelineFilter(pf)}
                className={`rounded-lg px-3 py-1 text-xs transition ${
                  pipelineFilter === pf
                    ? 'bg-signal-blue/15 text-signal-bright font-medium'
                    : 'text-text-3 hover:bg-bg-hover hover:text-text-1'
                }`}
              >
                {labelMap[pf]}
              </button>
            )
          })}
        </div>

        {/* Run list */}
        <div className="flex-1 overflow-y-auto">
          {filteredRuns.length === 0 && (
            <p className="px-4 py-6 text-center text-xs text-text-3">
              {'\u6682\u65e0\u8fd0\u884c\u8bb0\u5f55'}
            </p>
          )}
          {filteredRuns.map((run) => {
            const active = run.run_id === selectedRunId
            const summaryStr = run.summary
              ? Object.entries(run.summary)
                  .slice(0, 3)
                  .map(([k, v]) => `${k}: ${v}`)
                  .join(', ')
              : ''
            return (
              <button
                key={run.run_id}
                type="button"
                onClick={() => {
                  setSelectedRunId(run.run_id)
                  setDetailTab('overview')
                }}
                className={`relative w-full border-b border-bg-hover px-3 py-2.5 text-left transition ${
                  active ? 'bg-signal-blue/[0.1]' : 'hover:bg-bg-hover'
                }`}
              >
                {active && <span className="absolute left-0 top-0 bottom-0 w-0.5" style={{ background: '#0a84ff' }} />}
                <div className="flex items-center gap-2">
                  <PipelineBadge pipeline={run.pipeline} />
                  <span className="truncate font-mono text-xs text-text-1">{run.run_id}</span>
                  {/* Only flag runs we could actually judge; a legacy log we cannot
                      parse must not look like a failure. */}
                  {diagMap[run.run_id]?.diagnosable && diagMap[run.run_id]?.ok === false && (
                    <span
                      className="shrink-0 rounded px-1 text-[10px] font-medium"
                      style={{ background: 'rgba(255,69,58,0.16)', color: '#ff453a' }}
                      title={diagMap[run.run_id]?.anomalies?.[0] ?? ''}
                    >
                      {'!'}
                    </span>
                  )}
                  {(diagMap[run.run_id]?.outbound
                    && Object.keys(diagMap[run.run_id].outbound ?? {}).length > 0
                    && diagMap[run.run_id]?.complete === false) && (
                    <span
                      className="shrink-0 rounded px-1 text-[10px] font-medium"
                      style={{ background: 'rgba(255,159,10,0.16)', color: '#ff9f0a' }}
                      title={'\u4e2d\u65ad\u524d\u5df2\u771f\u5b9e\u5916\u53d1\uff0c\u843d\u5e93\u72b6\u6001\u672a\u77e5'}
                    >
                      {'\u5916\u53d1'}
                    </span>
                  )}
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <StatusBadge status={run.status} />
                  {run.duration_ms != null && (
                    <span className="text-xs text-text-3">{fmtDuration(run.duration_ms)}</span>
                  )}
                  {run.started_at && (
                    <span className="text-xs text-text-3">{fmtTime(run.started_at)}</span>
                  )}
                </div>
                {summaryStr && (
                  <p className="mt-0.5 truncate text-xs text-text-3">{summaryStr}</p>
                )}
              </button>
            )
          })}
        </div>
      </div>

      {/* ------------------------------------------------------------------ */}
      {/* Right: detail panel                                                  */}
      {/* ------------------------------------------------------------------ */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden rounded-2xl bg-bg-card shadow-card" style={{ border: '1px solid rgba(255,255,255,0.08)' }}>
        {selectedRun === null ? (
          <div className="flex flex-1 flex-col">
            <div className="border-b border-bg-hover px-5 py-3">
              <p className="flex items-center gap-2 text-[10px] font-medium tracking-widest text-text-3 uppercase select-none">
                DETAIL
                <DevLabel name="RunDetail" />
              </p>
            </div>
            <div className="flex flex-1 items-center justify-center">
              <p className="text-sm text-text-3">
                {'\u9009\u62e9\u5de6\u4fa7\u7684\u8fd0\u884c\u8bb0\u5f55\u67e5\u770b\u8be6\u60c5'}
              </p>
            </div>
          </div>
        ) : (
          <>
            {/* Header */}
            <div className="flex items-center gap-3 border-b border-bg-hover px-5 py-3">
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <PipelineBadge pipeline={selectedRun.pipeline} />
                  <DevLabel name="RunDetail" />
                  <span className="font-mono text-sm text-text-1">{selectedRun.run_id}</span>
                  <StatusBadge status={selectedRun.status} />
                  {selectedRun.duration_ms != null && (
                    <span className="text-xs text-text-3">{fmtDuration(selectedRun.duration_ms)}</span>
                  )}
                </div>
                {selectedRun.started_at && (
                  <p className="mt-0.5 text-xs text-text-3">{fmtTime(selectedRun.started_at)}</p>
                )}
                {selectedRun.summary && (
                  <p className="mt-0.5 text-xs text-text-3">
                    {Object.entries(selectedRun.summary)
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(' \u00b7 ')}
                  </p>
                )}
              </div>

              {/* Tab switcher */}
              <div className="flex shrink-0 gap-1 rounded-lg bg-bg-hover p-1">
                {(['overview', 'flow', 'decisions', 'diagnosis'] as DetailTab[]).map((tab) => {
                  const tabLabel: Record<DetailTab, string> = {
                    overview: '\u6982\u89c8',
                    flow: 'Flow',
                    decisions: 'Decisions',
                    diagnosis: '\u8bca\u65ad',
                  }
                  return (
                    <button
                      key={tab}
                      type="button"
                      onClick={() => setDetailTab(tab)}
                      className={`rounded-md px-3 py-1 text-xs font-medium transition ${
                        detailTab === tab
                          ? 'bg-bg-card text-text-1 shadow-sm'
                          : 'text-text-3 hover:text-text-2'
                      }`}
                    >
                      {tabLabel[tab]}
                    </button>
                  )
                })}
              </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto px-3 py-2">
              {/* These two report on the grouped-detail fetch, which the diagnosis
                  tab does not use -- showing them there would stack a spinner or a
                  "load failed" on top of a perfectly good diagnosis. */}
              {loading && detailTab !== 'diagnosis' && (
                <p className="py-8 text-center text-xs text-text-3">{'\u52a0\u8f7d\u4e2d\u2026'}</p>
              )}
              {!loading && detail === null && detailTab !== 'diagnosis' && (
                <p className="py-8 text-center text-xs text-text-3">{'\u52a0\u8f7d\u5931\u8d25'}</p>
              )}
              {!loading && detailTab === 'overview' && (
                <RunView
                  key={selectedRun.run_id}
                  events={runEvents}
                  workflowId={selectedRun.pipeline}
                  summary={selectedRun.summary}
                />
              )}
              {!loading && detail !== null && detailTab === 'flow' && (
                <FlowTab detail={detail} />
              )}
              {!loading && detail !== null && detailTab === 'decisions' && (
                <DecisionsTab detail={detail} />
              )}
              {/* Diagnosis reads the raw log itself, so it does not depend on
                  `detail` having loaded -- it still works for a run whose grouped
                  detail failed to parse, which is exactly when you need it. */}
              {detailTab === 'diagnosis' && <DiagnosisTab runId={selectedRun.run_id} />}
            </div>
          </>
        )}
      </div>
    </div>
    </div>
  )
}
