import { useEffect, useMemo, useRef, useState } from 'react'
import { API } from '@/api'
import { useAppContext } from '@/context/app-context'
import type { ProgressEvent } from '@/hooks/useWorkflowStream'
import DevLabel from '@/components/dev/DevLabel'
import { useWorkflowSkeleton } from '@/hooks/useWorkflowSkeleton'
import { STEP_LABELS, SKIP_REASON_LABELS, interpretEvent } from './interpret'
import MultisiteRunView from './MultisiteRunView'

// W1/W2/W3 的步骤骨架**不再抄在这里**——从后端 /api/workflow/skeleton 拉
// （`useWorkflowSkeleton`）。抄的那份烂过：W3 少了 4 个步骤、W2 少了 wechat，
// 而且不会报错。后端那份由 tests/test_pipeline_skeleton.py 双向盯着源码。
//
// **每步会调哪些工具也不再预先声明**：一个 pipeline 文件里可能有好几个
// set_context，工具归哪一步靠静态分析分不出来，而手维护的列表会说谎
// （`fetch_jd` 里挂着一个早就搬走的 score_job，永远显示"待运行"）。
// 现在只显示**实际观测到的**工具——空闲态本来就不知道会调什么。

// Per-workflow run summary chips (keys match pipeline/w{1,2}/pipeline.py summary dict).
// W1: \u67e5\u770b(cards_viewed) \u2192 \u6253\u5206(scored) \u2192 \u6295\u9012(applied) \u2192 \u8df3\u8fc7(skipped) \u2014\u2014 the
// user asked for a top-level "\u770b\u4e86\u591a\u5c11 / \u6253\u5206\u591a\u5c11 / \u6295\u4e86\u591a\u5c11" count.
const SUMMARY_CHIPS: Record<string, { key: string; label: string }[]> = {
  w1: [
    { key: 'cards_viewed', label: '\u67e5\u770b' },
    { key: 'scored', label: '\u6253\u5206' },
    { key: 'applied', label: '\u6295\u9012' },
    { key: 'skipped', label: '\u8df3\u8fc7' },
    { key: 'errors', label: '\u5931\u8d25' },
  ],
  w2: [
    { key: 'convs_processed', label: '\u5904\u7406\u4f1a\u8bdd' },
    { key: 'resumes_sent', label: '\u53d1\u7b80\u5386' },
    { key: 'stage_changes', label: '\u72b6\u6001\u53d8\u66f4' },
  ],
}

// \u2500\u2500 Hierarchy tree model \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

// Run trigger (who launched it) \u2192 short label. Source: run_start meta.trigger, carried
// on the 'start' event detail (live via emitter.start_workflow, replay via _parse_run_events).
const TRIGGER_LABELS: Record<string, string> = {
  manual: '\u624b\u52a8',
  scheduled: '\u5b9a\u65f6',
  selfcheck: '\u81ea\u68c0',
  cli: '\u547d\u4ee4\u884c',
}

// Format the run's params (from start event detail.params) into a one-line string.
function formatRunParams(workflowId: string, params: Record<string, unknown>): string {
  const n = (v: unknown): number | undefined => (typeof v === 'number' ? v : undefined)
  const dry = params.dry_run === true ? ' \u00b7 \u6f14\u7ec3' : ''
  if (workflowId === 'w1') {
    const mc = params.max_cards
    const cards = mc == null ? '\u5168\u90e8' : String(mc)
    return `${cards} \u5361 \u00b7 \u9608\u503c ${n(params.score_threshold) ?? '?'}${dry}`
  }
  if (workflowId === 'w2') {
    return `${n(params.max_conversations) ?? '?'} \u4f1a\u8bdd \u00b7 \u8d85\u65f6 ${n(params.no_response_days) ?? '?'}\u5929 \u00b7 \u6e05\u7406 ${n(params.stale_conv_days) ?? '?'}\u5929${dry}`
  }
  return ''
}

interface ToolNode {
  tool: string
  status: string
  message: string
  detail: Record<string, unknown>
  ts: number
}
interface StepNode {
  step: string
  status: string
  message: string
  detail: Record<string, unknown>
  ts: number
  tools: Map<string, ToolNode>
}
interface InstanceNode {
  key: string
  label: string
  jobId: string
  firstTs: number
  lastTs: number
  steps: Map<string, StepNode>
}

const RUN_KEY = '__run__'

function instanceKey(ev: ProgressEvent): string {
  const s = ev.scope || {}
  const id = (s.conv_id as string) || (s.job_id as string) || ''
  return id || RUN_KEY
}

// Reduce the flat event stream into workflow -> instance -> step -> tool.
// Step-level events (tool == null) drive the step node; tool events become
// children. Latest event wins for a given node.
function buildTree(events: ProgressEvent[], workflow: string): InstanceNode[] {
  const instances = new Map<string, InstanceNode>()
  for (const ev of events) {
    if (ev.workflow !== workflow) continue
    const key = instanceKey(ev)
    const ts = ev.ts ?? 0
    let inst = instances.get(key)
    if (!inst) {
      inst = { key, label: '', jobId: '', firstTs: ts, lastTs: ts, steps: new Map() }
      instances.set(key, inst)
    }
    inst.lastTs = Math.max(inst.lastTs, ts)
    const company = (ev.scope?.company as string) || ''
    if (company) inst.label = company
    // job_id links the instance to its Boss job posting (open-job button). W1 events
    // scope job_id directly; W2/W3 now carry it on the navigate/locate scope. Empty
    // for sha256 soft-key conversations, which get no button.
    const jobId = (ev.scope?.job_id as string) || ''
    if (jobId) inst.jobId = jobId

    let st = inst.steps.get(ev.step)
    if (!st) {
      st = { step: ev.step, status: 'pending', message: '', detail: {}, ts, tools: new Map() }
      inst.steps.set(ev.step, st)
    }
    if (ev.tool) {
      const existing = st.tools.get(ev.tool)
      if (!existing || ts >= existing.ts) {
        st.tools.set(ev.tool, { tool: ev.tool, status: ev.status, message: ev.message, detail: ev.detail ?? {}, ts })
      }
    } else if (ts >= st.ts || st.status === 'pending') {
      st.status = ev.status
      st.message = ev.message
      st.detail = ev.detail ?? {}
      st.ts = ts
    }
  }
  return [...instances.values()].sort((a, b) => a.firstTs - b.firstTs)
}

