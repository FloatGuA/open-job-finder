import { useEffect, useMemo, useState } from 'react'
import { API, type PoolDiff, type PoolDiffBlock, type PoolPending } from '@/api'

// \u4fe1\u606f\u6c60\u7684\u53d8\u66f4\u63d0\u6848\uff1a\u673a\u5668\u6539\u6c60\uff08\u4e0a\u4f20\u89e3\u6790 / AI \u6574\u7406\uff09\u4e0d\u76f4\u63a5\u843d\u76d8\uff0c\u5148\u5728\u8fd9\u91cc\u7ed9\u4eba\u770b diff\u3001
// \u52fe\u9009\u3001\u518d\u5199\u3002\u6c60\u662f\u6c42\u804c\u8005\u5168\u90e8\u4fe1\u606f\u7684\u552f\u4e00\u4e3b\u5e93\uff0c\u800c LLM \u6574\u7406\u662f**\u6574\u4f53\u91cd\u5199 sections**\u3001
// \u4f1a\u628a\u5b83\u6ca1\u63d0\u5230\u7684\u5757\u5f04\u4e22\u2014\u2014\u539f\u5148\u53ea\u6709"\u5199\u524d\u5feb\u7167 + \u4e8b\u540e\u56de\u6eda"\uff0c\u90a3\u662f\u5185\u5bb9\u5df2\u88ab\u8986\u76d6\u4e4b\u540e\u7684\u8865\u6551\u3002

const T_TITLE = '\u4fe1\u606f\u6c60\u6709\u5f85\u786e\u8ba4\u7684\u53d8\u66f4'
const T_FROM_UPLOAD = '\u6765\u81ea\u7b80\u5386\u89e3\u6790'
const T_FROM_BUILD = '\u6765\u81ea AI \u6574\u7406'
const T_HINT = '\u52fe\u4e0a\u7684\u624d\u4f1a\u5199\u8fdb\u4fe1\u606f\u6c60\uff0c\u6ca1\u52fe\u7684\u4fdd\u6301\u539f\u6837\u3002'
const T_BASIC = '\u57fa\u672c\u4fe1\u606f'
const T_KIND_ADDED = '\u65b0\u589e'
const T_KIND_CHANGED = '\u4fee\u6539'
const T_KIND_REMOVED = '\u5220\u9664'
const T_SECTION_NEW = '\u65b0\u5206\u533a'
const T_APPLY = '\u5e94\u7528\u9009\u4e2d'
const T_DISCARD = '\u5168\u90e8\u4e22\u5f03'
const T_SELECT_ALL = '\u5168\u9009'
const T_CLEAR = '\u5168\u4e0d\u9009'
const T_APPLYING = '\u5199\u5165\u4e2d\u2026'
const T_CONFIRM_DISCARD = '\u4e22\u5f03\u8fd9\u4efd\u63d0\u6848\uff1f\u4fe1\u606f\u6c60\u4e0d\u4f1a\u6539\u53d8\uff0c\u4f46\u8fd9\u6b21\u89e3\u6790\u51fa\u7684\u5185\u5bb9\u5c31\u6ca1\u4e86\u3002'
const T_REMOVED_WARN = '\u63d0\u6848\u4e3b\u5f20\u5220\u6389\u5b83\u3002\u52fe\u4e0a = \u540c\u610f\u5220\u9664\u3002'
const T_EMPTY = '\u6ca1\u6709\u5f85\u786e\u8ba4\u7684\u53d8\u66f4'

const KIND_STYLE: Record<PoolDiffBlock['kind'], { label: string; color: string }> = {
  added: { label: T_KIND_ADDED, color: '#30d158' },
  changed: { label: T_KIND_CHANGED, color: '#ff9f0a' },
  removed: { label: T_KIND_REMOVED, color: '#ff453a' },
}

function KindBadge({ kind }: { kind: PoolDiffBlock['kind'] }) {
  const s = KIND_STYLE[kind]
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[11.5px] font-semibold"
      style={{ background: `${s.color}22`, color: s.color }}
    >
      {s.label}
    </span>
  )
}

