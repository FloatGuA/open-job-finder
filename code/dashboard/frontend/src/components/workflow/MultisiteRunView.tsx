import { useEffect, useMemo, useRef, useState } from 'react'
import { API } from '@/api'
import type { ProgressEvent } from '@/hooks/useWorkflowStream'
import {
  agentRows,
  agentTurns,
  forWorkflow,
  runSummary,
  stageStatuses,
  stageSummary,
  type StageStatus,
} from './multisiteRun'

// \u7b2c 1 \u5c42\uff1a\u9759\u6001\u5168\u94fe\uff0c\u53ea\u9ad8\u4eae\u5f53\u524d\u6bb5\u3002**\u4e0d\u67e5\u8de8 run \u771f\u5b9e\u72b6\u6001**\u2014\u2014\u90a3\u8981\u5148\u628a layer \u4e4b\u95f4\u7684
// \u72b6\u6001\u6d41\u8f6c\u5b9a\u6b7b\uff0c\u800c\u90a3\u662f\u7528\u6237\u660e\u786e\u8bf4"\u8fd8\u6ca1\u60f3\u6e05\u695a\u3001\u8981\u5355\u72ec\u7406"\u7684\u90e8\u5206\uff08spec \u00a73\uff09\u3002
// Layer 3 = \u63d0\u4ea4 + \u56de\u7ad9\u70b9\u6293\u5df2\u6295\u9012\u622a\u56fe\uff0c\u76ee\u524d\u8fd8\u6ca1\u5efa\uff0c\u753b\u6210\u865a\u7ebf\u3002
const PIPELINE: { id: string; label: string; unbuilt?: boolean }[] = [
  { id: 'm1', label: '\u9009\u5c97' },
  { id: 'cp1', label: '\u5ba1\u6279\u2460' },
  { id: 'm2', label: '\u586b\u8868' },
  { id: 'cp2', label: '\u5ba1\u6279\u2461' },
  { id: 'l3', label: 'Layer 3', unbuilt: true },
]

const STAGE_DOT: Record<StageStatus, string> = {
  pending: 'bg-text-3/30',
  running: 'bg-signal-blue animate-pulse',
  done: 'bg-signal-green',
  // partial = 跑完了但没干完（步数耗尽）。黄色，绝不能跟 done 一样绿。
  partial: 'bg-signal-amber',
  error: 'bg-signal-red',
}