function instLabel(inst: InstanceNode): string {
  if (inst.label) return inst.label
  if (inst.key === RUN_KEY) return '\u8fd0\u884c'
  return inst.key.slice(0, 8)
}

// \u2500\u2500 Status visuals (Telemetry signal palette) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

function fmtRowTs(ts?: number): string {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleTimeString('zh-CN', { hour12: false })
}

function dotCls(status: string): string {
  switch (status) {
    case 'running':  return 'bg-signal-amber animate-pulse'
    case 'done':     return 'bg-signal-green'
    case 'skipped':  return 'bg-deco'
    case 'error':    return 'bg-signal-red'
    case 'blocked':  return 'bg-signal-amber animate-pulse'
    case 'stopping': return 'bg-signal-red animate-pulse'
    case 'info':     return 'bg-signal-teal'
    default:         return 'bg-text-3/30'
  }
}

// -- Per-instance loop detail ---------------------------------------------

// Render a given set of steps (step\u2192tool, real per-tool messages) for one
// instance: a loop instance (job / conversation) or the run-level `__run__`
// instance. `stepKeys` selects which steps to show (run-level vs loop-level, from
// /api/workflow/skeleton), so
// Open a job's Boss detail page in the shared automation browser (the one logged
// into Boss). Reuses POST /api/browse, which 409s while a workflow runs (the single
// login profile is locked by the run) \u2014 hence disabled when workflowRunning, matching
// the conversation "\u5728 Boss \u6253\u5f00" button. Only needs the job_id (every job instance has
// it from scope), so it works for skipped/already-applied jobs too, not just JD-fetched.
function OpenJobButton({ jobId }: { jobId: string }) {
  const { workflowRunning } = useAppContext()
  const [err, setErr] = useState<string | null>(null)
  const url = `https://www.zhipin.com/job_detail/${jobId}.html`
  return (
    <div className="flex items-center gap-2 px-3 py-1.5" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
      <button
        type="button"
        onClick={() => {
          setErr(null)
          API.browseUrl(url)
            .then((r) => { if (!r?.ok) setErr(r.reason || '\u672a\u80fd\u5728 Boss \u6253\u5f00\u8be5\u5c97\u4f4d') })
            .catch((e: Error) => setErr(e.message))
        }}
        disabled={workflowRunning !== null}
        className="rounded-lg px-2.5 py-1 font-mono text-[11.5px] text-signal-bright transition hover:bg-signal-blue/10 disabled:cursor-not-allowed disabled:opacity-40"
        style={{ background: 'rgba(10,132,255,0.1)' }}
        title={'\u5728\u81ea\u52a8\u5316\u6d4f\u89c8\u5668\u4e2d\u6253\u5f00\u8be5\u5c97\u4f4d\u7684 Boss \u8be6\u60c5\u9875\uff08\u5de5\u4f5c\u6d41\u8fd0\u884c\u65f6\u4e0d\u53ef\u7528\uff09'}
      >
        {'\u2197 \u5728 Boss \u6253\u5f00'}
      </button>
      <span className="font-mono text-[11px] text-text-3" title={'job_id'}>{'job_id: '}{jobId}</span>
      {err && <span className="font-mono text-[11px] text-signal-red">{err}</span>}
    </div>
  )
}

