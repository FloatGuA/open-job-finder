import { useEffect, useRef, useState, type ReactNode } from 'react'
import { API, type SelfCheckReport, type SelfCheckCfg, type SelfCheckHistoryEntry } from '@/api'
import DevLabel from '@/components/dev/DevLabel'

function Card({ title, children, dev }: { title: string; children: ReactNode; dev?: string }) {
  return (
    <div className="relative overflow-hidden rounded-2xl bg-bg-card p-6 shadow-card">
      <div className="pointer-events-none absolute inset-0 rounded-2xl" style={{ border: '1px solid rgba(255,255,255,0.08)' }} />
      <h2 className="mb-5 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-text-3">
        {title}
        {dev && <DevLabel name={dev} />}
      </h2>
      {children}
    </div>
  )
}

// \u8f7b\u91cf\u63a2\u9488\uff1a\u6d4f\u89c8\u5668+\u767b\u5f55 / DB / LLM \u5373\u65f6\u5065\u5eb7\u68c0\u67e5\uff08\u53ea\u8bfb\u65e0\u526f\u4f5c\u7528\uff09
function ProbeCard() {
  const [running, setRunning] = useState(false)
  const [report, setReport] = useState<SelfCheckReport | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const run = async () => {
    setRunning(true)
    setErr(null)
    try {
      setReport(await API.runSelfCheck())
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setRunning(false)
    }
  }
  return (
    <Card title={'\u7cfb\u7edf\u63a2\u9488'} dev="ProbeCard">
      <div className="flex items-center justify-between gap-4">
        <p className="min-w-0 flex-1 text-xs text-text-3" style={{ letterSpacing: '-0.12px' }}>
          {'\u4e00\u952e\u63a2\u6d4b \u6d4f\u89c8\u5668+\u767b\u5f55 / \u6570\u636e\u5e93 / LLM \u662f\u5426\u6b63\u5e38\uff08\u7ea6 20-30 \u79d2\uff0c\u53ea\u8bfb\u65e0\u526f\u4f5c\u7528\uff09'}
        </p>
        <button
          type="button"
          onClick={() => void run()}
          disabled={running}
          className="shrink-0 rounded-lg px-4 py-2 text-xs font-medium text-text-1 transition disabled:opacity-40"
          style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', letterSpacing: '-0.12px' }}
        >
          {running ? '\u63a2\u6d4b\u4e2d\uff08\u7ea6 20-30 \u79d2\uff09\u2026' : report ? '\u91cd\u65b0\u63a2\u6d4b' : '\u8fd0\u884c\u63a2\u9488'}
        </button>
      </div>
      {err && <p className="mt-3 text-xs text-signal-red">{err}</p>}
      {report && (
        <div className="mt-4 space-y-2">
          {report.probes.map((p) => (
            <div key={p.name} className="flex items-center gap-3 rounded-xl bg-bg-card2 px-3 py-2.5">
              <span className={`text-base ${p.ok ? 'text-signal-green' : 'text-signal-red'}`}>{p.ok ? '\u2713' : '\u2717'}</span>
              <span className="w-28 shrink-0 text-sm text-text-1" style={{ letterSpacing: '-0.224px' }}>{p.label}</span>
              <span className="min-w-0 flex-1 truncate font-mono text-xs text-text-3" title={p.detail}>{p.detail}</span>
              <span className="shrink-0 font-mono text-[11px] text-text-3">{p.duration_ms}ms</span>
            </div>
          ))}
        </div>
      )}
    </Card>
  )
}

