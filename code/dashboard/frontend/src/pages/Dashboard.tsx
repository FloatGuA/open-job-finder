import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { API } from '@/api'
import type { PendingReply, WechatPending } from '@/api'
import { useAppContext } from '@/context/app-context'
import WorkflowPanel from '@/components/workflow/WorkflowPanel'
import WorkflowTrack from '@/components/workflow/WorkflowTrack'
import { QueueSection } from './Queue'
import DevLabel from '@/components/dev/DevLabel'

interface StatsData {
  total: number
  applied_today: number
  daily_limit: number
  responded: number
  interviews: number
  offers: number
  by_status: Record<string, number>
}

// Keys MUST match schemas.py AppStatus enum exactly (FOUND/APPLIED/INTERVIEWING/
// OFFER/REJECTED) \u2014 backend get_stats().by_status keys on those. Ordered as the
// pipeline funnel (left\u2192right on the stacked bar). FOUND is pre-apply (rarely persisted).
const STATUS_META: Array<{ key: string; label: string; color: string }> = [
  { key: 'FOUND',        label: '\u5df2\u53d1\u73b0', color: 'rgba(255,255,255,0.14)' },
  { key: 'APPLIED',      label: '\u5df2\u6295\u9012', color: '#0a84ff' },
  { key: 'INTERVIEWING', label: '\u9762\u8bd5\u4e2d', color: '#ff9f0a' },
  { key: 'OFFER',        label: 'Offer',  color: '#ffd60a' },
  { key: 'REJECTED',     label: '\u5df2\u62d2\u7edd', color: '#ff453a' },
]