/** \u9010\u6761\u7684\u589e\u5220\u5bf9\u7167\u3002\u8981\u70b9\u901a\u5e38\u53ea\u52a8\u4e00\u4e24\u6761\uff0c\u6574\u5757\u7ea2\u7eff\u4f1a\u8ba9\u4eba\u770b\u4e0d\u51fa\u6539\u4e86\u5565\u3002 */
function BulletDiff({ lines }: { lines: { op: string; text: string }[] }) {
  if (lines.length === 0) return null
  return (
    <div className="mt-1.5 overflow-hidden rounded-lg" style={{ border: '1px solid rgba(255,255,255,0.08)' }}>
      {lines.map((l, i) => {
        const bg = l.op === '+' ? 'rgba(48,209,88,0.12)' : l.op === '-' ? 'rgba(255,69,58,0.12)' : 'transparent'
        const fg = l.op === '+' ? '#30d158' : l.op === '-' ? '#ff453a' : '#adadb8'
        return (
          <div key={i} className="flex gap-2 px-2.5 py-1 font-mono text-[12.5px] leading-relaxed" style={{ background: bg }}>
            <span className="shrink-0 select-none" style={{ color: fg }}>{l.op === ' ' ? '\u00a0' : l.op}</span>
            <span className="min-w-0 flex-1 break-words" style={{ color: l.op === ' ' ? '#84848c' : fg }}>{l.text}</span>
          </div>
        )
      })}
    </div>
  )
}

function Row({
  checked,
  onToggle,
  children,
}: {
  checked: boolean
  onToggle: () => void
  children: React.ReactNode
}) {
  return (
    <div
      className="flex items-start gap-3 rounded-xl px-3 py-2.5"
      style={{
        background: checked ? 'rgba(10,132,255,0.09)' : 'rgba(255,255,255,0.03)',
        border: `1px solid ${checked ? 'rgba(10,132,255,0.28)' : 'rgba(255,255,255,0.07)'}`,
      }}
    >
      <input type="checkbox" checked={checked} onChange={onToggle}
             className="mt-0.5 h-[16px] w-[16px] shrink-0 accent-[#0a84ff]" />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  )
}