// \u5b9a\u65f6\u5e38\u6001\u81ea\u68c0\uff1a\u6bcf\u9694 N \u5c0f\u65f6\u771f\u8dd1 W1+W2\uff08\u63a2\u9488\u2192W1\u2192W2 \u4e32\u884c\uff09\uff0c\u914d\u7f6e + \u7acb\u5373\u89e6\u53d1
function ScheduledCard({ onRan }: { onRan: () => void }) {
  const [cfg, setCfg] = useState<SelfCheckCfg | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [running, setRunning] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  // Poll handles from runNow. Kept in refs so unmounting cancels them: they were
  // previously local consts, so navigating away within the 10-minute window left
  // the interval firing onRan into a dead component for up to 10 minutes.
  const pollRef = useRef<number | null>(null)
  const stopRef = useRef<number | null>(null)

  const clearPolling = () => {
    if (pollRef.current !== null) { window.clearInterval(pollRef.current); pollRef.current = null }
    if (stopRef.current !== null) { window.clearTimeout(stopRef.current); stopRef.current = null }
  }

  useEffect(() => {
    void API.getSchedule().then((s) => { if (s.selfcheck) setCfg(s.selfcheck) }).catch(() => {})
    return clearPolling
  }, [])

  const patch = (p: Partial<SelfCheckCfg>) => setCfg((c) => (c ? { ...c, ...p } : c))
  const save = async () => {
    if (!cfg) return
    setSaving(true); setErr(null); setSaved(false)
    try {
      await API.updateSchedule({ selfcheck: cfg })
      setSaved(true)
      window.setTimeout(() => setSaved(false), 3000)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setSaving(false)
    }
  }
  const runNow = async () => {
    setRunning(true); setErr(null)
    try {
      await API.runSelfCheckCycle({})
      // Replace any poll still running from a previous click, then poll for the
      // result and stop after 10 minutes. Both handles live in refs so the
      // unmount cleanup can cancel them.
      clearPolling()
      pollRef.current = window.setInterval(onRan, 15000)
      stopRef.current = window.setTimeout(clearPolling, 600000)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setRunning(false)
    }
  }

  if (!cfg) return null
  const numCls = 'w-20 rounded-lg bg-bg-card2 px-2 py-1 text-sm text-text-1 focus:outline-none'
  const numStyle: React.CSSProperties = { border: '1px solid rgba(255,255,255,0.08)' }
  return (
    <Card title={'\u5b9a\u65f6\u5e38\u6001\u81ea\u68c0\uff08\u771f\u8dd1 W1+W2\uff09'} dev="ScheduledCard">
      <p className="mb-4 text-xs text-text-3" style={{ letterSpacing: '-0.12px' }}>
        {'\u6bcf\u9694\u4e00\u6bb5\u65f6\u95f4\u81ea\u52a8\u771f\u8dd1\u4e00\u6b21\uff1a\u5148\u63a2\u9488\uff08\u767b\u5f55/DB/LLM\uff09\uff0c\u5168\u7eff\u518d\u4e32\u884c\u771f\u6295 W1 + \u68c0\u67e5 W2\u3002\u65e2\u662f\u5e38\u6001\u5316\u8fd0\u884c\uff0c\u4e5f\u662f\u5065\u5eb7\u81ea\u68c0\u3002'}
      </p>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-3">
        <label className="flex items-center gap-2 text-sm text-text-2">
          <input type="checkbox" checked={cfg.enabled} onChange={(e) => patch({ enabled: e.target.checked })} />
          {'\u542f\u7528\u5b9a\u65f6'}
        </label>
        <label className="flex items-center gap-2 text-sm text-text-2">
          {'\u95f4\u9694(\u5c0f\u65f6)'}
          <input type="number" min={1} className={numCls} style={numStyle} value={Math.round(cfg.interval_minutes / 60)}
            onChange={(e) => patch({ interval_minutes: Math.max(1, parseInt(e.target.value, 10) || 1) * 60 })} />
        </label>
        <label className="flex items-center gap-2 text-sm text-text-2">
          {'W1 \u6295\u9012\u6570'}
          <input type="number" min={0} className={numCls} style={numStyle} value={cfg.w1_max}
            onChange={(e) => patch({ w1_max: Math.max(0, parseInt(e.target.value, 10) || 0) })} />
        </label>
        <label className="flex items-center gap-2 text-sm text-text-2">
          {'W2 \u4e0a\u9650'}
          <input type="number" min={1} className={numCls} style={numStyle} value={cfg.w2_max}
            onChange={(e) => patch({ w2_max: Math.max(1, parseInt(e.target.value, 10) || 1) })} />
        </label>
        <label className="flex items-center gap-2 text-sm text-text-2">
          <input type="checkbox" checked={cfg.with_probes} onChange={(e) => patch({ with_probes: e.target.checked })} />
          {'\u5148\u8dd1\u63a2\u9488'}
        </label>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        <button type="button" onClick={() => void save()} disabled={saving}
          className="rounded-lg px-4 py-2 text-xs font-medium text-white transition disabled:opacity-40"
          style={{ background: '#0a84ff', letterSpacing: '-0.12px' }}>
          {saving ? '\u4fdd\u5b58\u4e2d\u2026' : '\u4fdd\u5b58\u914d\u7f6e'}
        </button>
        {saved && <span className="text-xs text-signal-green">{'\u2713 \u5df2\u4fdd\u5b58'}</span>}
        <button type="button" onClick={() => void runNow()} disabled={running}
          className="rounded-lg px-4 py-2 text-xs font-medium text-text-1 transition disabled:opacity-40"
          style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', letterSpacing: '-0.12px' }}>
          {running ? '\u5df2\u89e6\u53d1\uff0c\u540e\u53f0\u771f\u8dd1\u4e2d\u2026' : '\u7acb\u5373\u8dd1\u4e00\u6b21\u5b8c\u6574\u81ea\u68c0'}
        </button>
      </div>
      {err && <p className="mt-3 text-xs text-signal-red">{err}</p>}
    </Card>
  )
}