function StatusBar({ byStatus, total }: { byStatus: Record<string, number>; total: number }) {
  if (!total) return null
  const shown = STATUS_META.filter(({ key }) => (byStatus[key] ?? 0) > 0)
  return (
    <div className="relative overflow-hidden rounded-2xl bg-bg-card p-4 shadow-card">
      <div className="pointer-events-none absolute inset-0 rounded-2xl" style={{ border: '1px solid rgba(255,255,255,0.08)' }} />
      <div className="mb-3 flex items-center justify-between">
        <span className="flex items-center gap-2">
          <p className="text-xs font-semibold uppercase tracking-wider text-text-3">{'\u72b6\u6001\u5206\u5e03'}</p>
          <DevLabel name="StatusBar" />
        </span>
        <p className="font-mono text-xs text-text-3">{total}{' \u603b\u8ba1'}</p>
      </div>
      {/* Stacked bar */}
      <div className="flex h-2.5 w-full overflow-hidden rounded-full" style={{ background: 'rgba(255,255,255,0.05)' }}>
        {shown.map(({ key, color }) => {
          const pct = ((byStatus[key] ?? 0) / total) * 100
          return (
            <div
              key={key}
              style={{ width: `${pct}%`, background: color, minWidth: pct > 0 ? '2px' : 0 }}
              title={`${key}: ${byStatus[key]}`}
            />
          )
        })}
      </div>
      {/* Legend */}
      <div className="mt-3 flex flex-wrap gap-x-6 gap-y-2">
        {shown.map(({ key, label, color }) => (
          <div key={key} className="flex items-center gap-2 text-sm text-text-2">
            <span className="h-2 w-2 shrink-0 rounded-sm" style={{ background: color }} />
            <span>{label}</span>
            <span className="font-mono text-text-3">{byStatus[key]}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

function StatCard({
  title,
  value,
  desc,
  descNode,
  tone,
}: {
  title: string
  value?: string | number
  desc?: string
  descNode?: ReactNode
  tone?: 'green' | 'amber'
}) {
  const toneCls = tone === 'green' ? 'text-signal-green' : tone === 'amber' ? 'text-signal-amber' : 'text-white'
  return (
    <div className="relative overflow-hidden rounded-2xl bg-bg-card p-5 shadow-card">
      <div className="pointer-events-none absolute inset-0 rounded-2xl" style={{ border: '1px solid rgba(255,255,255,0.08)' }} />
      <p className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-text-3">
        {title}
        <DevLabel name="StatCard" />
      </p>
      <p className={`mt-2 font-mono text-[38px] font-semibold leading-none ${toneCls}`} style={{ letterSpacing: '-1px' }}>
        {value === undefined ? '\u2014' : value}
      </p>
      {descNode ? <div className="mt-1.5">{descNode}</div> : desc && <p className="mt-1.5 text-xs text-text-3">{desc}</p>}
    </div>
  )
}

function ApproveBar({ onGo }: { onGo: () => void }) {
  const [items, setItems] = useState<PendingReply[]>([])

  useEffect(() => {
    const load = () => API.getPendingReplies().then(setItems).catch(() => {})
    void load()
    const id = window.setInterval(load, 15_000)
    return () => window.clearInterval(id)
  }, [])

  if (items.length === 0) return null
  const companies = items.slice(0, 3).map((i) => i.company).filter(Boolean).join(' \u00b7 ')

  return (
    <div
      className="relative flex items-center gap-3 overflow-hidden rounded-2xl px-4 py-2.5"
      style={{
        background: 'linear-gradient(100deg,rgba(255,159,10,0.12),rgba(255,159,10,0.04) 70%)',
        border: '1px solid rgba(255,159,10,0.26)',
      }}
    >
      <span className="absolute left-0 top-0 bottom-0 w-0.5" style={{ background: '#ff9f0a' }} />
      <DevLabel name="ApproveBar" />
      <span className="h-2 w-2 shrink-0 animate-pulse rounded-full" style={{ background: '#ff9f0a' }} />
      <p className="shrink-0 text-sm font-semibold" style={{ color: '#ffd699', letterSpacing: '-0.224px' }}>
        <span className="font-mono" style={{ color: '#ff9f0a' }}>{items.length}</span>
        {' \u6761 HR \u56de\u590d\u5f85\u5ba1\u6279'}
      </p>
      <span className="hidden min-w-0 flex-1 truncate text-xs text-text-3 sm:block" title={companies}>{companies}</span>
      <button
        type="button"
        onClick={onGo}
        className="ml-auto inline-flex shrink-0 items-center gap-2 rounded-lg px-3.5 py-1.5 text-xs font-semibold transition hover:brightness-110"
        style={{ background: '#ff9f0a', color: '#1a1200' }}
      >
        {'\u524d\u5f80\u4f1a\u8bdd\u5ba1\u6279 \u2192'}
      </button>
    </div>
  )
}

// Strong Dashboard reminder: HRs who sent their WeChat and still need adding.
function WechatReminderCard({ onGo }: { onGo: () => void }) {
  const { workflowRunning } = useAppContext()
  const [items, setItems] = useState<WechatPending[]>([])
  const [q, setQ] = useState('')

  const load = useCallback(
    () => API.getWechatPending().then((d) => setItems(d.conversations)).catch(() => {}),
    [],
  )
  useEffect(() => {
    void load()
    const id = window.setInterval(() => void load(), 20_000)
    return () => window.clearInterval(id)
  }, [load])

  if (items.length === 0) return null
  const needle = q.trim().toLowerCase()
  const filtered = needle
    ? items.filter((i) => `${i.company}${i.hr_name}${i.hr_title}${i.wechat_id}`.toLowerCase().includes(needle))
    : items

  const dismiss = (convId: string) => {
    setItems((prev) => prev.filter((i) => i.conv_id !== convId))
    API.dismissWechat(convId).catch(() => void load())
  }

  return (
    <div
      className="relative overflow-hidden rounded-2xl px-4 py-3"
      style={{
        background: 'linear-gradient(100deg,rgba(48,209,88,0.14),rgba(48,209,88,0.04) 70%)',
        border: '1px solid rgba(48,209,88,0.3)',
      }}
    >
      <span className="absolute left-0 top-0 bottom-0 w-0.5" style={{ background: '#30d158' }} />
      <div className="mb-2.5 flex items-center gap-3">
        <DevLabel name="WechatReminderCard" />
        <span className="h-2 w-2 shrink-0 animate-pulse rounded-full" style={{ background: '#30d158' }} />
        <p className="shrink-0 text-sm font-semibold" style={{ color: '#9ff0b6', letterSpacing: '-0.224px' }}>
          <span className="font-mono" style={{ color: '#30d158' }}>{items.length}</span>
          {' \u4f4d HR \u5f85\u52a0\u5fae\u4fe1'}
        </p>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder={'\u7b5b\u9009\u516c\u53f8/HR'}
          className="ml-auto w-40 rounded-lg px-2.5 py-1 text-xs text-white placeholder:text-text-3 focus:outline-none"
          style={{ background: 'rgba(0,0,0,0.28)', border: '1px solid rgba(255,255,255,0.1)' }}
        />
        <button
          type="button"
          onClick={onGo}
          className="shrink-0 rounded-lg px-3 py-1 text-xs font-semibold transition hover:brightness-110"
          style={{ background: '#30d158', color: '#08240f' }}
        >
          {'\u524d\u5f80\u4f1a\u8bdd \u2192'}
        </button>
      </div>
      <div className="flex flex-col gap-1.5">
        {filtered.map((i) => (
          <div
            key={i.conv_id}
            className="flex items-center gap-2 rounded-lg px-2.5 py-1.5"
            style={{ background: 'rgba(0,0,0,0.18)' }}
          >
            <span className="min-w-0 truncate text-sm text-text-1" style={{ letterSpacing: '-0.224px' }}>
              {i.company}
              <span className="mx-1.5 text-text-3">{'\u00b7'}</span>
              <span className="text-text-2">{i.hr_name}</span>
              {i.hr_title && <span className="ml-1.5 text-xs text-text-3">{i.hr_title}</span>}
            </span>
            <span className="ml-2 shrink-0 font-mono text-xs font-semibold" style={{ color: '#30d158' }}>{i.wechat_id}</span>
            <button
              type="button"
              onClick={() => API.openInBrowser(i.conv_id).catch(() => {})}
              disabled={workflowRunning !== null}
              className="ml-auto shrink-0 rounded-md px-2 py-0.5 text-[11px] text-signal-bright transition hover:bg-signal-blue/10 disabled:cursor-not-allowed disabled:opacity-40"
              style={{ background: 'rgba(10,132,255,0.1)' }}
            >
              {'\u2197 \u5728 Boss \u6253\u5f00'}
            </button>
            <button
              type="button"
              onClick={() => dismiss(i.conv_id)}
              className="shrink-0 rounded-md px-2 py-0.5 text-[11px] text-text-2 transition hover:text-text-1"
              style={{ background: 'rgba(255,255,255,0.08)' }}
            >
              {'\u5df2\u6dfb\u52a0'}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

// \u6bcf\u65e5\u6295\u9012\u4e0a\u9650\u53ef\u7f16\u8f91\uff08Boss\u76f4\u8058\u786c\u4e0a\u9650\uff09\uff1a\u70b9\u51fb\u6539 \u2192 \u5b58 user_settings(daily_limit) \u2192 \u5237\u65b0
function DailyLimitEditor({ value, onSaved }: { value: number; onSaved: () => void }) {
  const [editing, setEditing] = useState(false)
  const [val, setVal] = useState(value)
  const [saving, setSaving] = useState(false)
  useEffect(() => { setVal(value) }, [value])
  const save = async () => {
    setSaving(true)
    try {
      await API.updateSchedule({ daily_limit: Math.max(0, val) })
      setEditing(false)
      onSaved()
    } catch {
      // \u4fdd\u6301\u7f16\u8f91\u6001\uff0c\u8ba9\u7528\u6237\u91cd\u8bd5
    } finally {
      setSaving(false)
    }
  }
  if (!editing) {
    return (
      <button type="button" onClick={() => setEditing(true)}
        className="text-xs text-text-3 transition hover:text-text-1" style={{ letterSpacing: '-0.12px' }}>
        {'\u65e5\u4e0a\u9650 '}{value}{'  \u270e \u6539'}
      </button>
    )
  }
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-xs text-text-3">{'\u65e5\u4e0a\u9650'}</span>
      <input type="number" min={0} value={val} autoFocus
        onChange={(e) => setVal(Math.max(0, parseInt(e.target.value, 10) || 0))}
        className="w-16 rounded bg-bg-card2 px-1.5 py-0.5 text-xs text-text-1" style={{ border: '1px solid rgba(255,255,255,0.12)' }} />
      <button type="button" onClick={() => void save()} disabled={saving} className="text-xs text-signal-blue disabled:opacity-40">{saving ? '\u2026' : '\u4fdd\u5b58'}</button>
      <button type="button" onClick={() => { setEditing(false); setVal(value) }} className="text-xs text-text-3">{'\u53d6\u6d88'}</button>
    </div>
  )
}

export default function Dashboard() {
  const { setPage } = useAppContext()
  const [stats, setStats] = useState<StatsData | null>(null)

  const load = useCallback(
    () => API.getStats().then((d) => setStats(d.stats as unknown as StatsData)).catch(() => {}),
    [],
  )

  useEffect(() => {
    void load()
    const id = window.setInterval(() => void load(), 30_000)
    return () => window.clearInterval(id)
  }, [load])

  return (
    <div className="space-y-5">
      {/* Pending approval \u2014 jumps to Chat (sole approval UI) */}
      <ApproveBar onGo={() => setPage('chat')} />

      {/* Strong reminder: HRs who sent WeChat still to be added */}
      <WechatReminderCard onGo={() => setPage('chat')} />

      {/* Telemetry */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard title={'\u603b\u804c\u4f4d'} value={stats?.total} desc={'\u7d2f\u8ba1\u53d1\u73b0'} />
        <StatCard
          title={'\u4eca\u65e5\u6295\u9012'}
          value={stats ? `${stats.applied_today} / ${stats.daily_limit}` : undefined}
          tone="amber"
          descNode={stats ? <DailyLimitEditor value={stats.daily_limit} onSaved={load} /> : undefined}
        />
        <StatCard title={'\u5df2\u83b7\u56de\u590d'} value={stats?.responded} tone="green" desc={'HR \u4e3b\u52a8\u56de\u5e94'} />
        <StatCard
          title={'\u9762\u8bd5 \u00b7 Offer'}
          value={stats ? (stats.interviews ?? 0) + (stats.offers ?? 0) : undefined}
          desc={stats ? `${stats.interviews ?? 0} \u9762\u8bd5 \u00b7 ${stats.offers ?? 0} offer` : undefined}
        />
      </div>

      {stats?.by_status && <StatusBar byStatus={stats.by_status} total={stats.total} />}

      {/* Command center: control (left, sticky) | live monitor (right, long) */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[minmax(460px,540px)_1fr] xl:items-start">
        <div className="space-y-4 xl:sticky xl:top-0">
          <div>
            <p className="mb-2 text-[10px] font-medium tracking-widest text-text-3 uppercase select-none">CONTROL</p>
            <WorkflowPanel />
          </div>
          <div>
            <p className="mb-2 text-[10px] font-medium tracking-widest text-text-3 uppercase select-none">QUEUE</p>
            <QueueSection />
          </div>
        </div>
        <div>
          <p className="mb-2 text-[10px] font-medium tracking-widest text-text-3 uppercase select-none">LIVE</p>
          <WorkflowTrack />
        </div>
      </div>

    </div>
  )
}
