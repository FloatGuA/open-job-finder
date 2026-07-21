import { useEffect, useRef, useState, type ReactNode } from 'react'
import { API } from '@/api'
import { useAppContext } from '@/context/app-context'
import DevLabel from '@/components/dev/DevLabel'

export default function WorkflowPanel() {
  const { workflowRunning } = useAppContext()

  const [scoreThreshold, setScoreThreshold] = useState(0)
  const [applyLimit, setApplyLimit] = useState(0)
  const [dryRun, setDryRun] = useState(false)
  const [customUrlEnabled, setCustomUrlEnabled] = useState(false)
  const [customUrl, setCustomUrl] = useState('')
  const [urlHistory, setUrlHistory] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem('ojf_search_url_history') || '[]') } catch { return [] }
  })
  const [maxConversations, setMaxConversations] = useState(30)
  const [days, setDays] = useState(7)
  const [checkInterval, setCheckInterval] = useState(0) // minutes; 0 = disabled
  const [headless, setHeadless] = useState(true)
  const [debug, setDebug] = useState(true)
  const [pending, setPending] = useState<'apply' | 'check' | 'all' | 'reply' | null>(null)
  const [stopping, setStopping] = useState(false)
  const [clearing, setClearing] = useState(false)
  const [clearConfirm, setClearConfirm] = useState(false)
  const clearConfirmTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [savingDefault, setSavingDefault] = useState<'w1' | 'w2' | null>(null)
  const [savedDefault, setSavedDefault] = useState<'w1' | 'w2' | null>(null)

  // Backfill from resolved Layer-3 defaults (config.yaml < user_settings.yaml) so
  // the panel opens with the user's saved defaults, not hardcoded JS values.
  // debug / auto_interval / search_url aren't persisted defaults \u2014 left as-is.
  useEffect(() => {
    void API.getWorkflowDefaults()
      .then(({ w1, w2 }) => {
        if (w1?.score_threshold != null) setScoreThreshold(Number(w1.score_threshold))
        if (w1?.max_cards != null) setApplyLimit(Number(w1.max_cards))
        if (w1?.dry_run != null) setDryRun(Boolean(w1.dry_run))
        if (w1?.headless != null) setHeadless(Boolean(w1.headless))
        if (w2?.max_conversations != null) setMaxConversations(Number(w2.max_conversations))
        if (w2?.no_response_days != null) setDays(Number(w2.no_response_days))
      })
      .catch(() => {})
  }, [])

  const handleSaveDefault = async (wf: 'w1' | 'w2') => {
    setSavingDefault(wf)
    setError(null)
    try {
      const updates =
        wf === 'w1'
          ? { score_threshold: scoreThreshold, max_cards: applyLimit, dry_run: dryRun, headless }
          : { max_conversations: maxConversations, no_response_days: days, headless }
      await API.saveWorkflowDefault(wf, updates)
      setSavedDefault(wf)
      window.setTimeout(() => setSavedDefault((p) => (p === wf ? null : p)), 1500)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSavingDefault(null)
    }
  }

  const renderSaveDefault = (wf: 'w1' | 'w2') => (
    <button
      type="button"
      onClick={() => void handleSaveDefault(wf)}
      disabled={savingDefault !== null}
      className="ml-auto shrink-0 rounded-lg px-2.5 py-1 text-xs text-text-3 transition hover:bg-bg-card2 hover:text-text-1 disabled:opacity-40"
      title={'\u628a\u5f53\u524d\u53c2\u6570\u4fdd\u5b58\u4e3a\u9ed8\u8ba4\uff08\u5199\u5165 user_settings.yaml\uff0c\u4e0b\u6b21\u6253\u5f00\u81ea\u52a8\u56de\u586b\uff09'}
    >
      {savedDefault === wf ? '\u2713 \u5df2\u8bbe\u4e3a\u9ed8\u8ba4' : savingDefault === wf ? '\u4fdd\u5b58\u4e2d\u2026' : '\u8bbe\u4e3a\u9ed8\u8ba4'}
    </button>
  )

  // Refs so setInterval callback always sees the latest values without restarts.
  const workflowRunningRef = useRef(workflowRunning)
  const pendingRef = useRef(pending)
  const checkParamsRef = useRef({ maxConversations, days, headless, debug })
  useEffect(() => { workflowRunningRef.current = workflowRunning }, [workflowRunning])
  useEffect(() => { pendingRef.current = pending }, [pending])
  useEffect(() => {
    checkParamsRef.current = { maxConversations, days, headless, debug }
  }, [maxConversations, days, headless, debug])

  // Auto-poll W2: fire every `checkInterval` minutes when no workflow is running.
  useEffect(() => {
    if (checkInterval <= 0) return
    const id = setInterval(() => {
      if (workflowRunningRef.current === null && pendingRef.current === null) {
        const { maxConversations: mc, days: d, headless: h, debug: dbg } = checkParamsRef.current
        setPending('check')
        API.triggerCheckWorkflow({ max_conversations: mc, no_response_days: d, headless: h, debug: dbg })
          .catch((e: Error) => setError(e.message))
          .finally(() => setPending(null))
      }
    }, checkInterval * 60 * 1000)
    return () => clearInterval(id)
  }, [checkInterval])

  const flashInfo = (msg: string) => {
    setInfo(msg)
    window.setTimeout(() => setInfo(null), 2500)
  }

  const saveToHistory = (url: string) => {
    const trimmed = url.trim()
    if (!trimmed) return
    const next = [trimmed, ...urlHistory.filter(u => u !== trimmed)].slice(0, 10)
    setUrlHistory(next)
    localStorage.setItem('ojf_search_url_history', JSON.stringify(next))
  }

  const buildApplyPayload = () => {
    const payload: Record<string, unknown> = {
      score_threshold: scoreThreshold,
      max_cards: applyLimit > 0 ? applyLimit : null,
      dry_run: dryRun,
      headless,
      debug,
    }
    if (customUrlEnabled && customUrl.trim()) {
      payload.search_url = customUrl.trim()
      saveToHistory(customUrl.trim())
    }
    return payload
  }

  const handleApply = async () => {
    setError(null)
    setInfo(null)
    setPending('apply')
    try {
      const res = (await API.triggerApplyWorkflow(buildApplyPayload())) as { status?: string }
      flashInfo(res?.status === 'started' ? '\u5df2\u5f00\u59cb\u6295\u9012' : '\u5df2\u6392\u5165\u961f\u5217')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPending(null)
    }
  }

  const handleCheck = async () => {
    setError(null)
    setInfo(null)
    setPending('check')
    try {
      const res = (await API.triggerCheckWorkflow({ max_conversations: maxConversations, no_response_days: days, headless, debug })) as { status?: string }
      flashInfo(res?.status === 'started' ? '\u5df2\u5f00\u59cb\u68c0\u67e5' : '\u5df2\u6392\u5165\u961f\u5217')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPending(null)
    }
  }

  const handleReply = async () => {
    setError(null)
    setInfo(null)
    setPending('reply')
    try {
      const res = (await API.triggerReplyWorkflow({ headless, debug })) as { status?: string }
      flashInfo(res?.status === 'started' ? '\u5df2\u5f00\u59cb\u53d1\u9001' : '\u5df2\u6392\u5165\u961f\u5217')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPending(null)
    }
  }

  const handleStop = async () => {
    setStopping(true)
    setError(null)
    try {
      await API.stopWorkflow()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setStopping(false)
    }
  }

  const handleClearClick = () => {
    if (!clearConfirm) {
      setClearConfirm(true)
      // Auto-cancel confirmation after 4 s
      clearConfirmTimer.current = setTimeout(() => setClearConfirm(false), 4000)
      return
    }
    // Second click: execute
    if (clearConfirmTimer.current) clearTimeout(clearConfirmTimer.current)
    setClearConfirm(false)
    setClearing(true)
    setError(null)
    setInfo(null)
    API.clearPendingJobs()
      .then(({ deleted }) => {
        setInfo(`\u5df2\u6e05\u9664 ${deleted} \u6761\u5f85\u5904\u7406\u8bb0\u5f55`)
        setTimeout(() => setInfo(null), 3000)
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setClearing(false))
  }

  const handleAll = async () => {
    setError(null)
    setInfo(null)
    setPending('all')
    try {
      await API.enqueueWorkflowChain([
        { workflow: 'w1', params: buildApplyPayload() },
        { workflow: 'w2', params: { max_conversations: maxConversations, no_response_days: days, headless, debug } },
      ])
      flashInfo('\u5df2\u6392\u5165\u961f\u5217\uff1aW1 \u2192 W2')
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPending(null)
    }
  }

  const customUrlMissing = customUrlEnabled && !customUrl.trim()
  const disabled = pending !== null || customUrlMissing

  return (
    <div className="relative overflow-hidden rounded-2xl bg-bg-card p-5 shadow-card">
      <div className="pointer-events-none absolute inset-0 rounded-2xl" style={{ border: '1px solid rgba(255,255,255,0.08)' }} />
      <DevLabel name="WorkflowPanel" float />

      {info && (
        <p className="mb-4 rounded-lg bg-signal-green/10 px-3 py-2 text-xs text-signal-green">{info}</p>
      )}
      {customUrlMissing && (
        <p className="mb-4 rounded-lg bg-signal-amber/10 px-3 py-2 text-xs text-signal-amber">{'\u5df2\u52fe\u9009\u300c\u81ea\u5b9a\u4e49\u641c\u7d22 URL\u300d\uff0c\u8bf7\u5148\u586b\u5165 URL \u518d\u8fd0\u884c'}</p>
      )}
      {error && (
        <p className="mb-4 rounded-lg bg-signal-red/10 px-3 py-2 text-xs text-signal-red">{error}</p>
      )}

      {/* W1 group */}
      <div className="mb-3 flex items-center gap-2">
        <GroupHeader wf="w1" title={'\u6295\u9012\u53c2\u6570'} inline />
        {renderSaveDefault('w1')}
      </div>
      <div className="space-y-2.5">
        <FieldNum label="score_threshold" value={scoreThreshold} onChange={setScoreThreshold} min={0} max={100} />
        <FieldNum label={'max_cards\uff080=\u7528\u9ed8\u8ba4\uff09'} value={applyLimit} onChange={setApplyLimit} min={0} max={100} />
        <FieldToggle label="dry_run" checked={dryRun} onChange={setDryRun} />
        <FieldToggle label={'\u81ea\u5b9a\u4e49\u641c\u7d22 URL'} checked={customUrlEnabled} onChange={setCustomUrlEnabled} />
        {customUrlEnabled && (
          <div className="space-y-2 pl-1">
            <input
              type="text"
              value={customUrl}
              onChange={e => setCustomUrl(e.target.value)}
              placeholder={'https://www.zhipin.com/web/geek/jobs?...'}
              className="w-full rounded-lg bg-bg-card2 px-3 py-1.5 font-mono text-xs text-text-1 focus:outline-none focus:ring-1 focus:ring-signal-blue"
              style={{ border: '1px solid rgba(255,255,255,0.08)' }}
            />
            {urlHistory.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {urlHistory.map((u, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => setCustomUrl(u)}
                    className="max-w-xs truncate rounded-full bg-bg-card2 px-2 py-0.5 font-mono text-xs text-text-3 transition hover:bg-bg-hover hover:text-text-1"
                    title={u}
                  >
                    {u.length > 45 ? u.slice(0, 42) + '\u2026' : u}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="my-4 h-px" style={{ background: 'rgba(255,255,255,0.08)' }} />

      {/* W2 group */}
      <div className="flex items-center gap-2">
        <GroupHeader wf="w2" title={'\u68c0\u67e5\u53c2\u6570'} inline />
        {checkInterval > 0 && (
          <span className="rounded-full bg-signal-blue/15 px-2 py-0.5 text-xs text-signal-bright">
            {'\u6bcf '}{checkInterval}{' \u5206\u81ea\u52a8\u626b\u63cf'}
          </span>
        )}
        {renderSaveDefault('w2')}
      </div>
      <div className="mt-3 space-y-2.5">
        <FieldNum label="max_conversations" value={maxConversations} onChange={setMaxConversations} min={1} max={200} />
        <FieldNum label="no_response_days" value={days} onChange={setDays} min={1} max={90} />
        <FieldNum label={'auto_interval\uff08\u5206\uff0c0=\u5173\uff09'} value={checkInterval} onChange={setCheckInterval} min={0} max={240} />
      </div>

      <div className="my-4 h-px" style={{ background: 'rgba(255,255,255,0.08)' }} />

      {/* Runtime */}
      <div className="flex flex-wrap gap-x-6 gap-y-2.5">
        <FieldToggle label={'headless'} checked={headless} onChange={setHeadless} compact />
        <FieldToggle label={'debug'} checked={debug} onChange={setDebug} compact />
      </div>

      {/* Actions */}
      <div className="mt-5 flex flex-wrap items-center gap-2.5">
        <button
          type="button"
          onClick={() => void handleApply()}
          disabled={disabled}
          className="inline-flex items-center gap-2 rounded-[10px] border border-border-subtle bg-bg-card2 px-4 py-2 text-sm text-text-1 transition hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-50"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-signal-blue" style={{ boxShadow: '0 0 8px #0a84ff' }} />
          {pending === 'apply' ? '\u6295\u9012\u4e2d\u2026' : '\u5f00\u59cb\u6295\u9012'}
        </button>
        <button
          type="button"
          onClick={() => void handleCheck()}
          disabled={disabled}
          className="inline-flex items-center gap-2 rounded-[10px] border border-border-subtle bg-bg-card2 px-4 py-2 text-sm text-text-1 transition hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-50"
        >
          <span className="h-1.5 w-1.5 rounded-full bg-signal-purple" style={{ boxShadow: '0 0 8px #bf5af2' }} />
          {pending === 'check' ? '\u626b\u63cf\u4e2d\u2026' : '\u626b\u63cf\u56de\u590d'}
        </button>
        <button
          type="button"
          onClick={() => void handleReply()}
          disabled={disabled}
          className="inline-flex items-center gap-2 rounded-[10px] border border-border-subtle bg-bg-card2 px-4 py-2 text-sm text-text-1 transition hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-50"
          title={'\u53d1\u9001\u6240\u6709\u5df2\u6279\u51c6\u7684 HR \u56de\u590d\uff08\u641c\u7d22\u5b9a\u4f4d + \u6295\u9012\u9a8c\u8bc1\uff09'}
        >
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: '#30d6c0', boxShadow: '0 0 8px #30d6c0' }} />
          {pending === 'reply' ? '\u53d1\u9001\u4e2d\u2026' : '\u53d1\u9001\u5df2\u6279\u51c6\u56de\u590d'}
        </button>
        <button
          type="button"
          onClick={() => void handleAll()}
          disabled={disabled}
          className="rounded-[10px] px-4 py-2 text-sm font-semibold text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
          style={{ background: 'linear-gradient(135deg,#0a84ff,#40c8e0)', boxShadow: '0 4px 18px rgba(10,132,255,0.3)' }}
        >
          {pending === 'all' ? '\u6267\u884c\u4e2d\u2026' : '\u26a1 W1+W2'}
        </button>
        <button
          type="button"
          onClick={() => void handleStop()}
          disabled={stopping || workflowRunning === null}
          className="rounded-[10px] px-4 py-2 text-sm text-signal-red transition disabled:cursor-not-allowed disabled:opacity-40"
          style={{ background: 'rgba(255,69,58,0.08)', border: '1px solid rgba(255,69,58,0.28)' }}
        >
          {stopping ? '\u4e2d\u6b62\u4e2d\u2026' : '\u25a0 \u4e2d\u6b62'}
        </button>
        <button
          type="button"
          onClick={handleClearClick}
          disabled={clearing || workflowRunning !== null}
          className={`rounded-[10px] px-4 py-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-40 ${
            clearConfirm
              ? 'bg-signal-amber/20 text-signal-amber hover:bg-signal-amber/30'
              : 'bg-transparent text-text-3 hover:bg-bg-card2 hover:text-text-1'
          }`}
          title={'\u5220\u9664\u6240\u6709\u975e\u5df2\u6295\u9012\u72b6\u6001\u7684\u8bb0\u5f55\uff08DISCOVERED / SCANNED / SCORED / ERROR\uff09'}
        >
          {clearing ? '\u6e05\u9664\u4e2d\u2026' : clearConfirm ? '\u786e\u8ba4\u6e05\u9664\uff1f' : '\u6e05\u9664\u7f13\u5b58'}
        </button>
      </div>
    </div>
  )
}

function GroupHeader({ wf, title, inline }: { wf: 'w1' | 'w2'; title: string; inline?: boolean }) {
  const cls = wf === 'w1' ? 'bg-signal-blue/18 text-signal-bright' : 'bg-signal-purple/18 text-signal-purple'
  return (
    <div className={inline ? 'flex items-center gap-2.5' : 'mb-3 flex items-center gap-2.5'}>
      <span className={`rounded font-mono text-[12.5px] font-bold px-2 py-0.5 ${cls}`}>{wf.toUpperCase()}</span>
      <span className="text-sm text-text-2">{title}</span>
    </div>
  )
}

function FieldNum({
  label,
  value,
  onChange,
  min,
  max,
}: {
  label: string
  value: number
  onChange: (v: number) => void
  min: number
  max: number
}) {
  return (
    <div className="flex items-center gap-3">
      <span className="flex-1 font-mono text-sm text-text-2">{label}</span>
      <input
        type="number"
        value={value}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-[86px] rounded-lg bg-bg-card2 px-2.5 py-1.5 text-right font-mono text-sm text-text-1 focus:outline-none focus:ring-1 focus:ring-signal-blue"
        style={{ border: '1px solid rgba(255,255,255,0.08)' }}
      />
    </div>
  )
}

function FieldToggle({
  label,
  checked,
  onChange,
  compact,
}: {
  label: string
  checked: boolean
  onChange: (v: boolean) => void
  compact?: boolean
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!checked)}
      className={`flex items-center gap-3 ${compact ? '' : 'w-full'}`}
    >
      <span className="flex-1 text-left font-mono text-sm text-text-2">{label}</span>
      <span
        className="relative h-[22px] w-[38px] shrink-0 rounded-full transition-colors"
        style={{ background: checked ? '#0a84ff' : 'rgba(255,255,255,0.13)' }}
      >
        <span
          className="absolute top-0.5 left-0.5 h-[18px] w-[18px] rounded-full bg-white transition-transform"
          style={{ transform: checked ? 'translateX(16px)' : 'translateX(0)' }}
        />
      </span>
    </button>
  )
}