// non-loop steps live outside the per-instance loop. `inst` null = idle skeleton
// (everything pending), so the structure shows even with no run.
function InstanceDetail({
  inst,
  workflow,
  stepKeys,
}: {
  inst: InstanceNode | null
  workflow: string
  stepKeys: string[]
}) {
  const instSteps = inst?.steps ?? new Map<string, StepNode>()
  return (
    <div className="overflow-hidden rounded-xl" style={{ border: '1px solid rgba(255,255,255,0.05)' }}>
      {/* Open the job's Boss detail page. Now for all workflows (W1/W2/W3) via the
          job_id carried on scope; hidden when there is none (run-level node, or a
          soft-key W2/W3 conversation with no job_id). */}
      {inst && inst.key !== RUN_KEY && inst.jobId && <OpenJobButton jobId={inst.jobId} />}
      {workflow === 'w1' && inst && applyFailScreenshot(inst) && (
        <div className="flex items-center gap-2 px-3 py-1.5" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
          <a
            href={`/api/apply-failure/${applyFailScreenshot(inst)}`}
            target="_blank"
            rel="noreferrer"
            className="rounded-lg px-2.5 py-1 font-mono text-[11.5px] text-signal-red transition hover:bg-signal-red/10"
            style={{ background: 'rgba(255,69,58,0.1)' }}
          >
            {'\u{1F4F7} \u67e5\u770b\u6295\u9012\u5931\u8d25\u622a\u56fe'}
          </a>
        </div>
      )}
      {/* W2 locate-failure screenshot (conv_navigate_failed). Same failure-diagnostic
          image path as W1 apply failures, served by /api/apply-failure/{name}. */}
      {workflow === 'w2' && inst && navFailScreenshot(inst) && (
        <div className="flex items-center gap-2 px-3 py-1.5" style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}>
          <a
            href={`/api/apply-failure/${navFailScreenshot(inst)}`}
            target="_blank"
            rel="noreferrer"
            className="rounded-lg px-2.5 py-1 font-mono text-[11.5px] text-signal-red transition hover:bg-signal-red/10"
            style={{ background: 'rgba(255,69,58,0.1)' }}
          >
            {'\u{1F4F7} \u67e5\u770b\u5b9a\u4f4d\u5931\u8d25\u622a\u56fe'}
          </a>
        </div>
      )}
      {stepKeys.map((stepKey) => {
        const st = instSteps.get(stepKey)
        const sStatus = st?.status ?? 'pending'
        const toolKeys = [...(st?.tools.keys() ?? [])]
        return (
          <div
            key={stepKey}
            className={`px-3 py-1.5 ${sStatus === 'running' ? 'bg-signal-amber/[0.05]' : ''}`}
            style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}
          >
            <div className="flex items-center gap-2.5">
              <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${dotCls(sStatus)}`} />
              <span className={`shrink-0 font-mono text-[13.5px] ${sStatus === 'pending' ? 'text-text-3' : 'text-text-1'}`}>
                {STEP_LABELS[stepKey] ?? stepKey}
              </span>
              {st?.message && sStatus !== 'pending' && (
                <span className={`min-w-0 truncate font-mono text-[11px] ${msgCls(sStatus)}`}>{st.message}</span>
              )}
            </div>
            {toolKeys.length > 0 && (
              <div className="mt-1 space-y-0.5 pl-5">
                {toolKeys.map((t) => {
                  const tn = st?.tools.get(t)
                  const tStatus = tn?.status ?? 'pending'
                  return (
                    <div key={t} className="flex items-start gap-2">
                      <span className={`mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full ${dotCls(tStatus)}`} />
                      <span className="w-[180px] shrink-0 font-mono text-[11.5px] text-text-3">{t}</span>
                      {tn?.message && (
                        <span className={`min-w-0 break-all font-mono text-[11px] ${msgCls(tStatus)}`}>{tn.message}</span>
                      )}
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}

// Pull the score number out of a W1 instance. Prefer the job_scored business
// event's detail.score (authoritative, present in JSONL replay); fall back to the
// score_job tool message regex for live/non-debug streams that lack the event.
function extractScore(inst: InstanceNode): number | null {
  const scored = inst.steps.get('job_scored')?.detail?.score
  if (typeof scored === 'number') return scored
  for (const st of inst.steps.values()) {
    const t = st.tools.get('score_job')
    if (t) {
      const m = t.message.match(/\d{1,3}/)
      if (m) return parseInt(m[0], 10)
    }
  }
  return null
}

// Did this card's score pass the threshold? Reads the job_scored event's
// detail.above_threshold (present in JSONL replay + live). null when unknown.
function scoreAbove(inst: InstanceNode): boolean | null {
  const v = inst.steps.get('job_scored')?.detail?.above_threshold
  return typeof v === 'boolean' ? v : null
}

// One-line result badge for a processed card.
function cardResult(inst: InstanceNode): { text: string; cls: string } {
  if (inst.steps.get('apply')?.status === 'done') return { text: '\u6295\u9012', cls: 'bg-signal-green/16 text-signal-green' }
  if (inst.steps.get('resume')?.status === 'done') return { text: '\u53d1\u7b80\u5386', cls: 'bg-signal-green/16 text-signal-green' }
  if (inst.steps.get('verify')?.status === 'done') return { text: '\u5df2\u53d1', cls: 'bg-signal-green/16 text-signal-green' }
  // Business-event outcomes: job_applied / job_skipped are always written to the run
  // JSONL, so the badge stays correct even when classify/apply have no terminal step
  // event (older runs, or jobs skipped before a Step class ran).
  if (inst.steps.has('job_applied')) return { text: '\u6295\u9012', cls: 'bg-signal-green/16 text-signal-green' }
  if (inst.steps.has('job_apply_failed')) return { text: '\u6295\u9012\u5931\u8d25', cls: 'bg-signal-red/16 text-signal-red' }
  if (inst.steps.has('job_skipped')) return { text: '\u8df3\u8fc7', cls: 'bg-white/[0.06] text-text-3' }
  // Finalize-stage closures (no per-conversation loop steps ran): a real outcome of
  // this run, so show \u5df2\u5173\u95ed rather than falling through to \u7b49\u5f85.
  if (inst.steps.has('conv_timeout_closed') || inst.steps.has('job_no_response_rejected'))
    return { text: '\u5df2\u5173\u95ed', cls: 'bg-white/[0.06] text-text-3' }
  for (const s of inst.steps.values()) if (s.status === 'error') return { text: '\u9519\u8bef', cls: 'bg-signal-red/16 text-signal-red' }
  for (const s of inst.steps.values()) if (s.status === 'running') return { text: '\u5904\u7406\u4e2d', cls: 'bg-signal-amber/16 text-signal-amber' }
  for (const s of inst.steps.values()) if (s.status === 'skipped') return { text: '\u8df3\u8fc7', cls: 'bg-white/[0.06] text-text-3' }
  // Ran to completion but took no specific action (e.g. a W2 conversation that
  // needs no resume/reply): a normal terminal state, NOT "waiting/not-started".
  for (const s of inst.steps.values()) if (s.status === 'done') return { text: '\u5df2\u5904\u7406', cls: 'bg-signal-teal/16 text-signal-teal' }
  return { text: '\u7b49\u5f85', cls: 'bg-white/[0.05] text-text-3' }
}

// Human-readable skip reason for a W1 job card (already-applied / score-below /
// content-duplicate / llm-error), from SKIP_REASON_LABELS + optional prior_status.
// Reads the reason from whichever node carries it:
// the job_skipped business event (always in JSONL replay) or, during a live run
// without debug SSE, the terminal classify/apply skipped step's detail. Returns null
// when the card was not skipped. This is what the user looks at to know WHY a job was
// skipped without expanding the raw live log.
function skipReasonText(inst: InstanceNode): string | null {
  const pick = (): { reason: string; prior: string } | null => {
    const js = inst.steps.get('job_skipped')
    if (js) return { reason: String(js.detail?.reason ?? ''), prior: String(js.detail?.prior_status ?? '') }
    for (const key of ['apply']) {
      const st = inst.steps.get(key)
      if (st?.status === 'skipped')
        return { reason: String(st.detail?.reason ?? ''), prior: String(st.detail?.prior_status ?? '') }
    }
    return null
  }
  const d = pick()
  if (!d) return null
  const label = SKIP_REASON_LABELS[d.reason] ?? STEP_LABELS.job_skipped
  return d.prior ? `${label} (${d.prior})` : label
}

// Filename of the apply-failure screenshot for a W1 job (job_apply_failed event
// detail.screenshot), served by GET /api/apply-failure/{name}. null when none.
function applyFailScreenshot(inst: InstanceNode): string | null {
  const name = inst.steps.get('job_apply_failed')?.detail?.screenshot
  return typeof name === 'string' && name ? name : null
}

// Filename of the W2 locate-failure screenshot (conv_navigate_failed event
// detail.screenshot), served by GET /api/apply-failure/{name}. null when none.
function navFailScreenshot(inst: InstanceNode): string | null {
  const name = inst.steps.get('conv_navigate_failed')?.detail?.screenshot
  return typeof name === 'string' && name ? name : null
}

// Scrolling list of loop instances (newest first). Each row is a button that
// selects which instance the detail panel shows. `activeKey` is highlighted
// (it may be the auto-followed latest card when nothing is manually selected).
function RecentCards({
  cards,
  workflow,
  activeKey,
  onSelect,
}: {
  cards: InstanceNode[]
  workflow: string
  activeKey: string | null
  onSelect: (key: string | null) => void
}) {
  if (cards.length === 0) {
    return (
      <div
        className="flex h-full items-center justify-center rounded-xl px-3 py-6 text-center text-[12.5px] text-text-3"
        style={{ border: '1px solid rgba(255,255,255,0.05)' }}
      >
        {workflow === 'w1' ? '\u6682\u65e0\u5904\u7406\u4e2d\u7684\u804c\u4f4d' : '\u6682\u65e0\u5904\u7406\u4e2d\u7684\u4f1a\u8bdd'}
      </div>
    )
  }
  return (
    <div className="h-full overflow-y-auto rounded-xl" style={{ border: '1px solid rgba(255,255,255,0.05)' }}>
      {cards.map((inst) => {
        const res = cardResult(inst)
        const score = workflow === 'w1' ? extractScore(inst) : null
        const above = workflow === 'w1' ? scoreAbove(inst) : null
        const scoreColor = above === true ? 'text-signal-green' : above === false ? 'text-signal-red' : 'text-text-2'
        const skip = workflow === 'w1' ? skipReasonText(inst) : null
        const active = inst.key === activeKey
        return (
          <button
            key={inst.key}
            type="button"
            title={`${instLabel(inst)}${skip ? ` \u00b7 ${skip}` : ''} \u00b7 ${fmtRowTs(inst.lastTs)}`}
            onClick={() => onSelect(active ? null : inst.key)}
            className={`flex w-full items-center gap-2 px-2.5 py-1.5 text-left transition hover:bg-white/[0.04] ${active ? 'bg-signal-blue/[0.10]' : ''}`}
            style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}
          >
            <span className={`min-w-0 flex-1 truncate text-[13px] ${active ? 'text-signal-bright' : 'text-text-1'}`}>
              {instLabel(inst)}
            </span>
            {skip && <span className="max-w-[92px] shrink-0 truncate text-[11px] text-text-3">{skip}</span>}
            {score != null && <span className={`shrink-0 font-mono text-[12px] ${scoreColor}`}>{score}</span>}
            <span className={`shrink-0 rounded font-mono text-[10.5px] font-semibold px-1.5 py-0.5 ${res.cls}`}>{res.text}</span>
          </button>
        )
      })}
    </div>
  )
}

// Live Event Log

function stepBadgeCls(step: string): string {
  switch (step) {
    case 'navigate':  return 'bg-signal-blue/15 text-signal-bright'
    case 'fetch_jd':  return 'bg-signal-purple/18 text-signal-purple'
    case 'apply':     return 'bg-signal-green/16 text-signal-green'
    case 'read':      return 'bg-signal-blue/15 text-signal-bright'
    case 'analyze':   return 'bg-signal-amber/16 text-signal-amber'
    case 'reply':     return 'bg-signal-green/16 text-signal-green'
    case 'resume':    return 'bg-white/10 text-text-3'
    default:          return 'bg-white/10 text-text-3'
  }
}

function msgCls(status: string): string {
  switch (status) {
    case 'done':     return 'text-signal-green'
    case 'skipped':  return 'text-text-3'
    case 'error':    return 'text-signal-red'
    case 'blocked':  return 'text-signal-amber'
    case 'stopping': return 'text-signal-red'
    default:         return 'text-text-2'
  }
}

// Live-log line color. Score events read green (>= threshold) / red (< threshold) from
// detail.above_threshold so the "\u8bc4\u5206" feedback is instantly readable; apply failures
// read red; everything else falls back to the status palette.
function liveMsgCls(ev: ProgressEvent): string {
  if (ev.step === 'job_scored') {
    return (ev.detail as Record<string, unknown> | undefined)?.above_threshold === false
      ? 'text-signal-red'
      : 'text-signal-green'
  }
  if (ev.step === 'job_apply_failed') return 'text-signal-red'
  return msgCls(ev.status)
}

function formatTs(ts?: number): string {
  if (!ts) return ''
  return new Date(ts * 1000).toLocaleTimeString('zh-CN', { hour12: false })
}

function LiveLog({ events }: { events: ProgressEvent[] }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [autoScroll, setAutoScroll] = useState(true)
  // Collapsed by default: the skeleton + recent cards already convey progress, so the
  // raw per-event tail stays out of the way (it doubled the LIVE column height). The
  // collapsed header still shows the latest event message so activity is visible.
  const [open, setOpen] = useState(false)

  // Only render the tail; the full history can be hundreds of rows.
  const shown = events.length > 80 ? events.slice(-80) : events
  const last = events[events.length - 1]

  useEffect(() => {
    if (open && autoScroll && containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight
    }
  }, [events, autoScroll, open])

  const handleScroll = () => {
    const el = containerRef.current
    if (!el) return
    setAutoScroll(el.scrollHeight - el.scrollTop - el.clientHeight < 48)
  }

  return (
    <div className="mt-4 overflow-hidden rounded-xl" style={{ border: '1px solid rgba(255,255,255,0.05)' }}>
      {/* Header (collapse toggle) */}
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left transition hover:bg-white/[0.03]"
        style={{ background: 'rgba(255,255,255,0.03)' }}
      >
        <span className="text-[10px] text-text-3">{open ? '\u25be' : '\u25b8'}</span>
        <span className="shrink-0 text-xs font-semibold uppercase tracking-wider text-text-3">{'\u5b9e\u65f6\u65e5\u5fd7'}</span>
        <DevLabel name="LiveLog" />
        <span className="shrink-0 font-mono text-[11px] text-text-3">{events.length}</span>
        {!open && last && (
          <span className={`ml-1 min-w-0 flex-1 truncate font-mono text-[11px] ${liveMsgCls(last)}`}>
            {interpretEvent(last)}
          </span>
        )}
        {open && !autoScroll && (
          <span
            role="button"
            tabIndex={0}
            onClick={(e) => {
              e.stopPropagation()
              setAutoScroll(true)
              if (containerRef.current) containerRef.current.scrollTop = containerRef.current.scrollHeight
            }}
            className="ml-auto rounded px-2 py-0.5 text-xs text-signal-bright transition hover:bg-signal-blue/10"
          >
            {'\u56de\u5230\u6700\u65b0'}
          </span>
        )}
      </button>

      {open && (
        <div
          ref={containerRef}
          onScroll={handleScroll}
          className="overflow-y-auto"
          style={{ maxHeight: '220px', background: 'rgba(0,0,0,0.22)', borderTop: '1px solid rgba(255,255,255,0.05)' }}
        >
          {events.length === 0 ? (
            <div className="px-4 py-4 text-xs text-text-3 opacity-50">{'\u6682\u65e0\u65e5\u5fd7'}</div>
          ) : (
            shown.map((ev, i) => (
              <div
                key={`${ev.step}-${ev.tool ?? ''}-${ev.ts ?? i}-${i}`}
                className="flex items-start gap-2 px-3 py-1 font-mono"
                style={{ borderBottom: '1px solid rgba(255,255,255,0.025)' }}
              >
                <span className="mt-0.5 w-16 shrink-0 text-[11px] text-text-3">{formatTs(ev.ts)}</span>
                <span className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[10px] leading-none ${stepBadgeCls(ev.step)}`}>
                  {STEP_LABELS[ev.step] ?? ev.step}
                  {ev.tool ? `/${ev.tool}` : ''}
                </span>
                <span className={`min-w-0 break-all text-[12px] leading-relaxed ${liveMsgCls(ev)}`}>
                  {interpretEvent(ev)}
                </span>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}

// \u2500\u2500 Workflow Card \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

// Shared run visualization: run-level (non-loop) block + per-instance loop
// master-detail + run summary chips + human-readable live log. Fed either by the
// realtime SSE stream (Console live) or a replayed JSONL run (Console after stop,
// or the Logs page). Pure presentation: no run controls, no data fetching. The
// caller resets per-instance selection by remounting (key=).
function TreeRunView({
  events,
  workflowId,
  summary = null,
  isRunning = false,
}: {
  events: ProgressEvent[]
  workflowId: string
  summary?: Record<string, number> | null
  isRunning?: boolean
}) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const tree = useMemo(() => buildTree(events, workflowId), [events, workflowId])
  const runInst = useMemo(() => tree.find((i) => i.key === RUN_KEY) ?? null, [tree])
  // Run meta (who launched it + params), from the 'start' event detail.
  const skeleton = useWorkflowSkeleton()
  const startDetail = (runInst?.steps.get('start')?.detail ?? {}) as Record<string, unknown>
  const trigger = typeof startDetail.trigger === 'string' ? startDetail.trigger : ''
  const runParams = formatRunParams(workflowId, (startDetail.params ?? {}) as Record<string, unknown>)
  // Loop cards = instances that actually entered the per-job/conversation loop (have
  // at least one loop-level node). Finalize-stage bulk closures (conv_timeout_closed /
  // job_no_response_rejected) carry a conv_id/job_id scope but never looped, so they
  // are excluded here and summarized via closedCount instead of flooding the list.
  const cards = useMemo(() => {
    const loop = skeleton.loop_steps[workflowId] ?? []
    return tree
      .filter((i) => i.key !== RUN_KEY && loop.some((s) => i.steps.has(s)))
      .sort((a, b) => b.lastTs - a.lastTs)
  }, [tree, workflowId, skeleton])
  const closedCount = useMemo(() => {
    const loop = skeleton.loop_steps[workflowId] ?? []
    return tree.filter(
      (i) =>
        i.key !== RUN_KEY &&
        !loop.some((s) => i.steps.has(s)) &&
        (i.steps.has('conv_timeout_closed') || i.steps.has('job_no_response_rejected')),
    ).length
  }, [tree, workflowId, skeleton])
  const processed = cards.length
  // The detail panel shows `activeKey`: the manually-selected instance, else
  // auto-follows the latest card so the right side tracks what's processing now.
  const following = !(selectedKey && cards.some((c) => c.key === selectedKey))
  const activeKey = following ? cards[0]?.key ?? null : selectedKey
  const activeInst = cards.find((c) => c.key === activeKey) ?? null

  return (
    <>
      {/* Run meta: running indicator + who triggered it + this run's params. */}
      {(trigger || runParams || isRunning) && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-xl px-3 py-2"
          style={{ border: '1px solid rgba(255,255,255,0.06)', background: 'rgba(255,255,255,0.02)' }}>
          {isRunning ? (
            <span className="flex items-center gap-1.5 text-[12px] text-signal-green">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-signal-green opacity-70" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-signal-green" />
              </span>
              {'\u8fd0\u884c\u4e2d'}
            </span>
          ) : (
            <span className="flex items-center gap-1.5 text-[12px] text-text-3">
              <span className="h-2 w-2 rounded-full bg-text-3/40" />
              {'\u5df2\u7ed3\u675f'}
            </span>
          )}
          {trigger && (
            <span className="rounded-lg bg-signal-blue/12 px-2 py-0.5 font-mono text-[11px] text-signal-bright">
              {(TRIGGER_LABELS[trigger] ?? trigger)}{' \u89e6\u53d1'}
            </span>
          )}
          {runParams && (
            <span className="font-mono text-[11.5px] text-text-2">{runParams}</span>
          )}
        </div>
      )}

      {/* Run-level (non-loop) steps: scan / navigate / finalize. */}
      <div className="mb-3">
        <p className="mb-1.5 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-text-3">
          {'\u672c\u6b21\u8fd0\u884c \u00b7 \u975e\u5faa\u73af'}
          <DevLabel name="RunSteps" />
        </p>
        <InstanceDetail inst={runInst} workflow={workflowId} stepKeys={skeleton.run_steps[workflowId] ?? []} />
      </div>

      {/* Loop: left = instance list, right = selected/auto-followed instance detail. */}
      <div className="flex gap-3" style={{ height: '480px' }}>
        <div className="flex w-[220px] shrink-0 flex-col">
          <div className="mb-1.5 flex items-center justify-between">
            <span className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-text-3">
              {workflowId === 'w1' ? '\u9010\u804c\u4f4d\u5faa\u73af' : '\u9010\u4f1a\u8bdd\u5faa\u73af'}
              <DevLabel name="RecentCards" />
            </span>
            <span className="font-mono text-[11.5px] text-text-3">
              {processed}
              {closedCount > 0 && (
                <span className="ml-1.5 text-deco">{'\u00b7 \u8d85\u65f6\u5173\u95ed '}{closedCount}</span>
              )}
            </span>
          </div>
          <div className="min-h-0 flex-1">
            <RecentCards
              cards={cards}
              workflow={workflowId}
              activeKey={activeKey}
              onSelect={setSelectedKey}
            />
          </div>
        </div>
        <div className="flex min-w-0 flex-1 flex-col">
          <div className="mb-1.5 flex items-center justify-between gap-2">
            <span className="flex min-w-0 items-center gap-2">
              <span className="shrink-0 text-[11px] font-semibold uppercase tracking-wider text-signal-bright">{'\u5faa\u73af\u660e\u7ec6'}</span>
              <DevLabel name="InstanceDetail" />
              {activeInst && (
                <span className="min-w-0 truncate font-mono text-[11.5px] text-text-2">{instLabel(activeInst)}</span>
              )}
            </span>
            {activeInst && (
              following ? (
                <span className="flex shrink-0 items-center gap-1 text-[10.5px] text-text-3">
                  <span className="h-1.5 w-1.5 rounded-full bg-signal-green" />
                  {'\u8ddf\u968f\u6700\u65b0'}
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => setSelectedKey(null)}
                  className="shrink-0 rounded px-2 py-0.5 text-[10.5px] text-text-3 transition hover:bg-white/[0.06] hover:text-text-1"
                >
                  {'\u8ddf\u968f\u6700\u65b0'}
                </button>
              )
            )}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            <InstanceDetail inst={activeInst} workflow={workflowId} stepKeys={skeleton.loop_steps[workflowId] ?? []} />
          </div>
        </div>
      </div>

      {/* Run summary + LLM degraded alert */}
      {summary && (
        <div className="mt-4 space-y-2">
          <div className="flex flex-wrap gap-2">
            {(SUMMARY_CHIPS[workflowId] ?? []).map(({ key, label }) =>
              summary[key] !== undefined ? (
                <span key={key} className="rounded-lg bg-white/5 px-2.5 py-1 text-xs text-text-2">
                  {label}{' '}
                  <span className="font-mono font-semibold text-text-1">{summary[key]}</span>
                </span>
              ) : null,
            )}
            {(summary.db_write_failures ?? 0) > 0 && (
              <span className="rounded-lg px-2.5 py-1 text-xs text-signal-red" style={{ background: 'rgba(255,69,58,0.1)' }}>
                {STEP_LABELS.db_write_failed}{' '}
                <span className="font-mono font-semibold">{summary.db_write_failures}</span>
              </span>
            )}
          </div>
          {(summary.llm_degraded ?? 0) > 0 && (
            <div
              className="rounded-lg px-3 py-2 text-xs text-signal-amber"
              style={{ background: 'rgba(255,159,10,0.08)', border: '1px solid rgba(255,159,10,0.2)' }}
            >
              {'\u26a0 '}
              {summary.llm_degraded}
              {' \u4e2a\u4f1a\u8bdd\u610f\u56fe\u5206\u6790\u5931\u8d25\uff08LLM \u8d85\u65f6\u6216\u4e0d\u53ef\u7528\uff09\u3002'}
              {'\u7ed3\u679c\u672a\u5199\u5165\u2014\u2014\u5217\u8868\u91cc\u8fd9\u4e9b\u4f1a\u8bdd\u7684\u610f\u56fe\u4ecd\u662f\u4e0a\u4e00\u8f6e\u7684\u65e7\u503c\uff0c\u4e0b\u8f6e W2 \u4f1a\u81ea\u52a8\u91cd\u8bd5\u3002'}
            </div>
          )}
        </div>
      )}

      {/* Live log */}
      <LiveLog events={events} />
    </>
  )
}

