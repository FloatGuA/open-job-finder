import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react'
import { API, type QueueSnapshot, type QueueItem, type WorkflowId } from '@/api'
import DevLabel from '@/components/dev/DevLabel'

const WF_META: Record<WorkflowId, { label: string; short: string; color: string }> = {
  w1: { label: 'W1 \u6295\u9012', short: 'W1', color: '#0a84ff' },
  w2: { label: 'W2 \u68c0\u67e5', short: 'W2', color: '#30d158' },
  w3: { label: 'W3 \u53d1\u56de\u590d', short: 'W3', color: '#bf5af2' },
}

const SRC_LABEL: Record<string, string> = {
  manual: '\u624b\u52a8',
  queue: '\u961f\u5217',
  scheduled: '\u5b9a\u65f6',
  selfcheck: '\u81ea\u68c0',
}

function WfBadge({ wf }: { wf: WorkflowId }) {
  const m = WF_META[wf]
  return (
    <span
      className="shrink-0 rounded font-mono text-[12px] font-bold px-1.5 py-0.5"
      style={{ background: `${m.color}22`, color: m.color }}
    >
      {m.short}
    </span>
  )
}

function paramsSummary(item: QueueItem): string {
  const p = (item.params || {}) as Record<string, unknown>
  const bits: string[] = []
  if (item.workflow === 'w1') {
    if (p.max_cards != null) bits.push(`\u5361 ${p.max_cards}`)
    if (p.score_threshold != null) bits.push(`\u9608\u503c ${p.score_threshold}`)
  } else if (item.workflow === 'w2') {
    if (p.max_conversations != null) bits.push(`\u4f1a\u8bdd ${p.max_conversations}`)
  } else if (p.max_replies != null) {
    bits.push(`\u56de\u590d ${p.max_replies}`)
  }
  if (p.dry_run) bits.push('\u6f14\u7ec3')
  return bits.length ? bits.join(' \u00b7 ') : '\u9ed8\u8ba4\u53c2\u6570'
}

function fmtTime(iso: string): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleTimeString('zh-CN', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return ''
  }
}

