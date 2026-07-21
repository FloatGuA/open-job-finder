import { useCallback, useEffect, useRef, useState } from 'react'
import { API } from '@/api'
import type { ScheduleConfig, ScheduleLogEntry, RegressionReport, InvariantReport, SmokeReport } from '@/api'
import DevLabel from '@/components/dev/DevLabel'
import { SelfCheckSection } from './SelfCheck'

function formatNextRun(iso: string | null | undefined): string {
  if (!iso) return '\u6682\u65e0\u8ba1\u5212'
  const d = new Date(iso)
  const diffSec = Math.round((d.getTime() - Date.now()) / 1000)
  if (diffSec <= 0) return '\u5373\u5c06\u89e6\u53d1'

  const localTime = d.toLocaleTimeString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })

  let relative: string
  if (diffSec < 3600) {
    const m = Math.floor(diffSec / 60)
    const s = diffSec % 60
    relative = s > 0 ? `${m}\u5206${s}\u79d2\u540e` : `${m}\u5206\u949f\u540e`
  } else {
    const h = Math.floor(diffSec / 3600)
    const m = Math.floor((diffSec % 3600) / 60)
    relative = m > 0 ? `${h}\u5c0f\u65f6${m}\u5206\u540e` : `${h}\u5c0f\u65f6\u540e`
  }

  return `${relative}\uff08${localTime}\uff09`
}

