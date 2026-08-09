import { useEffect, useMemo, useState } from 'react'
import { API, type PrepCard, type PrepDoc, type PrepKind } from '@/api'
import DevLabel from '@/components/dev/DevLabel'

// Interview prep, split out of the architecture page (was its 5th tab) into its own
// navigator. Content lives in code/data/interview_prep.yaml -- gitignored, personal
// material, edited by hand. This page is read-only: fetch, group by kind, render.
// Answers start collapsed so the page doubles as self-quizzing.

const T_INTRO_A = '\u6309\u5c97\u4f4d\u7ec4\u7ec7\u7684\u9762\u8bd5\u95ee\u7b54\u5361\u7247\u3002'
const T_INTRO_B = '\u5185\u5bb9\u5b58\u5728 code/data/interview_prep.yaml\uff08\u4e0d\u5165 git\uff09\uff0c\u6539\u5b8c\u5237\u65b0\u9875\u9762\u5373\u53ef\uff0c\u4e0d\u7528\u91cd\u65b0\u6784\u5efa\u3002'
const T_EMPTY_T = '\u8fd8\u6ca1\u6709\u9762\u8bd5\u5361\u7247'
const T_EMPTY_D = '\u5728 code/data/interview_prep.yaml \u91cc\u6309\u5c97\u4f4d\u5199 roles/cards\uff0c\u6bcf\u5f20\u5361\u52a0 kind: project\uff08\u9488\u5bf9\u672c\u9879\u76ee\uff09\u6216 kind: basics\uff08\u901a\u7528\u516b\u80a1\uff09\u3002'
const T_ALL = '\u5168\u90e8'
const T_PROJECT = '\u9879\u76ee\u95ee\u7b54'
const T_BASICS = '\u901a\u7528\u516b\u80a1'
const T_EXPAND = '\u5168\u90e8\u5c55\u5f00'
const T_COLLAPSE = '\u5168\u90e8\u6536\u8d77'
const T_PITCH = '\u7535\u68af\u9648\u8ff0'
const T_EVIDENCE = '\u652f\u6491\u8bc1\u636e'
const T_AVOID = '\u522b\u8fd9\u4e48\u8bf4'
const T_NO_CARD = '\u8fd9\u4e2a\u5c97\u4f4d\u5728\u5f53\u524d\u7b5b\u9009\u4e0b\u6ca1\u6709\u5361\u7247\u3002'

const KIND_STYLE: Record<PrepKind, { label: string; accent: string }> = {
  project: { label: T_PROJECT, accent: '#0a84ff' },
  basics: { label: T_BASICS, accent: '#30d158' },
}

// Card bodies support **bold** and nothing else -- a full markdown renderer is
// overkill for emphasising a phrase. An odd number of ** leaves the tail as plain text.
function RichText({ text }: { text: string }) {
  const parts = text.split('**')
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1
          ? <strong key={i} className="font-semibold text-text-1">{p}</strong>
          : <span key={i}>{p}</span>
      )}
    </>
  )
}

function Pill({ n, accent }: { n: number; accent: string }) {
  return (
    <span className="shrink-0 rounded-full px-1.5 py-px font-mono text-[13.5px] font-semibold"
      style={{ background: `${accent}26`, color: accent }}>
      {n}
    </span>
  )
}