export function QueueSection() {
  const [snap, setSnap] = useState<QueueSnapshot | null>(null)
  const [busy, setBusy] = useState(false)
  const [localPending, setLocalPending] = useState<QueueItem[]>([])
  const [dragId, setDragId] = useState<string | null>(null)
  const draggingRef = useRef(false)

  const load = useCallback(async () => {
    try {
      const s = await API.getWorkflowQueue()
      setSnap(s)
      if (!draggingRef.current) setLocalPending(s.pending)
    } catch {
      // non-fatal
    }
  }, [])

  useEffect(() => {
    void load()
    const id = window.setInterval(() => void load(), 3000)
    return () => window.clearInterval(id)
  }, [load])

  const act = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await fn()
    } finally {
      setBusy(false)
      await load()
    }
  }

  const onDragStart = (id: string) => {
    draggingRef.current = true
    setDragId(id)
  }
  const onDragOver = (e: DragEvent, overId: string) => {
    e.preventDefault()
    if (!dragId || dragId === overId) return
    setLocalPending((prev) => {
      const from = prev.findIndex((i) => i.id === dragId)
      const to = prev.findIndex((i) => i.id === overId)
      if (from < 0 || to < 0 || from === to) return prev
      const next = prev.slice()
      const [m] = next.splice(from, 1)
      next.splice(to, 0, m)
      return next
    })
  }
  const onDragEnd = () => {
    const ids = localPending.map((i) => i.id)
    draggingRef.current = false
    setDragId(null)
    void act(() => API.reorderQueue(ids))
  }

  const current = snap?.current ?? null
  const paused = snap?.paused ?? false
  const recent = snap?.recent ?? []

  return (
    <div className="relative rounded-2xl bg-bg-card p-5 shadow-card">
      <DevLabel name="QueueSection" float />

      <div className="mb-3 flex items-center justify-between">
        <p className="flex items-center gap-2 text-xs text-text-3" style={{ letterSpacing: '-0.12px' }}>
          {'\u6267\u884c\u961f\u5217'}
          <DevLabel name="QueueList" />
        </p>
        <div className="flex items-center gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={() => void act(() => (paused ? API.resumeQueue() : API.pauseQueue()))}
            className="rounded px-2 py-0.5 text-xs transition disabled:opacity-40"
            style={
              paused
                ? { background: 'rgba(48,209,88,0.14)', color: '#30d158', border: '1px solid rgba(48,209,88,0.3)' }
                : { background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.6)', border: '1px solid rgba(255,255,255,0.12)' }
            }
          >
            {paused ? '\u25b6 \u7ee7\u7eed' : '\u23f8 \u6682\u505c'}
          </button>
          {localPending.length > 0 && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void act(() => API.clearWorkflowQueue())}
              className="rounded px-2 py-0.5 text-xs text-text-3 transition hover:text-signal-red disabled:opacity-40"
            >
              {'\u6e05\u7a7a'}
            </button>
          )}
        </div>
      </div>

      {current ? (
        <div
          className="mb-3 flex items-center gap-3 rounded-xl px-3 py-2.5"
          style={{ background: 'rgba(48,209,88,0.08)', border: '1px solid rgba(48,209,88,0.25)' }}
        >
          <span className="h-1.5 w-1.5 animate-pulse rounded-full" style={{ background: '#30d158' }} />
          <WfBadge wf={current.workflow} />
          <span className="text-sm text-text-1">{WF_META[current.workflow].label}</span>
          <span className="text-xs text-text-3">{paramsSummary(current)}</span>
          <span className="font-mono text-[11px] text-text-3">{'\u52a0\u5165 '}{fmtTime(current.enqueued_at)}</span>
          <span className="ml-auto text-xs" style={{ color: '#30d158' }}>{'\u8fd0\u884c\u4e2d'}</span>
        </div>
      ) : (
        <div
          className="mb-3 rounded-xl px-3 py-2.5 text-xs text-text-3"
          style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}
        >
          {paused ? '\u5df2\u6682\u505c\uff0c\u8fd0\u884c\u5b8c\u5f53\u524d\u540e\u4e0d\u518d\u81ea\u52a8\u63a5\u4e0b\u4e00\u4e2a' : '\u5f53\u524d\u7a7a\u95f2\uff0c\u65e0\u8fd0\u884c\u4e2d\u7684\u5de5\u4f5c\u6d41'}
        </div>
      )}

      {localPending.length === 0 ? (
        <p className="text-xs" style={{ color: 'rgba(255,255,255,0.2)' }}>{'\u961f\u5217\u4e3a\u7a7a\uff0c\u7528\u4e0a\u65b9\u63a7\u5236\u53f0\u586b\u53c2\u6570\u540e\u89e6\u53d1\u5373\u52a0\u5165\u961f\u5217'}</p>
      ) : (
        <div className="space-y-1.5">
          {localPending.map((item, i) => (
            <div
              key={item.id}
              draggable={!busy}
              onDragStart={() => onDragStart(item.id)}
              onDragOver={(e) => onDragOver(e, item.id)}
              onDragEnd={onDragEnd}
              className="flex cursor-grab items-center gap-2.5 rounded-xl px-3 py-2 active:cursor-grabbing"
              style={{
                background: dragId === item.id ? 'rgba(10,132,255,0.12)' : 'rgba(255,255,255,0.03)',
                border: dragId === item.id ? '1px solid rgba(10,132,255,0.4)' : '1px solid rgba(255,255,255,0.06)',
                opacity: dragId === item.id ? 0.85 : 1,
              }}
            >
              <span className="shrink-0 text-text-3" title={'\u62d6\u52a8\u6539\u53d8\u987a\u5e8f'}>{'\u283f'}</span>
              <span className="w-4 shrink-0 text-center font-mono text-xs text-text-3">{i + 1}</span>
              <WfBadge wf={item.workflow} />
              <span className="text-sm text-text-2">{WF_META[item.workflow].label}</span>
              <span className="text-xs text-text-3">{paramsSummary(item)}</span>
              <span
                className="rounded px-1 text-[11px]"
                style={{ background: 'rgba(255,255,255,0.06)', color: 'rgba(255,255,255,0.5)' }}
              >
                {SRC_LABEL[item.source] ?? item.source}
              </span>
              <span className="shrink-0 font-mono text-[11px] text-text-3" title={'\u52a0\u5165\u65f6\u95f4'}>
                {'\u52a0\u5165 '}{fmtTime(item.enqueued_at)}
              </span>
              <button
                type="button"
                disabled={busy}
                onClick={() => void act(() => API.removeQueueItem(item.id))}
                className="ml-auto shrink-0 rounded px-1.5 py-0.5 text-text-3 transition hover:text-signal-red disabled:opacity-40"
                title={'\u79fb\u9664'}
              >
                {'\u00d7'}
              </button>
            </div>
          ))}
        </div>
      )}

      {recent.length > 0 && (
        <div className="mt-4 border-t pt-3" style={{ borderColor: 'rgba(255,255,255,0.06)' }}>
          <p className="mb-2 text-xs text-text-3">{'\u6700\u8fd1\u5b8c\u6210'}</p>
          <div className="space-y-1.5">
            {recent.slice(0, 6).map((item) => {
              const ok = item.status === 'done'
              return (
                <div key={item.id} className="flex items-center gap-2.5 text-xs">
                  <span style={{ color: ok ? '#30d158' : '#ff453a' }}>{ok ? '\u2713' : '\u2717'}</span>
                  <WfBadge wf={item.workflow} />
                  <span className="text-text-2">{WF_META[item.workflow].label}</span>
                  <span className="text-text-3">{SRC_LABEL[item.source] ?? item.source}</span>
                  {item.error && <span className="truncate text-signal-red">{item.error}</span>}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}