export default function PoolDiffPanel({ onApplied }: { onApplied: () => void }) {
  const [state, setState] = useState<PoolPending | null>(null)
  const [checked, setChecked] = useState<Set<string>>(new Set())
  const [busy, setBusy] = useState(false)

  const load = () => {
    API.getPoolPending()
      .then((r) => {
        setState(r)
        // \u9ed8\u8ba4\u52fe\u9009\u7531\u540e\u7aef\u7ed9\uff08accept_default\uff09\uff1a\u65b0\u589e\u9ed8\u8ba4\u9009\u4e0a\uff0c
        // \u4fee\u6539/\u5220\u9664\u9ed8\u8ba4\u4e0d\u9009\u2014\u2014\u524d\u8005\u8986\u76d6\u5df2\u6709\u5185\u5bb9\uff0c\u540e\u8005\u662f\u5220\u9664\u3002
        const d = r.diff
        if (!d) return setChecked(new Set())
        const init = new Set<string>()
        for (const b of d.basic_info) if (b.accept_default) init.add(b.key)
        for (const s of d.sections) for (const b of s.blocks) if (b.accept_default) init.add(b.key)
        setChecked(init)
      })
      .catch(() => setState({ pending: false }))
  }

  useEffect(() => { load() }, [])

  const diff: PoolDiff | undefined = state?.diff
  const allKeys = useMemo(() => {
    if (!diff) return [] as string[]
    return [
      ...diff.basic_info.map((b) => b.key),
      ...diff.sections.flatMap((s) => s.blocks.map((b) => b.key)),
    ]
  }, [diff])

  if (!state?.pending || !diff?.has_changes) return null

  const toggle = (k: string) =>
    setChecked((prev) => {
      const next = new Set(prev)
      if (next.has(k)) next.delete(k)
      else next.add(k)
      return next
    })

  const apply = async () => {
    setBusy(true)
    try {
      await API.applyPoolPending([...checked])
      setState({ pending: false })
      onApplied()
    } finally {
      setBusy(false)
    }
  }

  const discard = async () => {
    if (!window.confirm(T_CONFIRM_DISCARD)) return
    setBusy(true)
    try {
      await API.discardPoolPending()
      setState({ pending: false })
      onApplied()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="rounded-2xl p-4" style={{ background: 'rgba(255,159,10,0.06)', border: '1px solid rgba(255,159,10,0.3)' }}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <span className="text-[15px] font-semibold" style={{ color: '#ff9f0a' }}>{T_TITLE}</span>
        <span className="text-[12.5px] text-text-3">
          {state.source === 'build' ? T_FROM_BUILD : T_FROM_UPLOAD}
          {state.created_at ? `\u00b7 ${state.created_at}` : ''}
        </span>
        <div className="flex-1" />
        <button type="button" onClick={() => setChecked(new Set(allKeys))}
                className="rounded-lg px-2.5 py-1 text-[12.5px] text-text-2 transition hover:text-text-1"
                style={{ background: 'rgba(255,255,255,0.07)' }}>
          {T_SELECT_ALL}
        </button>
        <button type="button" onClick={() => setChecked(new Set())}
                className="rounded-lg px-2.5 py-1 text-[12.5px] text-text-2 transition hover:text-text-1"
                style={{ background: 'rgba(255,255,255,0.07)' }}>
          {T_CLEAR}
        </button>
      </div>
      <p className="mt-1 text-[12.5px] text-text-2">{T_HINT}</p>

      <div className="mt-3 space-y-3">
        {diff.basic_info.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-[13px] font-semibold text-text-1">{T_BASIC}</p>
            {diff.basic_info.map((b) => (
              <Row key={b.key} checked={checked.has(b.key)} onToggle={() => toggle(b.key)}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-[13px] text-text-1">{b.key.split('\u241f')[1]}</span>
                  <KindBadge kind={b.kind} />
                </div>
                <p className="mt-1 text-[13px]">
                  {b.old && <span className="line-through" style={{ color: '#ff453a' }}>{b.old}</span>}
                  {b.old && <span className="mx-2 text-text-3">{'\u2192'}</span>}
                  <span style={{ color: '#30d158' }}>{b.new}</span>
                </p>
              </Row>
            ))}
          </div>
        )}

        {diff.sections.map((s) => (
          <div key={s.name} className="space-y-1.5">
            <p className="flex items-center gap-2 text-[13px] font-semibold text-text-1">
              {s.name}
              {s.kind === 'added' && (
                <span className="rounded-full px-2 py-0.5 text-[11.5px] font-semibold"
                      style={{ background: 'rgba(48,209,88,0.18)', color: '#30d158' }}>
                  {T_SECTION_NEW}
                </span>
              )}
            </p>
            {s.blocks.map((b) => (
              <Row key={b.key} checked={checked.has(b.key)} onToggle={() => toggle(b.key)}>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[13.5px] font-medium text-text-1">{b.title || '\u2014'}</span>
                  <KindBadge kind={b.kind} />
                </div>
                {b.kind === 'removed' && (
                  <p className="mt-1 text-[12px]" style={{ color: '#ff453a' }}>{T_REMOVED_WARN}</p>
                )}
                {b.fields.map((f) => (
                  <p key={f.field} className="mt-1 text-[12.5px]">
                    <span className="text-text-3">{f.field}</span>
                    <span className="mx-1.5 text-text-3">:</span>
                    {f.old && <span className="line-through" style={{ color: '#ff453a' }}>{f.old}</span>}
                    {f.old && <span className="mx-2 text-text-3">{'\u2192'}</span>}
                    <span style={{ color: '#30d158' }}>{f.new || '\u2014'}</span>
                  </p>
                ))}
                <BulletDiff lines={b.bullets} />
              </Row>
            ))}
          </div>
        ))}
      </div>

      <div className="mt-3.5 flex flex-wrap items-center gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => void apply()}
          className="rounded-lg px-4 py-1.5 text-[13.5px] font-semibold text-white transition disabled:opacity-40"
          style={{ background: '#30a14e' }}
        >
          {busy ? T_APPLYING : `${T_APPLY} ${checked.size}`}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void discard()}
          className="rounded-lg bg-bg-card2 px-3.5 py-1.5 text-[13.5px] text-text-2 transition disabled:opacity-40"
        >
          {T_DISCARD}
        </button>
      </div>
    </div>
  )
}

export { T_EMPTY }