function CardBox({ card, n, open, onToggle }: {
  card: PrepCard; n: number; open: boolean; onToggle: () => void
}) {
  const accent = KIND_STYLE[card.kind].accent
  return (
    <div className="rounded-xl" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
      <button type="button" onClick={onToggle}
        className="flex w-full items-baseline gap-2.5 px-3.5 py-3 text-left">
        <Pill n={n} accent={accent} />
        <span className="flex-1 text-[15.5px] font-semibold leading-snug text-text-1">{card.q}</span>
        <span className={`shrink-0 text-[13px] transition-transform duration-150 ${open ? 'rotate-90' : ''}`}
          style={{ color: accent }}>{'\u25b8'}</span>
      </button>

      {open && (
        <div className="px-3.5 pb-3.5">
          {card.a && <p className="text-[14.5px] leading-relaxed text-text-2"><RichText text={card.a} /></p>}
          {card.evidence.length > 0 && (
            <div className="mt-2.5 rounded-lg p-2.5" style={{ background: 'rgba(10,132,255,0.06)', border: '1px solid rgba(10,132,255,0.16)' }}>
              <div className="mb-1 text-[12px] font-semibold uppercase tracking-wider text-signal-blue">{T_EVIDENCE}</div>
              <ul className="space-y-1">
                {card.evidence.map((e, i) => (
                  <li key={i} className="flex gap-2 text-[14px] leading-relaxed text-text-2">
                    <span className="text-text-3">&middot;</span><span><RichText text={e} /></span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          {card.avoid && (
            <div className="mt-2 rounded-lg px-2.5 py-2" style={{ background: 'rgba(255,69,58,0.06)', border: '1px solid rgba(255,69,58,0.18)' }}>
              <span className="text-[12px] font-semibold uppercase tracking-wider" style={{ color: '#ff6961' }}>{T_AVOID}</span>
              <p className="mt-0.5 text-[14px] leading-relaxed text-text-2"><RichText text={card.avoid} /></p>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Chip({ active, accent, label, count, onClick }: {
  active: boolean; accent?: string; label: string; count?: number; onClick: () => void
}) {
  const tint = accent ?? '#0a84ff'
  return (
    <button type="button" onClick={onClick}
      className={`rounded-lg px-3 py-1.5 text-[14px] font-medium transition ${active ? 'text-text-1' : 'text-text-3 hover:text-text-2'}`}
      style={active
        ? { background: `${tint}29`, boxShadow: `inset 0 0 0 1px ${tint}4d` }
        : { border: '1px solid rgba(255,255,255,0.08)' }}>
      {label}
      {count !== undefined && <span className="ml-1.5 font-mono text-[13px] text-text-3">{count}</span>}
    </button>
  )
}

type Filter = 'all' | PrepKind

export default function InterviewPrep() {
  const [doc, setDoc] = useState<PrepDoc | null>(null)
  const [role, setRole] = useState<string>('')
  const [filter, setFilter] = useState<Filter>('all')
  const [openKeys, setOpenKeys] = useState<Set<string>>(new Set())

  useEffect(() => {
    API.getInterviewPrep()
      .then((d) => {
        setDoc(d)
        if (d.roles.length > 0) setRole(d.roles[0].key)
      })
      .catch(() => setDoc({ roles: [] }))
  }, [])

  const cur = doc?.roles.find((r) => r.key === role) ?? null
  const counts = useMemo(() => ({
    project: cur?.cards.filter((c) => c.kind === 'project').length ?? 0,
    basics: cur?.cards.filter((c) => c.kind === 'basics').length ?? 0,
  }), [cur])

  // Groups render in a fixed order so the page does not reshuffle between roles.
  const groups = useMemo(() => {
    if (!cur) return []
    const kinds: PrepKind[] = filter === 'all' ? ['project', 'basics'] : [filter]
    return kinds
      .map((k) => ({ kind: k, cards: cur.cards.filter((c) => c.kind === k) }))
      .filter((g) => g.cards.length > 0)
  }, [cur, filter])

  const visibleKeys = useMemo(
    () => groups.flatMap((g) => g.cards.map((c) => `${role}:${c.q}`)),
    [groups, role]
  )
  const allOpen = visibleKeys.length > 0 && visibleKeys.every((k) => openKeys.has(k))

  function toggle(key: string) {
    setOpenKeys((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // Switching role resets the open set: keys are role-scoped, and carrying a stale
  // set over means the new role opens in a half-expanded state nobody asked for.
  function pickRole(key: string) {
    setRole(key)
    setOpenKeys(new Set())
  }

  return (
    <div className="relative space-y-4">
      <DevLabel name="InterviewPrep" float />
      <p className="text-[16px] leading-relaxed text-text-2">
        <span className="text-text-1">{T_INTRO_A}</span>
        {T_INTRO_B}
      </p>

      {doc && doc.roles.length === 0 && (
        <div className="rounded-xl p-5 text-center" style={{ border: '1px dashed rgba(255,255,255,0.12)' }}>
          <p className="text-[15px] font-semibold text-text-1">{T_EMPTY_T}</p>
          <p className="mt-1.5 text-[14px] leading-relaxed text-text-3">{T_EMPTY_D}</p>
        </div>
      )}

      {doc && doc.roles.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {doc.roles.map((r) => (
            <Chip key={r.key} active={role === r.key} label={r.name} onClick={() => pickRole(r.key)} />
          ))}
        </div>
      )}

      {cur && cur.pitch && (
        <div className="relative overflow-hidden rounded-2xl bg-bg-card p-5 shadow-card">
          <div className="pointer-events-none absolute inset-0 rounded-2xl" style={{ border: '1px solid rgba(255,255,255,0.08)' }} />
          <div className="mb-2 flex items-baseline gap-2.5">
            <span className="rounded px-1.5 py-0.5 font-mono text-[15px] font-bold bg-signal-blue/18 text-signal-bright">{'\u2460'}</span>
            <span className="text-[18px] font-semibold text-text-1">{T_PITCH}</span>
            <span className="text-[15px] text-text-3">{cur.name}</span>
          </div>
          <p className="text-[15.5px] leading-relaxed text-text-1"><RichText text={cur.pitch} /></p>
          {cur.hook && (
            <div className="mt-3 rounded-xl p-3" style={{ background: 'rgba(10,132,255,0.06)', border: '1px solid rgba(10,132,255,0.18)' }}>
              <p className="text-[14.5px] leading-relaxed text-text-2"><RichText text={cur.hook} /></p>
            </div>
          )}
        </div>
      )}

      {cur && (
        <div className="flex flex-wrap items-center gap-1.5">
          <Chip active={filter === 'all'} label={T_ALL} count={counts.project + counts.basics} onClick={() => setFilter('all')} />
          <Chip active={filter === 'project'} accent={KIND_STYLE.project.accent} label={T_PROJECT} count={counts.project}
            onClick={() => setFilter('project')} />
          <Chip active={filter === 'basics'} accent={KIND_STYLE.basics.accent} label={T_BASICS} count={counts.basics}
            onClick={() => setFilter('basics')} />
          <button type="button"
            onClick={() => setOpenKeys(allOpen ? new Set() : new Set(visibleKeys))}
            className="ml-auto rounded-lg px-3 py-1.5 text-[14px] font-medium text-text-3 transition hover:text-text-1"
            style={{ border: '1px solid rgba(255,255,255,0.08)' }}>
            {allOpen ? T_COLLAPSE : T_EXPAND}
          </button>
        </div>
      )}

      {cur && groups.length === 0 && (
        <p className="px-1 text-[14px] text-text-3">{T_NO_CARD}</p>
      )}

      {groups.map((g) => (
        <div key={g.kind} className="space-y-2.5">
          {filter === 'all' && (
            <div className="flex items-center gap-2 px-1 pt-1">
              <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: KIND_STYLE[g.kind].accent }} />
              <span className="text-[14px] font-semibold uppercase tracking-wider text-text-3">{KIND_STYLE[g.kind].label}</span>
              <span className="font-mono text-[13px] text-text-3">{g.cards.length}</span>
            </div>
          )}
          {g.cards.map((c, i) => {
            const key = `${role}:${c.q}`
            return <CardBox key={key} card={c} n={i + 1} open={openKeys.has(key)} onToggle={() => toggle(key)} />
          })}
        </div>
      ))}
    </div>
  )
}