// Dispatcher: **no hooks here**.
// m1/m2 图节点内部是 agent 自主循环，是序列不是集合——buildTree 按 tool 名存 Map、
// 后来者覆盖，take_snapshot 的几十次调用会塌成一个。所以它们走单独的三层视图。
export function RunView(props: {
  events: ProgressEvent[]
  workflowId: string
  summary?: Record<string, number> | null
  isRunning?: boolean
}) {
  if (props.workflowId === 'm1' || props.workflowId === 'm2') {
    return (
      <MultisiteRunView
        events={props.events}
        workflowId={props.workflowId}
        isRunning={props.isRunning ?? false}
      />
    )
  }
  return <TreeRunView {...props} />
}

function WorkflowCard({
  workflowId,
  events,
  showRunSummary = false,
}: {
  workflowId: string
  events: ProgressEvent[]
  showRunSummary?: boolean
}) {
  const { workflowRunning } = useAppContext()
  const [stopping, setStopping] = useState(false)
  const [isStuck, setIsStuck] = useState(false)
  const lastEventRef = useRef<number>(Date.now())
  const isRunning = workflowRunning === workflowId

  // When not running, the in-memory SSE buffer is capped (200, shared across
  // workflows) and lost on restart, so it can't show the *complete* last run.
  // Replay the full run from its persisted JSONL instead; live mode keeps using
  // the realtime stream. Same ProgressEvent shape -> same buildTree downstream.
  const [replayEvents, setReplayEvents] = useState<ProgressEvent[]>([])
  useEffect(() => {
    if (isRunning) return
    let cancelled = false
    void API.getRuns({ pipeline: workflowId })
      .then(async (r) => {
        const latest = r.runs[0]
        if (!latest) {
          if (!cancelled) setReplayEvents([])
          return
        }
        const detail = await API.getRunEvents(latest.run_id)
        if (!cancelled) setReplayEvents(detail.events)
      })
      .catch(() => {
        if (!cancelled) setReplayEvents([])
      })
    return () => {
      cancelled = true
    }
  }, [isRunning, workflowId])

  // Live while running, the complete persisted run once stopped. Tree-building and
  // per-instance selection now live in the shared RunView below.
  const displayEvents = isRunning ? events : replayEvents

  // Last completed run summary for this pipeline (only when showRunSummary).
  const [runSummary, setRunSummary] = useState<Record<string, number> | null>(null)
  const prevRunningRef = useRef(isRunning)

  useEffect(() => {
    if (!showRunSummary) return
    let cancelled = false
    void API.getRuns({ pipeline: workflowId }).then((r) => {
      if (cancelled) return
      const latest = r.runs.find((x) => x.status === 'done')
      setRunSummary(latest?.summary ?? null)
    })
    return () => {
      cancelled = true
    }
  }, [showRunSummary, workflowId])

  useEffect(() => {
    if (showRunSummary && prevRunningRef.current && !isRunning) {
      void API.getRuns({ pipeline: workflowId }).then((r) => {
        const latest = r.runs.find((x) => x.status === 'done')
        setRunSummary(latest?.summary ?? null)
      })
    }
    prevRunningRef.current = isRunning
  }, [isRunning, showRunSummary, workflowId])

  useEffect(() => {
    lastEventRef.current = Date.now()
    setIsStuck(false)
  }, [events])

  useEffect(() => {
    if (!isRunning) {
      setIsStuck(false)
      return
    }
    const id = setInterval(() => {
      if (Date.now() - lastEventRef.current > 30_000) {
        setIsStuck(true)
      }
    }, 5_000)
    return () => clearInterval(id)
  }, [isRunning])

  const handleStop = async () => {
    setStopping(true)
    try {
      await API.stopWorkflow()
    } finally {
      setStopping(false)
    }
  }

  return (
    <div className="relative overflow-hidden rounded-2xl bg-bg-card p-4 shadow-card">
      <div className="pointer-events-none absolute inset-0 rounded-2xl" style={{ border: '1px solid rgba(255,255,255,0.08)' }} />

      {/* Title row \u2014 workflow identity lives in the tab bar above; here we keep
          only the live-run indicator + stop control (no duplicate badge/title). */}
      <div className="mb-3 flex min-h-[28px] items-center justify-between">
        <div className="flex items-center gap-2.5">
          {isRunning && (
            <span className="flex items-center gap-1.5 text-xs text-signal-green">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-signal-green" />
              {'\u8fd0\u884c\u4e2d'}
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => void handleStop()}
          disabled={stopping || !isRunning}
          className="rounded-lg px-3 py-1 text-xs text-signal-red transition disabled:cursor-not-allowed disabled:opacity-40"
          style={{ background: 'rgba(255,69,58,0.08)' }}
        >
          {stopping ? '\u4e2d\u6b62\u4e2d\u2026' : '\u25a0 \u4e2d\u6b62'}
        </button>
      </div>

      {isRunning && isStuck && (
        <div
          className="mb-4 rounded-lg px-4 py-2 text-xs text-signal-amber"
          style={{ background: 'rgba(255,159,10,0.08)', border: '1px solid rgba(255,159,10,0.2)' }}
        >
          {'\u8d85\u8fc7 30s \u65e0\u54cd\u5e94\uff0c\u540e\u7aef\u53ef\u80fd\u5361\u4f4f\u2014\u2014\u53ef\u70b9\u51fb\u300c\u4e2d\u6b62\u300d\u6216\u300c\u91cd\u542f\u540e\u7aef\u300d'}
        </div>
      )}

      <RunView events={displayEvents} workflowId={workflowId} summary={showRunSummary ? runSummary : null} isRunning={isRunning} />
    </div>
  )
}

// \u2500\u2500 Root export \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

const TABS = [
  { id: 'w1', badge: 'W1', title: '\u6295\u9012\u6d41\u7a0b' },
  { id: 'w2', badge: 'W2', title: '\u56de\u590d\u626b\u63cf' },
  { id: 'w3', badge: 'W3', title: '\u53d1\u9001\u56de\u590d' },
  // 多站点 Layer 1。后端的步骤骨架里没有它们的条目，
  // \u90a3\u51e0\u5f20\u8868\u662f\u624b\u7ef4\u62a4\u7684\u9759\u6001\u6a21\u677f\uff08\u5df2\u7ecf\u56e0\u4e3a\u6f02\u79fb\u8bb0\u8fc7\u4e00\u6b21\u6848\uff09\uff0c
  // \u7559\u7a7a = \u53ea\u663e\u793a\u771f\u5b9e\u6536\u5230\u7684\u4e8b\u4ef6\uff0c\u4ee5\u540e\u8981\u505a\u8be6\u7ec6\u9aa8\u67b6\u518d\u5f80\u91cc\u586b\u3002
  { id: 'm1', badge: 'M1', title: '\u591a\u7ad9\u9009\u5c97' },
  { id: 'm2', badge: 'M2', title: '\u52d8\u5bdf\u8868\u5355' },
] as const

const TAB_BADGE_CLS: Record<string, string> = {
  w1: 'bg-signal-blue/18 text-signal-bright',
  w2: 'bg-signal-purple/18 text-signal-purple',
  w3: 'bg-signal-teal/18 text-signal-teal',
  m1: 'bg-signal-amber/18 text-signal-amber',
  m2: 'bg-signal-red/18 text-signal-red',
}

// W1/W2/W3 are mutually exclusive (one workflow runs at a time), so they share a
// single full-size frame and switch via tabs instead of three cramped cards.
// The active tab auto-follows whichever workflow starts running; the user can
// still click a tab to inspect another pipeline's last run.
export default function WorkflowTrack() {
  const { progressEvents, workflowRunning } = useAppContext()
  const [tab, setTab] = useState<string>('w1')

  // Jump to the running workflow whenever it changes (mutual exclusion means the
  // running one is what the user wants to watch). value-change guard avoids
  // yanking focus back while the user browses another tab mid-run.
  useEffect(() => {
    if (workflowRunning) setTab(workflowRunning)
  }, [workflowRunning])

  const events = useMemo(
    () => progressEvents.filter((e) => e.workflow === tab),
    [progressEvents, tab],
  )
  return (
    <div className="relative space-y-3">
      <DevLabel name="WorkflowTrack" float />
      {/* Tab bar */}
      <div className="flex gap-1.5">
        {TABS.map((t) => {
          const isActive = tab === t.id
          const running = workflowRunning === t.id
          const badgeCls = TAB_BADGE_CLS[t.id] ?? 'bg-signal-teal/18 text-signal-teal'
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className={`flex items-center gap-2 rounded-xl px-3 py-1.5 text-sm transition ${
                isActive ? 'bg-bg-card shadow-card text-text-1' : 'text-text-3 hover:bg-white/[0.04] hover:text-text-2'
              }`}
              style={isActive ? { border: '1px solid rgba(255,255,255,0.08)' } : undefined}
            >
              <span className={`rounded font-mono text-[11px] font-bold px-1.5 py-0.5 ${badgeCls}`}>{t.badge}</span>
              <span>{t.title}</span>
              {running && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-signal-green" />}
            </button>
          )
        })}
      </div>

      {/* Single full-size frame; remount per tab so per-instance selection resets */}
      <WorkflowCard
        key={tab}
        workflowId={tab}
        events={events}
        showRunSummary={tab === 'w1' || tab === 'w2'}
      />
    </div>
  )
}