export default function MultisiteRunView({
  events,
  workflowId,
  isRunning = false,
}: {
  events: ProgressEvent[]
  workflowId: string
  isRunning?: boolean
}) {
  const [stages, setStages] = useState<string[]>([])
  const [maxSteps, setMaxSteps] = useState<number | null>(null)
  const [picked, setPicked] = useState<string | null>(null)

  // 先滤掉别的 workflow 的事件，下面所有派生量都用 evs 而不是 events。
  const evs = useMemo(() => forWorkflow(events, workflowId), [events, workflowId])

  // \u9aa8\u67b6\u4ece\u540e\u7aef\u56fe\u5b9a\u4e49\u53d6\uff0c\u4e0d\u5728\u524d\u7aef\u624b\u6284\u2014\u2014W1/W2 \u7684 SKELETON \u5c31\u662f\u624b\u6284\u7684\uff0c\u5df2\u7ecf\u6f02\u79fb\u8fc7\u3002
  useEffect(() => {
    let alive = true
    API.multisiteStages().then((r) => {
      if (!alive) return
      setStages(workflowId === 'm1' ? r.m1 : r.m2)
      setMaxSteps(r.max_steps ?? null)
    })
    return () => {
      alive = false
    }
  }, [workflowId])

  const statuses = useMemo(() => stageStatuses(evs, stages), [evs, stages])

  // \u9ed8\u8ba4\u8ddf\u968f"\u6700\u540e\u4e00\u4e2a\u5df2\u7ecf\u5f00\u8dd1\u7684\u7ad9"\uff1b\u7528\u6237\u70b9\u8fc7\u5c31\u56fa\u5b9a\u5728\u4ed6\u9009\u7684\u90a3\u4e2a\u3002
  const latest = useMemo(
    () => [...stages].reverse().find((s) => statuses[s] !== 'pending') ?? stages[0] ?? null,
    [stages, statuses],
  )
  const following = !(picked && stages.includes(picked))
  const active = following ? latest : picked
  const rows = useMemo(() => (active ? agentRows(evs, active) : []), [evs, active])
  // 阶段自己的产出。ensure_ready / write_pending_jobs 没有 agent 循环，
  // 第 3 层是空的——它们的信息全在这里。
  const summary = useMemo(() => (active ? stageSummary(evs, active) : null), [evs, active])
  const finished = useMemo(() => runSummary(evs), [evs])
  // 内层 ReAct 的位置：用掉几轮模型调用 / 上限多少。没有分母的话，
  // 「跑了 34 轮」读者无从判断是宽裕还是快撞墙。
  const turns = useMemo(() => (active ? agentTurns(evs, active) : 0), [evs, active])

  // \u5931\u8d25\u90a3\u4e00\u7ad9\u7684\u5b8c\u6574\u5feb\u7167\uff1a\u6587\u4ef6\u540d\u6765\u81ea\u5931\u8d25\u4e8b\u4ef6\u7684 detail\uff0c\u8ddf applyFailScreenshot
  // \u4ece\u4e8b\u4ef6 detail \u6260\u6587\u4ef6\u540d\u662f\u540c\u4e00\u4e2a\u8def\u5b50\u3002
  const runId = (evs.find((e) => e.step === 'start')?.detail?.run_id as string) || ''
  const snapshotFile = active
    ? ((evs.find((e) => e.step === active && e.seq == null && e.status === 'error')
        ?.detail?.snapshot_file as string) || '')
    : ''

  // \u8ddf\u968f\u6700\u65b0\uff1a\u7528\u6237\u624b\u52a8\u4e0a\u6eda\u540e\u505c\u6b62\u8ddf\u968f\uff08\u4e0e\u73b0\u6709 LiveLog \u540c\u6b3e\uff09\u3002
  const boxRef = useRef<HTMLDivElement | null>(null)
  const stickRef = useRef(true)
  useEffect(() => {
    const box = boxRef.current
    if (box && stickRef.current) box.scrollTop = box.scrollHeight
  }, [rows.length])

  return (
    <div className="space-y-4">
      {/* \u7b2c 1 \u5c42 */}
      <div className="flex items-center gap-1 overflow-x-auto">
        {PIPELINE.map((seg, i) => (
          <div key={seg.id} className="flex shrink-0 items-center gap-1">
            {i > 0 && <span className={seg.unbuilt ? 'text-text-3/40' : 'text-text-3'}>{'\u2500\u2500'}</span>}
            <span
              className="rounded-lg px-2.5 py-1 text-[12px]"
              style={
                seg.id === workflowId
                  ? { background: 'rgba(10,132,255,0.16)', color: '#0a84ff', fontWeight: 600 }
                  : { color: seg.unbuilt ? 'rgba(255,255,255,0.25)' : 'rgba(255,255,255,0.45)' }
              }
            >
              {seg.label}
            </span>
          </div>
        ))}
      </div>

      {/* \u7b2c 2 \u5c42\uff1a\u5730\u94c1\u7ad9\u3002\u70b9\u4e00\u7ad9\u770b\u90a3\u4e00\u7ad9\u7684\u65f6\u95f4\u7ebf\u3002 */}
      <div className="flex flex-wrap items-center gap-1">
        {/* \u8ddf\u968f\u6700\u65b0\uff1a\u70b9\u8fc7\u4efb\u4f55\u4e00\u7ad9\u5c31\u56fa\u5b9a\u5728\u90a3\u91cc\uff0c\u6ca1\u8fd9\u4e2a\u6309\u94ae\u5c31\u51fa\u4e0d\u53bb\u4e86\u3002 */}
        {stages.map((s, i) => (
          <div key={s} className="flex items-center gap-1">
            {i > 0 && <span className="text-text-3">{'\u2500\u2500'}</span>}
            <button
              type="button"
              onClick={() => setPicked(s)}
              className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-[12px] transition ${
                s === active ? 'bg-white/[0.08] text-text-1' : 'text-text-2 hover:bg-white/[0.04]'
              }`}
            >
              <span className={`h-2 w-2 rounded-full ${STAGE_DOT[statuses[s] ?? 'pending']}`} />
              <span className="font-mono">{s}</span>
              {(() => {
                const d = stageSummary(evs, s)?.durationMs
                return d != null ? (
                  <span className="font-mono text-[10.5px] text-text-3">{fmtMs(d)}</span>
                ) : null
              })()}
            </button>
          </div>
        ))}
        {!following && (
          <button
            type="button"
            onClick={() => setPicked(null)}
            className="ml-1 rounded px-2 py-0.5 text-[10.5px] text-text-3 transition hover:bg-white/[0.06] hover:text-text-1"
          >
            {'\u56de\u5230\u8ddf\u968f\u6700\u65b0'}
          </button>
        )}
        {following && (
          <span className="ml-1 flex items-center gap-1 text-[10.5px] text-text-3">
            <span className="h-1.5 w-1.5 rounded-full bg-signal-green" />
            {'\u8ddf\u968f\u6700\u65b0'}
          </span>
        )}
      </div>

      {/* \u672c\u9636\u6bb5\u4ea7\u51fa\u3002\u7b2c 3 \u5c42\u53ea\u6709 agent \u6d3b\u52a8\uff0c\u800c\u786e\u5b9a\u6027\u9636\u6bb5\u6839\u672c\u6ca1\u6709 agent \u5faa\u73af\uff0c
          \u4e0d\u628a step \u81ea\u5df1\u7684\u4ea7\u51fa\u6446\u51fa\u6765\u7684\u8bdd\uff0c\u5b83\u4eec\u770b\u8d77\u6765\u5c31\u662f\u4e00\u7247\u7a7a\u767d\u3002 */}
      {summary && (
        <div
          className="rounded-xl px-3 py-2"
          style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)' }}
        >
          <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wider text-text-3">
            {'\u672c\u9636\u6bb5\u4ea7\u51fa'}
            {summary.durationMs != null && (
              <span className="ml-2 font-mono normal-case text-text-3">{fmtMs(summary.durationMs)}</span>
            )}
          </p>
          {summary.error && (
            <p className="mb-1 font-mono text-[11.5px] text-signal-red">{summary.error}</p>
          )}
          {summary.status === 'partial' && (
            <p className="mb-1 text-[11.5px] text-signal-amber">{'\u6b65\u6570\u8017\u5c3d\uff0c\u7ed3\u679c\u662f\u90e8\u5206\u7684\u2014\u2014\u540d\u989d\u6ca1\u6ee1\u7684\u7c7b\u522b\u53ef\u80fd\u53ea\u662f\u6ca1\u626b\u5230\uff0c\u4e0d\u4ee3\u8868\u7ad9\u4e0a\u6ca1\u6709'}</p>
          )}
          {Object.keys(summary.data).length === 0 ? (
            <p className="font-mono text-[11.5px] text-text-3">{'\u8fd9\u4e00\u9636\u6bb5\u6ca1\u6709\u7ed3\u6784\u5316\u4ea7\u51fa'}</p>
          ) : (
            <div className="flex flex-wrap gap-x-4 gap-y-1">
              {Object.entries(summary.data).map(([k, v]) => (
                <span key={k} className="font-mono text-[11.5px] text-text-2">
                  {k}
                  {': '}
                  <span className="text-text-1">
                    {typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v)}
                  </span>
                </span>
              ))}
            </div>
          )}
        </div>
      )}

      {/* \u7b2c 3 \u5c42\uff1aagent \u6bcf\u4e00\u8f6e\u3002append-only\uff0c\u4e0d\u53bb\u91cd\u3002 */}
      <div className="flex items-baseline justify-between">
        <span className="text-[10.5px] font-semibold uppercase tracking-wider text-text-3">
          {'\u5185\u5c42 ReAct \u5faa\u73af'}
        </span>
        {maxSteps != null && (
          <span className="font-mono text-[11px] text-text-3">
            {'\u6a21\u578b\u8f6e\u6b21'}
            {` ${turns} / ${maxSteps} `}
            <span
              className={turns >= maxSteps * 0.8 ? 'text-signal-amber' : 'text-text-3'}
            >
              {`(${Math.round((turns / maxSteps) * 100)}%)`}
            </span>
          </span>
        )}
      </div>
      <div
        ref={boxRef}
        onScroll={(e) => {
          const el = e.currentTarget
          stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 24
        }}
        className="max-h-[420px] overflow-y-auto rounded-xl p-2 font-mono text-[11.5px]"
        style={{ background: 'rgba(0,0,0,0.25)', border: '1px solid rgba(255,255,255,0.06)' }}
      >
        {rows.length === 0 ? (
          <p className="p-2 text-text-3">{isRunning ? '\u7b49\u5f85 agent \u8f93\u51fa\u2026' : '\u8fd9\u4e00\u7ad9\u6ca1\u6709 agent \u6d3b\u52a8'}</p>
        ) : (
          rows.map((ev) => <AgentRow key={`${ev.step}-${ev.seq}`} ev={ev} />)
        )}
      </div>

      {finished && (
        <div
          className="rounded-xl px-3 py-2"
          style={{ background: 'rgba(48,209,88,0.08)', border: '1px solid rgba(48,209,88,0.2)' }}
        >
          <p className="mb-1 text-[10.5px] font-semibold uppercase tracking-wider text-signal-green">
            {'\u672c\u6b21\u8fd0\u884c\u603b\u7ed3'}
          </p>
          <div className="flex flex-wrap gap-x-4 gap-y-1">
            {Object.entries(finished).map(([k, v]) => (
              <span key={k} className="font-mono text-[11.5px] text-text-2">
                {k}
                {': '}
                <span className="text-text-1">
                  {typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v)}
                </span>
              </span>
            ))}
          </div>
        </div>
      )}

      {snapshotFile && runId && (
        <a
          className="text-[11.5px] text-signal-bright underline"
          href={`/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(snapshotFile)}`}
          target="_blank"
          rel="noreferrer"
        >
          {'\u4e0b\u8f7d\u5931\u8d25\u65f6\u7684\u5b8c\u6574\u5feb\u7167'}
        </a>
      )}
    </div>
  )
}

// \u8017\u65f6\uff1a\u6beb\u79d2\u5bf9\u4eba\u6ca1\u6709\u610f\u4e49\uff0c137077ms \u8981\u4e00\u773c\u770b\u51fa\u662f\u4e24\u5206\u591a\u949f\u3002
function fmtMs(ms: number): string {
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  const m = Math.floor(ms / 60000)
  return `${m}m${Math.round((ms % 60000) / 1000)}s`
}

function AgentRow({ ev }: { ev: ProgressEvent }) {
  const d = (ev.detail ?? {}) as Record<string, unknown>
  const seq = String(ev.seq ?? 0).padStart(2, '0')
  if (d.kind === 'think') {
    const calls = (d.calls ?? []) as { name: string; args: Record<string, unknown> }[]
    return (
      <div className="px-2 py-0.5">
        {calls.map((c, i) => (
          <div key={i} className="text-signal-bright">
            {`[${seq}] -> ${c.name}(${JSON.stringify(c.args)})`}
          </div>
        ))}
        {!!d.text && <div className="text-text-1">{`[${seq}] `}{'\u8bf4: '}{String(d.text)}</div>}
      </div>
    )
  }
  return (
    <div className="px-2 py-0.5 text-text-3">
      {`[${seq}] <- ${String(d.tool ?? '')}: ${String(d.chars ?? 0)} `}
      {' \u5b57\u7b26 | '}
      {String(d.head ?? '')}
    </div>
  )
}