// \u81ea\u68c0\u5386\u53f2\uff1a\u7a81\u51fa\u5c55\u793a\u6bcf\u6b21\u5b8c\u6574\u81ea\u68c0\u7684\u7ed3\u679c\uff08\u63a2\u9488 + W1 + W2 \u5206\u9636\u6bb5 \u2713/\u2717\uff09
function HistoryCard({ reloadKey }: { reloadKey: number }) {
  const [history, setHistory] = useState<SelfCheckHistoryEntry[]>([])
  useEffect(() => {
    void API.getSelfCheckHistory(20).then(setHistory).catch(() => {})
  }, [reloadKey])
  return (
    <Card title={'\u81ea\u68c0\u5386\u53f2'} dev="HistoryCard">
      {history.length === 0 ? (
        <p className="text-xs text-text-3">{'\u6682\u65e0\u81ea\u68c0\u8bb0\u5f55'}</p>
      ) : (
        <div className="space-y-2">
          {history.map((h, i) => {
            const okAll = h.ok === true
            const time = new Date(h.started_at).toLocaleString('zh-CN', { hour12: false })
            const stageStr = h.skipped_reason
              ? h.skipped_reason
              : h.stages.map((s) => `${s.label}${s.ok ? '\u2713' : '\u2717'}`).join('  ')
            return (
              <div key={i} className="flex items-start gap-3 rounded-xl bg-bg-card2 px-3 py-2.5">
                <span className={`mt-0.5 text-base ${okAll ? 'text-signal-green' : 'text-signal-red'}`}>{okAll ? '\u2713' : '\u2717'}</span>
                <div className="min-w-0 flex-1">
                  <p className="font-mono text-[11px] text-text-3">{time}{' \u00b7 '}{h.trigger_type}</p>
                  <p className="break-all text-xs text-text-2">{stageStr}</p>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </Card>
  )
}

export function SelfCheckSection() {
  const [reloadKey, setReloadKey] = useState(0)
  return (
    <div className="relative space-y-5">
      <DevLabel name="SelfCheckPage" float />
      <ProbeCard />
      <ScheduledCard onRan={() => setReloadKey((k) => k + 1)} />
      <HistoryCard reloadKey={reloadKey} />
    </div>
  )
}