function formatLogTime(iso: string): string {
  return new Date(iso).toLocaleString('zh-CN', {
    timeZone: 'Asia/Shanghai',
    hour12: false,
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

interface WfScheduleState {
  enabled: boolean
  times: string[]
  interval_enabled: boolean
  interval_minutes: number
  params: Record<string, unknown>
}

type ParamSpec =
  | { key: string; label: string; type: 'number'; min: number; max: number; hint?: string }
  | { key: string; label: string; type: 'boolean'; hint?: string }

function WorkflowScheduleSection({
  wf,
  title,
  state,
  onChange,
  nextRun,
  nextIntervalRun,
  onApplyCron,
  onApplyInterval,
  savingCron,
  savingInterval,
  paramSpecs,
  onSaveParamDefault,
}: {
  wf: 'w1' | 'w2'
  title: string
  state: WfScheduleState
  onChange: (u: Partial<WfScheduleState>) => void
  nextRun: string | null | undefined
  nextIntervalRun: string | null | undefined
  onApplyCron: (newEnabled: boolean, runNow: boolean) => void
  onApplyInterval: (newEnabled: boolean, runNow: boolean) => void
  savingCron: boolean
  savingInterval: boolean
  paramSpecs: ParamSpec[]
  onSaveParamDefault: (key: string, value: unknown) => void
}) {
  const [runNowCron, setRunNowCron] = useState(false)
  const [runNowInterval, setRunNowInterval] = useState(false)
  const [newTime, setNewTime] = useState('')
  const [showParams, setShowParams] = useState(false)
  const [savedKey, setSavedKey] = useState<string | null>(null)

  const updateParam = (key: string, value: unknown) =>
    onChange({ params: { ...state.params, [key]: value } })

  const saveDefault = (key: string, value: unknown) => {
    onSaveParamDefault(key, value)
    setSavedKey(key)
    setTimeout(() => setSavedKey((prev) => (prev === key ? null : prev)), 1500)
  }

  const addTime = () => {
    if (!newTime) return
    if (!state.times.includes(newTime))
      onChange({ times: [...state.times, newTime].sort() })
    setNewTime('')
  }

  return (
    <div
      className="rounded-xl p-4"
      style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.07)' }}
    >
      <div className="mb-3 flex items-center gap-2">
        <span className={`rounded font-mono text-[12px] font-bold px-1.5 py-0.5 ${wf === 'w1' ? 'bg-signal-blue/18 text-signal-bright' : 'bg-signal-purple/18 text-signal-purple'}`}>
          {wf.toUpperCase()}
        </span>
        <span className="text-sm font-semibold text-text-1">{title}</span>
        <DevLabel name="WorkflowScheduleSection" />
      </div>

      {/* Cron section */}
      <div
        className="mb-3 rounded-lg p-3"
        style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}
      >
        <div className="mb-2 flex items-center justify-between">
          <p className="text-xs text-text-3">{'\u5b9a\u65f6\u89e6\u53d1'}</p>
          <div className="flex items-center gap-3">
            <label className="flex cursor-pointer items-center gap-1.5">
              <input
                type="checkbox"
                checked={runNowCron}
                onChange={(e) => setRunNowCron(e.target.checked)}
                className="rounded"
              />
              <span className="text-xs text-text-2">{'\u7acb\u523b\u542f\u52a8\u4e00\u6b21'}</span>
            </label>
            <span
              className="text-xs"
              style={{ color: state.enabled ? '#2997ff' : 'rgba(255,255,255,0.3)' }}
            >
              {'\u5b9a\u65f6\u89e6\u53d1\uff1a'}{state.enabled ? '\u5df2\u5f00\u542f' : '\u5df2\u5173\u95ed'}
            </span>
            <button
              type="button"
              disabled={savingCron}
              onClick={() => { const v = !state.enabled; onChange({ enabled: v }); onApplyCron(v, runNowCron) }}
              className="flex h-5 w-9 items-center rounded-full transition-colors disabled:opacity-50"
              style={{ background: state.enabled ? '#0a84ff' : 'rgba(255,255,255,0.15)' }}
              aria-label={state.enabled ? '\u5173\u95ed\u5b9a\u65f6\u89e6\u53d1' : '\u5f00\u542f\u5b9a\u65f6\u89e6\u53d1'}
            >
              <span
                className="ml-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform"
                style={{ transform: state.enabled ? 'translateX(16px)' : 'translateX(0)' }}
              />
            </button>
          </div>
        </div>
        <div className="mb-1 flex items-baseline gap-1">
          <span className="text-xs" style={{ color: 'rgba(255,255,255,0.25)' }}>{'24\u5c0f\u65f6\u5236 HH:MM'}</span>
        </div>
        <div className="mb-1.5 flex flex-wrap gap-1.5">
          {state.times.map((t) => (
            <span
              key={t}
              className="flex items-center gap-1 rounded-lg px-2 py-0.5 text-xs"
              style={{ background: 'rgba(10,132,255,0.18)', color: '#2997ff' }}
            >
              {t}
              <button
                type="button"
                onClick={() => onChange({ times: state.times.filter((x) => x !== t) })}
                className="leading-none text-text-3 hover:text-red-400"
              >
                &times;
              </button>
            </span>
          ))}
        </div>
        <div className="flex items-center gap-1.5">
          <input
            type="time"
            value={newTime}
            onChange={(e) => setNewTime(e.target.value)}
            className="rounded-lg px-2 py-1 text-xs text-white"
            style={{
              background: 'rgba(255,255,255,0.08)',
              border: '1px solid rgba(255,255,255,0.12)',
              width: '100px',
            }}
          />
          <button
            type="button"
            onClick={addTime}
            className="rounded-lg px-2 py-1 text-xs text-text-2 transition hover:text-white"
            style={{ background: 'rgba(255,255,255,0.08)' }}
          >
            {`+ \u6dfb\u52a0`}
          </button>
        </div>
        {nextRun && (
          <div className="mt-1.5 flex items-center gap-2">
            <span className="text-xs text-text-3">{'\u5b9a\u65f6\u4e0b\u6b21\uff1a'}</span>
            <span className="text-xs font-medium" style={{ color: '#30d158' }}>{formatNextRun(nextRun)}</span>
          </div>
        )}
      </div>

      {/* Interval section */}
      <div
        className="mb-3 rounded-lg p-3"
        style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}
      >
        <div className="mb-2 flex items-center justify-between">
          <p className="text-xs text-text-3">{'\u95f4\u9694\u89e6\u53d1'}</p>
          <div className="flex items-center gap-3">
            <label className="flex cursor-pointer items-center gap-1.5">
              <input
                type="checkbox"
                checked={runNowInterval}
                onChange={(e) => setRunNowInterval(e.target.checked)}
                className="rounded"
              />
              <span className="text-xs text-text-2">{'\u7acb\u523b\u542f\u52a8\u4e00\u6b21'}</span>
            </label>
            <span
              className="text-xs"
              style={{ color: state.interval_enabled ? '#2997ff' : 'rgba(255,255,255,0.3)' }}
            >
              {'\u95f4\u9694\u89e6\u53d1\uff1a'}{state.interval_enabled ? '\u5df2\u5f00\u542f' : '\u5df2\u5173\u95ed'}
            </span>
            <button
              type="button"
              disabled={savingInterval}
              onClick={() => { const v = !state.interval_enabled; onChange({ interval_enabled: v }); onApplyInterval(v, runNowInterval) }}
              className="flex h-5 w-9 items-center rounded-full transition-colors disabled:opacity-50"
              style={{ background: state.interval_enabled ? '#0a84ff' : 'rgba(255,255,255,0.15)' }}
              aria-label={state.interval_enabled ? '\u5173\u95ed\u95f4\u9694\u89e6\u53d1' : '\u5f00\u542f\u95f4\u9694\u89e6\u53d1'}
            >
              <span
                className="ml-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform"
                style={{ transform: state.interval_enabled ? 'translateX(16px)' : 'translateX(0)' }}
              />
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={0}
            max={10080}
            value={state.interval_minutes}
            onChange={(e) =>
              onChange({ interval_minutes: Math.max(0, parseInt(e.target.value, 10) || 0) })
            }
            className="w-16 rounded-lg px-2 py-1 text-xs text-white"
            style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)' }}
          />
          <span className="text-xs text-text-3">{'\u5206\u949f\u4e00\u6b21'}</span>
        </div>
        {state.interval_enabled && (
          <div className="mt-1.5 flex items-center gap-2">
            <span className="text-xs text-text-3">{'\u4e0b\u6b21\u95f4\u9694\uff1a'}</span>
            <span
              className="text-xs font-medium"
              style={{ color: nextIntervalRun ? '#30d158' : 'rgba(255,255,255,0.35)' }}
            >
              {formatNextRun(nextIntervalRun)}
            </span>
          </div>
        )}
      </div>

      {/* Params section */}
      <div>
        <button
          type="button"
          onClick={() => setShowParams((v) => !v)}
          className="flex items-center gap-1.5 text-xs text-text-3 transition hover:text-text-2"
        >
          <span
            className="inline-block transition-transform"
            style={{ transform: showParams ? 'rotate(90deg)' : 'rotate(0deg)' }}
          >
            &#x25B6;
          </span>
          <span>{'\u53c2\u6570\u914d\u7f6e'}</span>
        </button>
        {showParams && (
          <div
            className="mt-2 space-y-2 rounded-lg p-3"
            style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}
          >
            {paramSpecs.map((spec) => (
              <div key={spec.key} className="flex items-center gap-3">
                <div className="min-w-0 flex-1">
                  <span className="text-xs text-text-2">{spec.label}</span>
                  {spec.hint && (
                    <span className="ml-1.5 text-xs text-text-3">{spec.hint}</span>
                  )}
                </div>
                {spec.type === 'boolean' ? (
                  <input
                    type="checkbox"
                    checked={!!state.params[spec.key]}
                    onChange={(e) => updateParam(spec.key, e.target.checked)}
                    className="rounded"
                    style={{ accentColor: '#0a84ff' }}
                  />
                ) : (
                  <input
                    type="number"
                    min={spec.min}
                    max={spec.max}
                    value={(state.params[spec.key] as number) ?? 0}
                    onChange={(e) =>
                      updateParam(spec.key, Math.max(spec.min, parseInt(e.target.value, 10) || 0))
                    }
                    className="w-16 rounded-lg px-2 py-1 text-xs text-white"
                    style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.12)' }}
                  />
                )}
                <button
                  type="button"
                  onClick={() => saveDefault(spec.key, state.params[spec.key])}
                  className="shrink-0 rounded px-1.5 py-0.5 text-xs transition-colors"
                  style={{
                    color: savedKey === spec.key ? '#30d158' : 'rgba(255,255,255,0.3)',
                    background: 'rgba(255,255,255,0.06)',
                  }}
                  title={'\u8bbe\u4e3a\u9ed8\u8ba4\u503c'}
                >
                  {savedKey === spec.key ? '\u2713' : '\u9ed8\u8ba4'}
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

    </div>
  )
}

const APPLY_PARAMS: ParamSpec[] = [
  { key: 'score_threshold',  label: '\u8bc4\u5206\u9608\u503c',     type: 'number',  min: 0,  max: 100, hint: '0 = \u4e0d\u8fc7\u6ee4\uff0c\u5168\u6295' },
  { key: 'max_cards',        label: '\u6700\u591a\u5904\u7406\u804c\u4f4d', type: 'number',  min: 0,  max: 50,  hint: '0 = \u7528\u9ed8\u8ba4\u503c' },
  { key: 'dry_run',          label: '\u6a21\u62df\u8fd0\u884c',     type: 'boolean',                    hint: '\u4e0d\u5b9e\u9645\u6295\u9012' },
  { key: 'headless',         label: '\u65e0\u5934\u6a21\u5f0f',     type: 'boolean',                    hint: '\u6d4f\u89c8\u5668\u540e\u53f0\u8fd0\u884c' },
]

const CHECK_PARAMS: ParamSpec[] = [
  { key: 'max_conversations', label: '\u6700\u591a\u626b\u63cf\u4f1a\u8bdd', type: 'number', min: 1, max: 10000 },
  { key: 'no_response_days',  label: '\u65e0\u56de\u5e94\u5929\u6570',   type: 'number', min: 1, max: 90,  hint: '\u8d85\u8fc7\u5219\u6807\u8bb0/\u62d2\u7edd' },
  { key: 'stale_conv_days',   label: '\u9648\u65e7\u5173\u95ed\u5929\u6570', type: 'number', min: 1, max: 180, hint: '\u8d85\u8fc7\u5219\u81ea\u52a8\u5173\u95ed' },
  { key: 'dry_run',           label: '\u6a21\u62df\u8fd0\u884c',     type: 'boolean',             hint: '\u4e0d\u5b9e\u9645\u53d1\u9001' },
  { key: 'headless',          label: '\u65e0\u5934\u6a21\u5f0f',     type: 'boolean',             hint: '\u6d4f\u89c8\u5668\u540e\u53f0\u8fd0\u884c' },
]

function ScheduleCard() {
  const [apply, setApply] = useState<WfScheduleState>({
    enabled: false,
    times: [],
    interval_enabled: false,
    interval_minutes: 0,
    params: {
      score_threshold: 0,
      max_cards: 15,
      dry_run: false,
      headless: true,
    },
  })
  const [check, setCheck] = useState<WfScheduleState>({
    enabled: false,
    times: [],
    interval_enabled: false,
    interval_minutes: 0,
    params: { max_conversations: 200, no_response_days: 14, stale_conv_days: 30, dry_run: false, headless: true },
  })
  const [nextRuns, setNextRuns] = useState<Record<string, string | null>>({})
  const [nextIntervalRuns, setNextIntervalRuns] = useState<Record<string, string | null>>({})
  const [schedulerRunning, setSchedulerRunning] = useState(false)
  const [savingApplyCron, setSavingApplyCron] = useState(false)
  const [savingApplyInterval, setSavingApplyInterval] = useState(false)
  const [savingCheckCron, setSavingCheckCron] = useState(false)
  const [savingCheckInterval, setSavingCheckInterval] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      const cfg = await (API.getSchedule() as Promise<ScheduleConfig>)
      setApply({
        enabled: cfg.apply.enabled,
        times: cfg.apply.times,
        interval_enabled: cfg.apply.interval_enabled ?? false,
        interval_minutes: cfg.apply.interval_minutes,
        params: cfg.apply.params,
      })
      setCheck({
        enabled: cfg.check.enabled,
        times: cfg.check.times,
        interval_enabled: cfg.check.interval_enabled ?? false,
        interval_minutes: cfg.check.interval_minutes,
        params: cfg.check.params,
      })
      setNextRuns(cfg._next_runs ?? {})
      setNextIntervalRuns(cfg._next_interval_runs ?? {})
      setSchedulerRunning(cfg._scheduler_running ?? false)
    } catch {
      // non-fatal
    }
  }, [])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const id = window.setInterval(() => void load(), 30_000)
    return () => window.clearInterval(id)
  }, [load])

  const handleSaveParamDefault = async (
    wf: 'apply' | 'check',
    key: string,
    value: unknown,
  ) => {
    try {
      await API.updateSchedule({ [wf]: { params: { [key]: value } } })
    } catch (e) {
      setSaveError((e as Error).message)
    }
  }

  const handleApplyCron = async (
    wf: 'apply' | 'check',
    state: WfScheduleState,
    setSaving: (v: boolean) => void,
    newEnabled: boolean,
    runNow: boolean,
  ) => {
    setSaveError(null)
    setSaving(true)
    try {
      await API.updateSchedule({ [wf]: { enabled: newEnabled, times: state.times } })
      if (runNow && newEnabled) {
        if (wf === 'apply') await API.triggerApplyWorkflow({ ...state.params })
        else await API.triggerCheckWorkflow({ ...state.params })
      }
      await load()
    } catch (e) {
      setSaveError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const handleApplyInterval = async (
    wf: 'apply' | 'check',
    state: WfScheduleState,
    setSaving: (v: boolean) => void,
    newEnabled: boolean,
    runNow: boolean,
  ) => {
    setSaveError(null)
    setSaving(true)
    try {
      await API.updateSchedule({ [wf]: { interval_enabled: newEnabled, interval_minutes: state.interval_minutes } })
      if (runNow && newEnabled) {
        if (wf === 'apply') await API.triggerApplyWorkflow({ ...state.params })
        else await API.triggerCheckWorkflow({ ...state.params })
      }
      await load()
    } catch (e) {
      setSaveError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rounded-2xl bg-bg-card p-5 shadow-card">
      <div className="mb-4 flex items-center justify-between">
        <span className="flex items-center gap-2">
          <p className="text-xs text-text-3" style={{ letterSpacing: '-0.12px' }}>
            {'\u81ea\u52a8\u8c03\u5ea6'}
          </p>
          <DevLabel name="ScheduleCard" />
        </span>
        <span
          className="flex items-center gap-1.5 text-xs"
          style={{ color: schedulerRunning ? '#30d158' : '#84848c' }}
        >
          <span
            className="inline-block h-1.5 w-1.5 rounded-full"
            style={{ background: schedulerRunning ? '#30d158' : '#84848c' }}
          />
          {schedulerRunning ? '\u8c03\u5ea6\u5668\u8fd0\u884c\u4e2d' : '\u672a\u542f\u52a8'}
        </span>
      </div>
      {saveError && (
        <p className="mb-3 rounded-lg bg-signal-red/10 px-3 py-2 text-xs text-signal-red">{saveError}</p>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        <WorkflowScheduleSection
          wf="w1"
          title={'\u6295\u9012'}
          state={apply}
          onChange={(u) => setApply((p) => ({ ...p, ...u }))}
          nextRun={nextRuns['apply']}
          nextIntervalRun={nextIntervalRuns['apply']}
          onApplyCron={(v, runNow) => void handleApplyCron('apply', apply, setSavingApplyCron, v, runNow)}
          onApplyInterval={(v, runNow) => void handleApplyInterval('apply', apply, setSavingApplyInterval, v, runNow)}
          savingCron={savingApplyCron}
          savingInterval={savingApplyInterval}
          paramSpecs={APPLY_PARAMS}
          onSaveParamDefault={(key, value) => void handleSaveParamDefault('apply', key, value)}
        />
        <WorkflowScheduleSection
          wf="w2"
          title={'\u68c0\u67e5'}
          state={check}
          onChange={(u) => setCheck((p) => ({ ...p, ...u }))}
          nextRun={nextRuns['check']}
          nextIntervalRun={nextIntervalRuns['check']}
          onApplyCron={(v, runNow) => void handleApplyCron('check', check, setSavingCheckCron, v, runNow)}
          onApplyInterval={(v, runNow) => void handleApplyInterval('check', check, setSavingCheckInterval, v, runNow)}
          savingCron={savingCheckCron}
          savingInterval={savingCheckInterval}
          paramSpecs={CHECK_PARAMS}
          onSaveParamDefault={(key, value) => void handleSaveParamDefault('check', key, value)}
        />
      </div>
    </div>
  )
}

function ScheduleLogCard() {
  const [log, setLog] = useState<ScheduleLogEntry[]>([])
  const [offline, setOffline] = useState(false)

  const load = useCallback(async () => {
    try {
      setLog(await API.getScheduleLog(50))
      setOffline(false)
    } catch {
      setOffline(true)
    }
  }, [])

  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const id = window.setInterval(() => void load(), 30_000)
    return () => window.clearInterval(id)
  }, [load])

  return (
    <div className="rounded-2xl bg-bg-card p-5 shadow-card">
      <p className="mb-4 flex items-center gap-2 text-xs text-text-3" style={{ letterSpacing: '-0.12px' }}>
        {'\u8c03\u5ea6\u5386\u53f2'}
        <DevLabel name="ScheduleLogCard" />
      </p>
      {offline ? (
        <p className="text-xs" style={{ color: '#ff453a' }}>
          {'\u670d\u52a1\u5668\u672a\u54cd\u5e94\uff0c\u65e5\u5fd7\u65e0\u6cd5\u52a0\u8f7d\u2014\u2014\u8bf7\u91cd\u542f\u540e\u7aef'}
        </p>
      ) : log.length === 0 ? (
        <p className="text-xs" style={{ color: 'rgba(255,255,255,0.2)' }}>
          {'\u6682\u65e0\u8bb0\u5f55\uff0c\u624b\u52a8\u6216\u5b9a\u65f6\u89e6\u53d1\u540e\u5c06\u5728\u6b64\u663e\u793a'}
        </p>
      ) : (
        <div className="space-y-1.5">
          {log.map((entry, i) => {
            const icon =
              entry.result === 'success' ? '\u2713' : entry.result === 'skipped' ? '\u25b7' : '\u2715'
            const resultColor =
              entry.result === 'success' ? '#30d158' : entry.result === 'skipped' ? '#84848c' : '#ff453a'
            const wfLabel = entry.workflow === 'apply' ? 'W1' : 'W2'
            return (
              <div key={i} className="flex items-start gap-2 text-xs leading-relaxed">
                <span style={{ color: resultColor, minWidth: '12px' }}>{icon}</span>
                <span className="shrink-0 text-text-3">{formatLogTime(entry.triggered_at)}</span>
                <span
                  className="shrink-0 rounded px-1"
                  style={{ background: 'rgba(255,255,255,0.08)', color: 'rgba(255,255,255,0.5)' }}
                >
                  {wfLabel}
                </span>
                <span
                  className="shrink-0 rounded px-1"
                  style={{
                    background: entry.trigger_type === 'manual' ? 'rgba(251,191,36,0.15)' : 'rgba(96,165,250,0.15)',
                    color: entry.trigger_type === 'manual' ? '#ff9f0a' : '#2997ff',
                  }}
                >
                  {entry.trigger_type === 'manual' ? '\u624b\u52a8' : '\u5b9a\u65f6'}
                </span>
                <span className="truncate text-text-2">
                  {entry.result === 'skipped'
                    ? `\u8df3\u8fc7\uff1a${entry.skipped_reason ?? ''}`
                    : entry.result === 'error'
                      ? `\u9519\u8bef\uff1a${entry.summary ?? ''}`
                      : `${entry.summary ?? ''} ${entry.duration_seconds ? `(${entry.duration_seconds}s)` : ''}`}
                </span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

type AutoTab = 'schedule' | 'regression'
const AUTO_TABS: Array<{ key: AutoTab; label: string }> = [
  { key: 'schedule', label: '\u5b9a\u65f6\u8c03\u5ea6' },
  { key: 'regression', label: '\u56de\u5f52\u6d4b\u8bd5' },
]

function PytestCard() {
  const [running, setRunning] = useState(false)
  const [report, setReport] = useState<RegressionReport | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const run = async () => {
    setRunning(true)
    setErr(null)
    try {
      setReport(await API.runRegressionPytest())
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setRunning(false)
    }
  }

  const failedFiles = report ? report.files.filter((f) => f.failed > 0) : []

  return (
    <div className="rounded-2xl bg-bg-card p-5 shadow-card">
      <div className="mb-4 flex items-center justify-between">
        <span className="flex items-center gap-2">
          <p className="text-xs text-text-3" style={{ letterSpacing: '-0.12px' }}>{'\u903b\u8f91\u56de\u5f52\uff08pytest\uff09'}</p>
          <DevLabel name="PytestCard" />
        </span>
        <button
          type="button"
          onClick={() => void run()}
          disabled={running}
          className="rounded-lg px-3 py-1.5 text-xs font-medium transition disabled:opacity-50"
          style={{ background: 'rgba(10,132,255,0.16)', color: '#2997ff', boxShadow: 'inset 0 0 0 1px rgba(10,132,255,0.3)' }}
        >
          {running ? '\u8fd0\u884c\u4e2d\u2026' : report ? '\u91cd\u65b0\u8fd0\u884c' : '\u8fd0\u884c\u5168\u90e8'}
        </button>
      </div>

      {err && (
        <p className="mb-3 rounded-lg bg-signal-red/10 px-3 py-2 text-xs text-signal-red">{err}</p>
      )}

      {running && (
        <p className="text-xs text-text-3">{'\u6b63\u5728\u8fd0\u884c\u5168\u90e8\u56de\u5f52\u6d4b\u8bd5\uff0c\u7ea6\u9700 10 \u79d2\u2026\u2026'}</p>
      )}

      {!running && !report && !err && (
        <p className="text-xs" style={{ color: 'rgba(255,255,255,0.3)' }}>
          {'\u70b9\u51fb\u300c\u8fd0\u884c\u5168\u90e8\u300d\u6267\u884c\u5168\u90e8\u56de\u5f52\u6d4b\u8bd5\uff08tool / pipeline / db / llm \u903b\u8f91\u5c42\uff0c\u7ea6 455 \u9879\uff09\u3002'}
        </p>
      )}

      {report && (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            <span className="flex items-center gap-1.5 font-semibold" style={{ color: report.ok ? '#30d158' : '#ff453a' }}>
              <span>{report.ok ? '\u2713' : '\u2715'}</span>
              <span>{report.passed}{' / '}{report.total}{' '}{'\u901a\u8fc7'}</span>
            </span>
            {report.failed > 0 && <span className="text-signal-red">{report.failed}{' '}{'\u5931\u8d25'}</span>}
            {report.skipped > 0 && <span className="text-text-3">{report.skipped}{' '}{'\u8df3\u8fc7'}</span>}
            <span className="text-text-3">{report.duration_s}{'s'}</span>
          </div>

          {report.collect_error && (
            <pre className="overflow-x-auto rounded-lg bg-signal-red/10 p-2 text-[11px] text-signal-red">{report.collect_error}</pre>
          )}

          {failedFiles.length > 0 && (
            <div className="space-y-2">
              {failedFiles.map((f) => (
                <div key={f.name} className="rounded-lg p-2" style={{ background: 'rgba(255,69,58,0.08)', border: '1px solid rgba(255,69,58,0.2)' }}>
                  <p className="mb-1 text-xs font-medium text-signal-red">{f.name}{' \u00b7 '}{f.failed}{' '}{'\u5931\u8d25'}</p>
                  {f.failures.map((fl, i) => (
                    <div key={i} className="ml-2 text-xs leading-relaxed">
                      <span className="text-text-2">{fl.name}</span>
                      {fl.message && <span className="text-text-3">{' \u2014 '}{fl.message}</span>}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          )}

          {report.ok && <p className="text-xs text-text-3">{'\u5168\u90e8\u901a\u8fc7\u3002'}</p>}
        </div>
      )}
    </div>
  )
}

function InvariantCard() {
  const [running, setRunning] = useState(false)
  const [report, setReport] = useState<InvariantReport | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const run = async () => {
    setRunning(true)
    setErr(null)
    try {
      setReport(await API.runRegressionInvariants())
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setRunning(false)
    }
  }

  return (
    <div className="rounded-2xl bg-bg-card p-5 shadow-card">
      <div className="mb-4 flex items-center justify-between">
        <span className="flex items-center gap-2">
          <p className="text-xs text-text-3" style={{ letterSpacing: '-0.12px' }}>{'\u6570\u636e\u4e0d\u53d8\u91cf'}</p>
          <DevLabel name="InvariantCard" />
        </span>
        <button
          type="button"
          onClick={() => void run()}
          disabled={running}
          className="rounded-lg px-3 py-1.5 text-xs font-medium transition disabled:opacity-50"
          style={{ background: 'rgba(10,132,255,0.16)', color: '#2997ff', boxShadow: 'inset 0 0 0 1px rgba(10,132,255,0.3)' }}
        >
          {running ? '\u68c0\u67e5\u4e2d\u2026' : report ? '\u91cd\u65b0\u68c0\u67e5' : '\u8fd0\u884c\u68c0\u67e5'}
        </button>
      </div>

      {err && (
        <p className="mb-3 rounded-lg bg-signal-red/10 px-3 py-2 text-xs text-signal-red">{err}</p>
      )}

      {!running && !report && !err && (
        <p className="text-xs" style={{ color: 'rgba(255,255,255,0.3)' }}>
          {'\u68c0\u67e5\u6570\u636e\u5c42\u4e0d\u53d8\u91cf\uff08\u72b6\u6001/stage/\u56de\u590d\u72b6\u6001\u5408\u6cd5\u6027\u3001\u56de\u590d\u6b63\u6587\u4e00\u81f4\u6027\uff09\u3002\u53ea\u8bfb\uff0c\u4e0d\u6539\u6570\u636e\u3002'}
        </p>
      )}

      {report && (
        <div className="space-y-1.5">
          <div className="mb-1 text-xs text-text-3">{'\u5e94\u8058 '}{report.total_apps}{' \u00b7 \u4f1a\u8bdd '}{report.total_convs}</div>
          {report.checks.map((c) => (
            <div key={c.name} className="flex items-start gap-2 text-xs leading-relaxed">
              <span style={{ color: c.ok ? '#30d158' : '#ff453a' }}>{c.ok ? '\u2713' : '\u2715'}</span>
              <span className="text-text-2">{c.name}</span>
              {!c.ok && <span className="text-signal-red">{'\u00b7 '}{c.detail}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function SmokeCard() {
  const [report, setReport] = useState<SmokeReport | null>(null)
  const [running, setRunning] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  // 5 rather than 1: a single card often has nothing applicable left, so the apply
  // path reports "not covered" and the gate never closes. Must match the server's
  // live-mode default (server.py) -- the frontend always sends an explicit value.
  const [w1Max, setW1Max] = useState(5)
  const [w2Max, setW2Max] = useState(5)
  // Workflow knobs mirroring the console's. score_threshold defaults BELOW the
  // stock 60 on purpose: at 60 a smoke often applies nothing, and a run that
  // applies nothing verifies nothing (covered=false), so the gate never closes.
  const [scoreThreshold, setScoreThreshold] = useState<number | ''>(40)
  const [noResponseDays, setNoResponseDays] = useState<number | ''>('')
  const [staleConvDays, setStaleConvDays] = useState<number | ''>('')
  const [confirmLive, setConfirmLive] = useState(false)
  const [showDiag, setShowDiag] = useState(false)
  const pollRef = useRef<number | null>(null)

  const fetchLast = async (): Promise<SmokeReport | null> => {
    try {
      return (await API.getRegressionSmokeLast()).report
    } catch {
      return null
    }
  }

  useEffect(() => {
    void fetchLast().then((r) => setReport(r))
    return () => {
      if (pollRef.current !== null) window.clearInterval(pollRef.current)
    }
  }, [])

  const run = async (mode: 'dry' | 'live') => {
    setErr(null)
    setConfirmLive(false)
    const before = report?.ran_at ?? ''
    setRunning(true)
    try {
      const knobs = {
        score_threshold: scoreThreshold === '' ? null : scoreThreshold,
        no_response_days: noResponseDays === '' ? null : noResponseDays,
        stale_conv_days: staleConvDays === '' ? null : staleConvDays,
      }
      await API.triggerRegressionSmoke(
        mode === 'live'
          ? { mode: 'live', w1_max: w1Max, w2_max: w2Max, ...knobs }
          : { mode: 'dry', w1_max: w1Max, w2_max: w2Max, ...knobs },
      )
    } catch (e) {
      setErr((e as Error).message)
      setRunning(false)
      return
    }
    let tries = 0
    pollRef.current = window.setInterval(() => {
      void (async () => {
        tries += 1
        const r = await fetchLast()
        if (r && r.ran_at !== before) {
          setReport(r)
          setRunning(false)
          if (pollRef.current !== null) window.clearInterval(pollRef.current)
        } else if (tries > 72) {
          setRunning(false)
          if (pollRef.current !== null) window.clearInterval(pollRef.current)
        }
      })()
    }, 5000)
  }

  return (
    <div className="rounded-2xl bg-bg-card p-5 shadow-card">
      <div className="mb-3 flex items-center justify-between">
        <span className="flex items-center gap-2">
          <p className="text-xs text-text-3" style={{ letterSpacing: '-0.12px' }}>{'\u771f\u673a\u7aef\u5230\u7aef\u5192\u70df'}</p>
          <DevLabel name="SmokeCard" />
        </span>
        <button
          type="button"
          onClick={() => void run('dry')}
          disabled={running}
          className="rounded-lg px-3 py-1.5 text-xs font-medium transition disabled:opacity-50"
          style={{ background: 'rgba(10,132,255,0.16)', color: '#2997ff', boxShadow: 'inset 0 0 0 1px rgba(10,132,255,0.3)' }}
        >
          {running ? '\u8fd0\u884c\u4e2d\u2026\uff08\u6570\u5206\u949f\uff09' : '\u8fd0\u884c dry-run'}
        </button>
      </div>

      <p className="mb-3 rounded-lg px-3 py-2 text-xs leading-relaxed" style={{ background: 'rgba(48,209,88,0.1)', color: '#30d158' }}>
        {'dry-run\uff1a\u53ea\u8bfb\u8def\u5f84\uff08\u4e0d\u6295\u9012/\u4e0d\u53d1\u9001\uff09\uff0c\u9a8c\u8bc1\u9009\u62e9\u5668/DOM/API \u672a\u65ad\u3002\u65e0\u5bb3\uff0c\u53ef\u968f\u610f\u8dd1\u3002'}
      </p>

      {/* Run knobs, shared by dry and live. These mirror the console's W1/W2
          parameters so a smoke can reproduce the conditions of a real run --
          without score_threshold the smoke silently used the stock 60 and could
          never cover the apply path. */}
      <div className="mb-3 rounded-lg p-3" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
        <p className="mb-2 text-xs font-medium text-text-2">{'\u8fd0\u884c\u53c2\u6570\uff08\u4e0e\u63a7\u5236\u53f0\u4e00\u81f4\uff09'}</p>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <label className="flex items-center gap-1.5 text-xs text-text-2">
            {'W1 \u6295\u9012'}
            <input
              type="number" min={1} max={10} value={w1Max}
              onChange={(ev) => setW1Max(Math.max(1, Number(ev.target.value) || 1))}
              className="w-14 rounded bg-bg-card px-2 py-1 text-xs text-text-1"
              style={{ border: '1px solid rgba(255,255,255,0.12)' }}
            />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-text-2">
            {'W2 \u4f1a\u8bdd'}
            <input
              type="number" min={1} max={50} value={w2Max}
              onChange={(ev) => setW2Max(Math.max(1, Number(ev.target.value) || 1))}
              className="w-14 rounded bg-bg-card px-2 py-1 text-xs text-text-1"
              style={{ border: '1px solid rgba(255,255,255,0.12)' }}
            />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-text-2">
            {'\u8bc4\u5206\u9608\u503c'}
            <input
              type="number" min={0} max={100} value={scoreThreshold}
              onChange={(ev) => setScoreThreshold(ev.target.value === '' ? '' : Number(ev.target.value))}
              className="w-14 rounded bg-bg-card px-2 py-1 text-xs text-text-1"
              style={{ border: '1px solid rgba(255,255,255,0.12)' }}
            />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-text-2">
            {'\u65e0\u54cd\u5e94\u5929\u6570'}
            <input
              type="number" min={1} max={365} value={noResponseDays} placeholder={'14'}
              onChange={(ev) => setNoResponseDays(ev.target.value === '' ? '' : Number(ev.target.value))}
              className="w-14 rounded bg-bg-card px-2 py-1 text-xs text-text-1"
              style={{ border: '1px solid rgba(255,255,255,0.12)' }}
            />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-text-2">
            {'\u9648\u65e7\u4f1a\u8bdd\u5929\u6570'}
            <input
              type="number" min={1} max={365} value={staleConvDays} placeholder={'30'}
              onChange={(ev) => setStaleConvDays(ev.target.value === '' ? '' : Number(ev.target.value))}
              className="w-14 rounded bg-bg-card px-2 py-1 text-xs text-text-1"
              style={{ border: '1px solid rgba(255,255,255,0.12)' }}
            />
          </label>
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-text-3">
          {'\u7559\u7a7a = \u7528\u9ed8\u8ba4\u503c\u3002\u8bc4\u5206\u9608\u503c\u9ed8\u8ba4\u7ed9 40\uff08\u4f4e\u4e8e\u51fa\u5382 60\uff09\uff1a\u9608\u503c\u592a\u9ad8\u4f1a\u5bfc\u81f4\u672c\u8f6e\u6295\u4e0d\u51fa\u53bb\uff0c\u5192\u70df\u5c31\u300c\u672a\u8986\u76d6\u300d\u6295\u9012\u8def\u5f84\uff0c\u95e8\u5f62\u540c\u865a\u8bbe\u3002'}
        </p>
      </div>

      <div className="mb-3 rounded-lg p-3" style={{ background: 'rgba(255,69,58,0.08)', border: '1px solid rgba(255,69,58,0.3)' }}>
        <p className="mb-2 text-xs font-semibold" style={{ color: '#ff453a' }}>{'\u771f\u8dd1\u6863 \u00b7 \u771f\u6295\u771f\u53d1\uff08\u6d88\u8017\u914d\u989d\u3001\u52a8\u771f\u5b9e HR\uff09'}</p>
        <p className="mb-2 text-xs leading-relaxed text-text-3">{'\u771f\u5b9e\u6295\u9012 + \u771f\u53d1\u7b80\u5386 + \u540c\u610f\u5fae\u4fe1\u7ed9\u771f\u5b9e HR\uff0c\u4e0d\u53ef\u64a4\u9500\uff1b\u8dd1\u5b8c\u65ad\u8a00\u300c\u771f\u53d1\u51fa\u53bb\u4e14\u5df2\u843d\u5e93\u300d\u3002'}</p>
        <button
          type="button"
          onClick={() => setConfirmLive(true)}
          disabled={running}
          className="rounded-lg px-3 py-1.5 text-xs font-medium transition disabled:opacity-50"
          style={{ background: 'rgba(255,69,58,0.16)', color: '#ff453a', boxShadow: 'inset 0 0 0 1px rgba(255,69,58,0.35)' }}
        >
          {'\u771f\u8dd1\uff08\u771f\u6295\u771f\u53d1\uff09'}
        </button>
      </div>

      {confirmLive && (
        <div className="mb-3 rounded-lg p-3" style={{ background: 'rgba(255,69,58,0.12)', border: '1px solid rgba(255,69,58,0.4)' }}>
          <p className="mb-1 text-xs font-semibold" style={{ color: '#ff453a' }}>{'\u786e\u8ba4\u771f\u8dd1\u5192\u70df\uff1f'}</p>
          <p className="mb-2 text-xs leading-relaxed text-text-2">
            {'\u5c06\u771f\u5b9e\u6295\u9012 '}{w1Max}{' \u4e2a\u5c97\u4f4d\u3001\u5904\u7406 '}{w2Max}{' \u4e2a\u4f1a\u8bdd\u5e76\u771f\u53d1\u7b80\u5386/\u540c\u610f\u5fae\u4fe1\u7ed9\u771f\u5b9e HR\u3002\u4e0d\u53ef\u64a4\u9500\u3001\u6d88\u8017 Boss \u6bcf\u65e5\u914d\u989d\u3002'}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              onClick={() => void run('live')}
              className="rounded-lg px-3 py-1.5 text-xs font-medium"
              style={{ background: '#ff453a', color: '#fff' }}
            >
              {'\u786e\u8ba4\u771f\u8dd1'}
            </button>
            <button
              type="button"
              onClick={() => setConfirmLive(false)}
              className="rounded-lg px-3 py-1.5 text-xs font-medium text-text-2"
              style={{ border: '1px solid rgba(255,255,255,0.15)' }}
            >
              {'\u53d6\u6d88'}
            </button>
          </div>
        </div>
      )}

      {err && (
        <p className="mb-3 rounded-lg bg-signal-red/10 px-3 py-2 text-xs text-signal-red">{err}</p>
      )}

      {running && (
        <p className="text-xs text-text-3">{'\u6b63\u5728\u771f\u673a\u5192\u70df\uff0c\u6bcf 5 \u79d2\u5237\u65b0\u7ed3\u679c\u2026\u2026'}</p>
      )}

      {report && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            {/* Three states, not two: red = something failed, amber = passed but the
                run never exercised the path (verified nothing), green = fully covered.
                Collapsing amber into green is how a smoke test stops being a gate. */}
            <span
              className="flex items-center gap-1.5 font-semibold"
              style={{ color: !report.ok ? '#ff453a' : report.fully_covered === false ? '#ff9f0a' : '#30d158' }}
            >
              <span>{!report.ok ? '\u2715' : report.fully_covered === false ? '\u26a0' : '\u2713'}</span>
              <span>
                {!report.ok
                  ? '\u6709\u5931\u8d25'
                  : report.fully_covered === false
                    ? '\u901a\u8fc7\u4f46\u672a\u5168\u8986\u76d6'
                    : '\u5168\u8986\u76d6\u901a\u8fc7'}
              </span>
            </span>
            {report.mode && (
              <span
                className="rounded px-1.5 py-0.5 text-[10px] font-medium"
                style={
                  report.mode === 'live'
                    ? { background: 'rgba(255,69,58,0.16)', color: '#ff453a' }
                    : { background: 'rgba(10,132,255,0.16)', color: '#2997ff' }
                }
              >
                {report.mode === 'live' ? '\u771f\u8dd1' : 'dry-run'}
              </span>
            )}
            <span className="text-text-3">{report.duration_s}{'s'}</span>
            <span className="text-text-3">{report.ran_at}</span>
          </div>
          {report.error && (
            <p className="rounded-lg bg-signal-red/10 px-3 py-2 text-xs text-signal-red">{report.error}</p>
          )}
          {report.checks.map((c) => (
            <div key={c.name} className="rounded-lg p-2" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
              <div className="flex items-start gap-2 text-xs">
                <span style={{ color: !c.ok ? '#ff453a' : c.covered === false ? '#ff9f0a' : '#30d158' }}>
                  {!c.ok ? '\u2715' : c.covered === false ? '\u26a0' : '\u2713'}
                </span>
                <span className="flex-1 text-text-2">{c.name}</span>
                {c.covered === false && c.ok && (
                  <span
                    className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium"
                    style={{ background: 'rgba(255,159,10,0.16)', color: '#ff9f0a' }}
                  >
                    {'\u672a\u8986\u76d6'}
                  </span>
                )}
                <span className="shrink-0 text-text-3">{c.duration_s}{'s'}</span>
              </div>
              <p className="ml-5 mt-0.5 text-xs text-text-3">{c.detail}</p>
            </div>
          ))}

          {/* State the gaps at the point of use, so a green badge is never read as
              "everything is verified". */}
          {report.fully_covered === false && (report.uncovered?.length ?? 0) > 0 && (
            <p className="rounded-lg px-3 py-2 text-xs leading-relaxed" style={{ background: 'rgba(255,159,10,0.1)', color: '#ff9f0a' }}>
              {'\u672c\u6b21\u672a\u771f\u6b63\u9a8c\u8bc1\u5230\uff1a'}{report.uncovered?.join('\u3001')}
              {'\u3002\u65e0\u5931\u8d25\u4e0d\u7b49\u4e8e\u5df2\u9a8c\u8bc1\u2014\u2014\u6539\u52a8\u540e\u8bf7\u786e\u8ba4\u76f8\u5173\u8def\u5f84\u771f\u7684\u8dd1\u5230\u4e86\u3002'}
            </p>
          )}
          {(report.not_covered_paths?.length ?? 0) > 0 && (
            <p className="text-xs leading-relaxed text-text-3">
              {'\u5192\u70df\u4e0d\u8986\u76d6\uff1a'}{report.not_covered_paths?.join('\u3001')}
            </p>
          )}

          {/* Run-log diagnosis: the verdict derived from the durable JSONL, which
              survives a crash that would leave this report unwritten. Params that
              never reached the runner are called out \u2014 the run can look healthy
              while proving nothing about the setting you asked for. */}
          {(report.diagnostics?.length ?? 0) > 0 && (
            <div className="rounded-lg p-2" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
              <button
                type="button"
                onClick={() => setShowDiag((v) => !v)}
                className="flex w-full items-center justify-between text-left text-xs text-text-2"
              >
                <span className="flex items-center gap-2">
                  <span>{'\u8fd0\u884c\u65e5\u5fd7\u8bca\u65ad'}</span>
                  {report.diagnostics_verdict?.params_applied === false && (
                    <span className="rounded px-1.5 py-0.5 text-[10px]" style={{ background: 'rgba(255,159,10,0.16)', color: '#ff9f0a' }}>
                      {'\u53c2\u6570\u672a\u751f\u6548'}
                    </span>
                  )}
                  {report.diagnostics_verdict?.ok === false && (
                    <span className="rounded px-1.5 py-0.5 text-[10px]" style={{ background: 'rgba(255,69,58,0.16)', color: '#ff453a' }}>
                      {'\u6709\u5f02\u5e38'}
                    </span>
                  )}
                  {report.diagnostics_verdict?.ok === true && (
                    <span className="rounded px-1.5 py-0.5 text-[10px]" style={{ background: 'rgba(48,209,88,0.14)', color: '#30d158' }}>
                      {'\u65e5\u5fd7\u65e0\u5f02\u5e38'}
                    </span>
                  )}
                </span>
                <span className="text-text-3">{showDiag ? '\u2212' : '+'}</span>
              </button>
              {showDiag && (
                <div className="mt-2 space-y-2">
                  {report.diagnostics?.map((d, i) => (
                    <pre
                      key={d.run_id ?? `diag-${i}`}
                      className="overflow-x-auto rounded p-2 text-[11px] leading-relaxed text-text-3"
                      style={{ background: 'rgba(0,0,0,0.25)' }}
                    >
                      {d.report || (d.anomalies ?? []).join('\n')}
                    </pre>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

type RegTab = 'env' | 'logic' | 'data' | 'e2e'

const REG_TABS: Array<{ key: RegTab; label: string; layer: string; hint: string }> = [
  { key: 'env', label: '\u73af\u5883', layer: 'LAYER 0 / ENV', hint: '\u63a2\u9488\uff1a\u767b\u5f55\u6001 / DB / LLM \u53ef\u8fbe\u6027' },
  { key: 'logic', label: '\u903b\u8f91', layer: 'LAYER 1 / LOGIC', hint: 'pytest \u5168\u91cf\u5957\u4ef6' },
  { key: 'data', label: '\u6570\u636e', layer: 'LAYER 2 / DATA', hint: '\u5e93\u5185\u4e0d\u53d8\u91cf\uff1a\u72b6\u6001\u673a / \u6c34\u4f4d\u7ebf / \u5f15\u7528\u5b8c\u6574\u6027' },
  { key: 'e2e', label: '\u771f\u673a', layer: 'LAYER 3 / E2E', hint: '\u5f00\u6d4f\u89c8\u5668\u8dd1 W1+W2\uff1b\u771f\u8dd1\u6863\u4f1a\u771f\u6295\u771f\u53d1' },
]

function RegressionSection() {
  const [sub, setSub] = useState<RegTab>('env')
  const active = REG_TABS.find((t) => t.key === sub) ?? REG_TABS[0]

  return (
    <div className="space-y-3">
      {/* Second-level tabs, deliberately lighter than the top-level pills
          (underline vs filled block) so the hierarchy reads at a glance. */}
      <div className="flex gap-6 border-b" style={{ borderColor: 'rgba(255,255,255,0.08)' }}>
        {REG_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setSub(t.key)}
            className={`-mb-px border-b-2 px-1 pb-2.5 text-[15px] font-medium transition ${
              sub === t.key ? 'text-text-1' : 'border-transparent text-text-3 hover:text-text-2'
            }`}
            style={sub === t.key ? { borderColor: '#2997ff' } : undefined}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <p className="text-[10px] font-medium tracking-widest text-text-3 uppercase select-none">{active.layer}</p>
        <p className="text-xs text-text-3">{active.hint}</p>
      </div>

      {/* Hidden rather than unmounted: a live smoke runs for minutes and polls for
          its result, and switching tabs mid-run would unmount the card, kill the
          poll, and lose the "running" state. Keeping all four mounted costs four
          light GETs on entry and keeps long-running state alive. */}
      <div className={sub === 'env' ? undefined : 'hidden'}><SelfCheckSection /></div>
      <div className={sub === 'logic' ? undefined : 'hidden'}><PytestCard /></div>
      <div className={sub === 'data' ? undefined : 'hidden'}><InvariantCard /></div>
      <div className={sub === 'e2e' ? undefined : 'hidden'}><SmokeCard /></div>
    </div>
  )
}

export default function Automation() {
  const [tab, setTab] = useState<AutoTab>('schedule')
  return (
    <div className="relative space-y-4">
      <DevLabel name="Automation" float />
      <div className="flex gap-1 rounded-xl p-1" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.06)' }}>
        {AUTO_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`flex-1 rounded-lg px-3 py-1.5 text-[16px] font-medium transition ${
              tab === t.key ? 'text-text-1' : 'text-text-3 hover:text-text-2'
            }`}
            style={tab === t.key ? { background: 'rgba(10,132,255,0.16)', boxShadow: 'inset 0 0 0 1px rgba(10,132,255,0.3)' } : undefined}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Same reasoning as the inner tabs: hide, don't unmount. Switching to the
          schedule tab while a live smoke is running must not kill its poll. */}
      <div className={tab === 'schedule' ? 'space-y-5' : 'hidden'}>
        <div>
          <p className="mb-2 text-[10px] font-medium tracking-widest text-text-3 uppercase select-none">AUTO SCHEDULE</p>
          <ScheduleCard />
        </div>
        <div>
          <p className="mb-2 text-[10px] font-medium tracking-widest text-text-3 uppercase select-none">SCHEDULE LOG</p>
          <ScheduleLogCard />
        </div>
      </div>
      <div className={tab === 'regression' ? undefined : 'hidden'}>
        <RegressionSection />
      </div>
    </div>
  )
}
