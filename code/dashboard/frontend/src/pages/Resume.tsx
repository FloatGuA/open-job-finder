import { useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from 'react'
import { API, type ResumeBlocks, type ResumeBlock, type ResumeSection, type ResumeBasicInfo, type ResumeTemplate, type ResumePlan, type ResumeIndex, type ResumeExport, type PoolSnapshot, type FieldMarks, type PoolCurrent, type Job } from '@/api'
import DevLabel from '@/components/dev/DevLabel'
import PoolDiffPanel from '@/components/PoolDiffPanel'

// v2.16\uff1a\u5206\u533a\u4e0d\u518d\u56fa\u5b9a\uff0c\u540d\u79f0\u81ea\u5b9a\u4e49\uff08\u5982\u300c\u6e38\u620f\u7ecf\u5386\u300d\u300cAgent \u7ecf\u5386\u300d\uff09\u3002\u8fd9\u4e9b\u53ea\u662f\u65b0\u5efa\u65f6\u7684\u5feb\u6377\u5019\u9009\u3002
const SECTION_PRESETS = ['\u6559\u80b2\u7ecf\u5386', '\u5b9e\u4e60\u7ecf\u5386', '\u9879\u76ee\u7ecf\u5386', '\u6280\u80fd\u7279\u957f', '\u83b7\u5956\u8363\u8a89']
const BASIC_FIELDS: Array<{ key: keyof ResumeBasicInfo; label: string }> = [
  { key: 'name', label: '\u59d3\u540d' },
  { key: 'phone', label: '\u7535\u8bdd' },
  { key: 'email', label: '\u90ae\u7bb1' },
  { key: 'city', label: '\u57ce\u5e02' },
  { key: 'target_title', label: '\u671f\u671b\u5c97\u4f4d' },
]

const inputCls = 'w-full rounded-lg bg-bg-card2 px-3 py-2 text-sm text-text-1 focus:outline-none focus:ring-1 focus:ring-signal-blue'
const inputStyle: React.CSSProperties = { border: '1px solid rgba(255,255,255,0.08)' }

function Card({ title, children, dev, action }: { title: string; children: ReactNode; dev?: string; action?: ReactNode }) {
  return (
    <div className="relative overflow-hidden rounded-2xl bg-bg-card p-6 shadow-card">
      <div className="pointer-events-none absolute inset-0 rounded-2xl" style={{ border: '1px solid rgba(255,255,255,0.08)' }} />
      <div className="mb-5 flex items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-text-3">{title}{dev && <DevLabel name={dev} />}</h2>
        {action}
      </div>
      {children}
    </div>
  )
}

function emptyBlock(): ResumeBlock {
  return { title: '', time: '', bullets: [], summary: '' }
}

function parseBlocksCsv(s: string): Array<{ cat: string; idx: number }> {
  return s.split(',').map((x) => x.trim()).filter(Boolean).map((x) => {
    const [cat, idx] = x.split('#')
    return { cat: (cat || '').trim(), idx: parseInt(idx, 10) || 0 }
  })
}
function blocksToCsv(blocks: Array<{ cat: string; idx: number }>): string {
  return (blocks || []).map((b) => `${b.cat}#${b.idx}`).join(', ')
}

// \u529f\u80fd\u4e8c a\uff1a\u9884\u5236\u6a21\u677f\u7ba1\u7406\uff08\u5173\u952e\u8bcd\u5339\u914d\u5c97\u4f4d \u2192 \u5757\u7ec4\u5408\u8d77\u70b9 \u2192 LLM \u5fae\u8c03\uff09
function TemplatesCard() {
  const [list, setList] = useState<ResumeTemplate[]>([])
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  useEffect(() => { void API.getResumeTemplates().then(setList).catch(() => {}) }, [])
  const update = (i: number, patch: Partial<ResumeTemplate>) =>
    setList((l) => l.map((t, j) => (j === i ? { ...t, ...patch } : t)))
  const add = () => setList((l) => [...l, { name: '', keywords: [], blocks: [], greeting_style: '' }])
  const remove = (i: number) => setList((l) => l.filter((_, j) => j !== i))
  const save = async () => {
    setSaving(true); setSaved(false)
    try { await API.saveResumeTemplates(list); setSaved(true); window.setTimeout(() => setSaved(false), 3000) }
    finally { setSaving(false) }
  }
  return (
    <Card title={'\u9884\u5236\u6a21\u677f\uff08\u6309\u5c97\u4f4d\u5173\u952e\u8bcd\u5339\u914d\uff09'} dev="ResumeTemplates" action={
      <button type="button" onClick={add} className="rounded-lg px-3 py-1.5 text-xs text-signal-bright transition hover:bg-signal-blue/10">{'+ \u65b0\u6a21\u677f'}</button>
    }>
      <p className="mb-3 text-xs text-text-3">{'\u5c97\u4f4d\u6807\u9898/JD \u547d\u4e2d\u5173\u952e\u8bcd\u65f6\uff0c\u7528\u8be5\u6a21\u677f\u7684\u5757\u7ec4\u5408\u4e3a\u8d77\u70b9\uff0c\u518d\u7531 LLM \u6309\u5c97\u4f4d\u5fae\u8c03\uff1b\u547d\u4e2d\u591a\u4e2a\u53d6\u547d\u4e2d\u8bcd\u6700\u591a\u7684\u3002'}</p>
      {list.length === 0 ? <p className="text-xs text-text-3">{'\u6682\u65e0\u6a21\u677f\uff0c\u70b9\u300c+ \u65b0\u6a21\u677f\u300d'}</p> : (
        <div className="space-y-3">
          {list.map((t, i) => (
            <div key={i} className="space-y-2 rounded-xl bg-bg-card2 p-4" style={{ border: '1px solid rgba(255,255,255,0.06)' }}>
              <div className="flex items-center gap-2">
                <input className={inputCls} style={inputStyle} placeholder={'\u6a21\u677f\u540d\uff08\u5982 \u6e38\u620f\u7b56\u5212\uff09'} value={t.name} onChange={(e) => update(i, { name: e.target.value })} />
                <button type="button" onClick={() => remove(i)} className="shrink-0 px-1.5 text-signal-red transition hover:brightness-125">{'\u2715'}</button>
              </div>
              <label className="block">
                <span className="text-[11px] text-text-3">{'\u5339\u914d\u5173\u952e\u8bcd\uff08\u9017\u53f7\u5206\u9694\uff09'}</span>
                <input className={inputCls} style={inputStyle} value={t.keywords.join(', ')} onChange={(e) => update(i, { keywords: e.target.value.split(',').map((x) => x.trim()).filter(Boolean) })} />
              </label>
              <label className="block">
                <span className="text-[11px] text-text-3">{'\u5efa\u8bae\u5757\u7ec4\u5408\uff08\u53ef\u9009\uff0c\u5982 project#0, internship#1\uff09'}</span>
                <input className={inputCls} style={inputStyle} value={blocksToCsv(t.blocks)} onChange={(e) => update(i, { blocks: parseBlocksCsv(e.target.value) })} />
              </label>
              <label className="block">
                <span className="text-[11px] text-text-3">{'\u62db\u547c\u8bed\u98ce\u683c\uff08\u53ef\u9009\uff09'}</span>
                <input className={inputCls} style={inputStyle} value={t.greeting_style} onChange={(e) => update(i, { greeting_style: e.target.value })} />
              </label>
            </div>
          ))}
        </div>
      )}
      <div className="mt-4 flex items-center gap-3">
        <button type="button" onClick={() => void save()} disabled={saving} className="rounded-lg px-4 py-2 text-xs font-medium text-white transition disabled:opacity-40" style={{ background: '#0a84ff' }}>{saving ? '\u4fdd\u5b58\u4e2d\u2026' : '\u4fdd\u5b58\u6a21\u677f'}</button>
        {saved && <span className="text-xs text-signal-green">{'\u2713 \u5df2\u4fdd\u5b58'}</span>}
      </div>
    </Card>
  )
}

// \u529f\u80fd\u4e8c b\uff1a\u5c97\u4f4d\u7279\u5316\u751f\u6210\uff08\u6309\u9700\uff1a\u9009\u5c97\u4f4d \u2192 \u751f\u6210\u5b9a\u5236\u7b80\u5386/\u62db\u547c\u8bed \u2192 \u9884\u89c8 PDF\uff09
function TailorCard() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [jobId, setJobId] = useState('')
  const [plan, setPlan] = useState<ResumePlan | null>(null)
  const [genR, setGenR] = useState(false)
  const [genG, setGenG] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => { void API.getJobs('APPLIED', 1, 100).then((r) => setJobs(r.jobs)).catch(() => {}) }, [])
  useEffect(() => {
    if (!jobId) { setPlan(null); return }
    void API.getResumePlan(jobId).then(setPlan).catch(() => setPlan(null))
  }, [jobId])

  const job = jobs.find((j) => j.job_id === jobId)
  const genResume = async () => {
    if (!jobId) return
    setGenR(true); setErr(null)
    try { setPlan(await API.tailorResume({ job_id: jobId, job_title: job?.title, company: job?.company })) }
    catch (e) { setErr((e as Error).message) } finally { setGenR(false) }
  }
  const genGreeting = async () => {
    if (!jobId) return
    setGenG(true); setErr(null)
    try { setPlan(await API.tailorGreeting({ job_id: jobId, job_title: job?.title, company: job?.company })) }
    catch (e) { setErr((e as Error).message) } finally { setGenG(false) }
  }

  return (
    <Card title={'\u5c97\u4f4d\u7279\u5316\u751f\u6210\uff08\u6309\u9700\uff09'} dev="ResumeTailor">
      <p className="mb-3 text-xs text-text-3">{'\u9009\u4e00\u4e2a\u5df2\u6295\u9012\u5c97\u4f4d\uff0c\u6309\u5176\u7528\u79ef\u6728\u5e93\u751f\u6210\u5b9a\u5236\u7b80\u5386\u4e0e\u62db\u547c\u8bed\uff08\u547d\u4e2d\u9884\u5236\u6a21\u677f\u5219\u4ee5\u5176\u4e3a\u8d77\u70b9\uff09\u3002'}</p>
      <select className={inputCls} style={inputStyle} value={jobId} onChange={(e) => setJobId(e.target.value)}>
        <option value="">{'\u9009\u62e9\u5c97\u4f4d\u2026'}</option>
        {jobs.map((j) => <option key={j.job_id} value={j.job_id}>{`${j.company} \u00b7 ${j.title}`}</option>)}
      </select>
      {jobId && (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <button type="button" onClick={() => void genResume()} disabled={genR} className="rounded-lg px-4 py-2 text-xs font-medium text-text-1 transition disabled:opacity-40" style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)' }}>{genR ? '\u751f\u6210\u4e2d\u2026' : '\u751f\u6210\u5b9a\u5236\u7b80\u5386'}</button>
          <button type="button" onClick={() => void genGreeting()} disabled={genG} className="rounded-lg px-4 py-2 text-xs font-medium text-text-1 transition disabled:opacity-40" style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)' }}>{genG ? '\u751f\u6210\u4e2d\u2026' : '\u751f\u6210\u62db\u547c\u8bed'}</button>
          {plan?.resume?.sections?.length ? (
            <button type="button" onClick={() => window.open(`/api/resume/plan/${jobId}/pdf`, '_blank')} className="rounded-lg px-4 py-2 text-xs text-signal-bright transition hover:bg-signal-blue/10">{'\u9884\u89c8/\u4e0b\u8f7d PDF'}</button>
          ) : null}
        </div>
      )}
      {err && <p className="mt-3 text-xs text-signal-red">{err}</p>}
      {plan?.greeting?.text && (
        <div className="mt-4 rounded-xl bg-bg-card2 p-3" style={{ border: '1px solid rgba(255,255,255,0.06)' }}>
          <p className="mb-1 text-[11px] text-text-3">{'\u62db\u547c\u8bed'}</p>
          <p className="text-sm text-text-1" style={{ whiteSpace: 'pre-wrap' }}>{plan.greeting.text}</p>
        </div>
      )}
      {plan?.resume?.sections?.length ? (
        <div className="mt-4">
          <p className="mb-2 text-[11px] text-text-3">{'\u5b9a\u5236\u7b80\u5386\u65b9\u6848'}{plan.resume.template_used ? `\uff08\u6a21\u677f\uff1a${plan.resume.template_used}\uff09` : ''}</p>
          <div className="space-y-2">
            {plan.resume.sections.map((s, i) => (
              <div key={i} className="rounded-xl bg-bg-card2 p-3" style={{ border: '1px solid rgba(255,255,255,0.06)' }}>
                <div className="flex justify-between text-sm text-text-1"><span className="font-medium">{s.title}</span><span className="text-text-3">{s.time}</span></div>
                <ul className="mt-1 list-disc pl-5 text-xs text-text-2">{s.bullets.map((b, j) => <li key={j}>{b}</li>)}</ul>
              </div>
            ))}
          </div>
        </div>
      ) : null}
    </Card>
  )
}

// -- \u5b9e\u65f6\u9884\u89c8\uff1a\u7531\u5757\u5e93\u5ba2\u6237\u7aef\u6e32\u67d3\u6210\u7b80\u5386 HTML\uff08\u9884\u89c8 iframe \u4e0e\u5bfc\u51fa PDF \u540c\u6e90\uff0c\u907f\u514d\u4e24\u5957\u6392\u7248\u6f02\u79fb\uff09--
import { buildResumeHtml } from '@/lib/resumeHtml'

const PAGE_W = 794          // A4 @96dpi
const PAGE_H = 1123

// Word \u5f0f\u5206\u9875\u9884\u89c8\uff1a\u540c\u4e00\u4efd HTML \u6e32\u67d3 N \u904d\uff0c\u6bcf\u9875\u53ea\u9732\u51fa\u81ea\u5df1\u90a3\u4e00\u6bb5
// \uff08\u8d1f\u504f\u79fb + \u88c1\u5207\uff09\u3002\u5207\u7247\u800c\u975e\u4e00\u6761\u957f\u9875\uff0c\u624d\u80fd\u5982\u5b9e\u770b\u5230\u65ad\u9875\u4f4d\u7f6e\u3002
function A4Preview({ html }: { html: string }) {
  const boxRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(0.6)
  const [pages, setPages] = useState(1)
  const [docH, setDocH] = useState(PAGE_H)

  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const update = () => { const w = el.clientWidth; if (w) setScale(Math.min(1, w / PAGE_W)) }
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const onLoad = (e: React.SyntheticEvent<HTMLIFrameElement>) => {
    const d = e.currentTarget.contentDocument
    if (!d || !d.body) return
    const h = Math.max(PAGE_H, d.body.scrollHeight)
    setDocH(h)
    setPages(Math.max(1, Math.ceil((h - 8) / PAGE_H)))
  }

  return (
    <div ref={boxRef} className="w-full overflow-auto" style={{ maxHeight: 'calc(100vh - 150px)' }}>
      <div className="mx-auto space-y-4" style={{ width: PAGE_W * scale }}>
        {Array.from({ length: pages }).map((_, i) => (
          <div key={i} className="relative overflow-hidden bg-white shadow-card"
            style={{ width: PAGE_W * scale, height: PAGE_H * scale }}>
            <iframe title={`resume-preview-${i}`} srcDoc={html} onLoad={i === 0 ? onLoad : undefined}
              scrolling="no"
              style={{
                width: PAGE_W, height: docH, border: 0, position: 'absolute', left: 0,
                top: -i * PAGE_H * scale,
                transform: `scale(${scale})`, transformOrigin: 'top left', pointerEvents: 'none',
              }} />
            {pages > 1 && (
              <span className="absolute bottom-1 right-2 text-[10px]" style={{ color: '#b8b8b8' }}>
                {i + 1}{' / '}{pages}
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// \u65b0\u5efa\u7b80\u5386\u7684\u9ed8\u8ba4\u540d\uff1a\u65e5\u671f_\u59d3\u540d_\u76ee\u6807\u5c97\u4f4d\uff08\u6ca1\u586b\u76ee\u6807\u5c97\u4f4d\u5c31\u9000\u6210\u300c\u7b80\u5386\u300d\uff09
const PDF_STATE_META: Record<string, { label: string; hint: string; fg: string; bg: string }> = {
  ready: { label: '\u53ef\u53d1\u9001', hint: '\u6709\u5df2\u5bfc\u51fa\u7684 PDF\uff0c\u4e14\u4e0d\u65e7\u4e8e\u7b80\u5386\u5185\u5bb9', fg: '#30d158', bg: 'rgba(48,209,88,0.14)' },
  stale: { label: 'PDF \u8fc7\u671f', hint: '\u7b80\u5386\u6539\u8fc7\u4e4b\u540e\u6ca1\u6709\u91cd\u65b0\u5bfc\u51fa\uff0cm2 \u4f1a\u62d2\u7edd\u4f7f\u7528\u8fd9\u4e00\u4efd', fg: '#ff9f0a', bg: 'rgba(255,159,10,0.16)' },
  missing: { label: '\u672a\u5bfc\u51fa', hint: '\u4ece\u6ca1\u5bfc\u51fa\u8fc7 PDF\uff0c\u591a\u7ad9\u70b9\u6295\u9012\u7528\u4e0d\u4e86\uff08\u540e\u7aef\u4e0d\u80fd\u66ff\u4f60\u6e32\u67d3\uff09', fg: 'rgba(255,255,255,0.45)', bg: 'rgba(255,255,255,0.07)' },
}

/** 「能不能发出去」的小徽章。没有它，简历列表和导出存档是两个互不相干的列表，
 *  人无从知道某一份到底能不能用——那正是 m2 传出一份过期 PDF 而无人察觉的原因。 */
function PdfStatePill({ state, exportedAt }: { state?: string; exportedAt?: string }) {
  const meta = PDF_STATE_META[state || 'missing'] ?? PDF_STATE_META.missing
  return (
    <span
      className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium"
      style={{ background: meta.bg, color: meta.fg }}
      title={exportedAt ? `${meta.hint}\uff1b\u5bfc\u51fa\u4e8e ${exportedAt}` : meta.hint}
    >
      {meta.label}
    </span>
  )
}

export function defaultResumeName(person: string, target: string): string {
  const d = new Date()
  const ymd = `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, '0')}${String(d.getDate()).padStart(2, '0')}`
  return [ymd, person.trim(), target.trim() || '\u7b80\u5386'].filter(Boolean).join('_')
}

type StyleField = 'title' | 'time' | 'bullets'
type StyleMark = 'bold' | 'italic' | 'underline'
const STYLE_FIELDS: Array<{ key: StyleField; label: string }> = [
  { key: 'title', label: '\u6807\u9898' },
  { key: 'time', label: '\u65f6\u95f4' },
  { key: 'bullets', label: '\u8981\u70b9' },
]
const STYLE_MARKS: Array<{ mark: StyleMark; glyph: string; title: string }> = [
  { mark: 'bold', glyph: 'B', title: '\u52a0\u7c97' },
  { mark: 'italic', glyph: 'I', title: '\u659c\u4f53' },
  { mark: 'underline', glyph: 'U', title: '\u4e0b\u5212\u7ebf' },
]
function toggleMark(style: ResumeBlock['style'], field: StyleField, mark: StyleMark): ResumeBlock['style'] {
  const next = { ...(style || {}) }
  const cur = { ...(next[field] || {}) }
  if (cur[mark]) delete cur[mark]
  else cur[mark] = true
  if (Object.keys(cur).length) next[field] = cur
  else delete next[field]
  return next
}

// \u5b57\u6bb5\u65c1\u7684\u5185\u8054 B/I/U\uff08\u6bd4\u5355\u72ec\u4e00\u6761\u5de5\u5177\u680f\u66f4\u76f4\u63a5\uff1a\u6539\u54ea\u4e2a\u6846\u5c31\u70b9\u65c1\u8fb9\u90a3\u7ec4\uff09
function MarkButtons({ marks, onToggle }: {
  marks?: FieldMarks
  onToggle: (m: StyleMark) => void
}) {
  return (
    <span className="flex shrink-0 items-center gap-0.5">
      {STYLE_MARKS.map(({ mark, glyph, title }) => {
        const on = !!marks?.[mark]
        return (
          <button key={mark} type="button" title={title} onClick={() => onToggle(mark)}
            className="h-7 w-7 rounded-md text-[12px] leading-none transition"
            style={{
              background: on ? 'rgba(10,132,255,0.2)' : 'rgba(255,255,255,0.05)',
              color: on ? '#4aa3ff' : 'rgba(255,255,255,0.45)',
              border: on ? '1px solid rgba(10,132,255,0.5)' : '1px solid rgba(255,255,255,0.08)',
              fontWeight: mark === 'bold' ? 700 : 400,
              fontStyle: mark === 'italic' ? 'italic' : 'normal',
              textDecoration: mark === 'underline' ? 'underline' : 'none',
            }}>{glyph}</button>
        )
      })}
    </span>
  )
}

type Owner = 'pool' | 'resume'
type DragItem =
  | { kind: 'block'; owner: Owner; si: number; bi: number }
  | { kind: 'section'; owner: Owner; si: number }
let dragItem: DragItem | null = null

// \u2500\u2500 \u5171\u7528\u5206\u533a\u7f16\u8f91\u5668\uff08\u4fe1\u606f\u6c60\u4e0e\u5f53\u524d\u7b80\u5386\u540c\u6784\uff1a\u540c\u4e00\u5c55\u793a\u3001\u540c\u4e00\u4ea4\u4e92\uff09\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
export function SectionEditor({ doc, onChange, owner, summaryHint, onExternalDrop, onQuickAdd, onQuickAddSection, compact, showStyle }: {
  doc: ResumeBlocks
  onChange: (next: ResumeBlocks) => void
  owner: Owner
  summaryHint: string
  onExternalDrop?: (item: DragItem, target: { si: number | null; slot: number }) => void   // \u6536\u4e0b\u6765\u81ea\u53e6\u4e00\u5217\u7684\u5757/\u5206\u533a
  onQuickAdd?: (si: number, bi: number) => void                            // \u6c60 \u2192 \u7b80\u5386 \u5355\u6761\u5feb\u6377\u590d\u5236
  onQuickAddSection?: (si: number) => void                                 // \u6c60 \u2192 \u7b80\u5386 \u6574\u5206\u533a\u590d\u5236
  compact?: boolean
  showStyle?: boolean          // \u5b57\u6bb5\u7ea7 \u7c97/\u659c/\u4e0b\u5212\u7ebf \u5f00\u5173\uff08\u53ea\u5728\u300c\u5f53\u524d\u7b80\u5386\u300d\u5217\u7528\uff0c\u4fe1\u606f\u6c60\u4e0d\u6392\u7248\uff09
}) {
  const [open, setOpen] = useState<string | null>(null)
  const [, force] = useState(0)
  const [blkSlot, setBlkSlot] = useState<{ si: number; slot: number } | null>(null)
  const [secSlot, setSecSlot] = useState<number | null>(null)
  const [hot, setHot] = useState(false)   // \u5916\u6765\u62d6\u62fd\u60ac\u505c\u9ad8\u4eae

  const sections = doc.sections || []
  const setSections = (next: ResumeSection[]) => onChange({ ...doc, sections: next })
  const patchSection = (si: number, patch: Partial<ResumeSection>) =>
    setSections(sections.map((s, i) => (i === si ? { ...s, ...patch } : s)))
  const addSection = (name: string) => setSections([...sections, { name, blocks: [] }])
  const removeSection = (si: number) => {
    if (!window.confirm(`\u5220\u9664\u5206\u533a\u300c${sections[si].name}\u300d\u53ca\u5176\u4e2d ${sections[si].blocks.length} \u6761\u5185\u5bb9\uff1f`)) return
    setSections(sections.filter((_, i) => i !== si)); setOpen(null)
  }
  const addBlock = (si: number) => {
    patchSection(si, { blocks: [...sections[si].blocks, emptyBlock()] })
    setOpen(`${si}:${sections[si].blocks.length}`)
  }
  const updateBlock = (si: number, bi: number, patch: Partial<ResumeBlock>) =>
    patchSection(si, { blocks: sections[si].blocks.map((b, j) => (j === bi ? { ...b, ...patch } : b)) })
  const removeBlock = (si: number, bi: number) => {
    patchSection(si, { blocks: sections[si].blocks.filter((_, j) => j !== bi) }); setOpen(null)
  }
  const moveBlock = (si: number, bi: number, dir: -1 | 1) => {
    const list = [...sections[si].blocks]
    const j = bi + dir
    if (j < 0 || j >= list.length) return
    const t = list[bi]; list[bi] = list[j]; list[j] = t
    patchSection(si, { blocks: list }); setOpen(`${si}:${j}`)
  }

  const mine = (it: DragItem | null) => !!it && it.owner === owner
  const foreign = (it: DragItem | null) => !!it && it.owner !== owner && !!onExternalDrop
  // \u6d4f\u89c8\u5668\u53ea\u628a\u300cdragenter \u4e0e dragover \u90fd\u88ab preventDefault\u300d\u7684\u5143\u7d20\u5f53\u4f5c\u6709\u6548\u653e\u7f6e\u76ee\u6807\uff1b
  // \u5c11\u4e86 dragenter\uff0cdrop \u6839\u672c\u4e0d\u4f1a\u89e6\u53d1\uff08\u62d6\u8fc7\u53bb\u6beb\u65e0\u53cd\u5e94\uff09\u3002
  const acceptEnter = (e: React.DragEvent) => {
    if (mine(dragItem) || foreign(dragItem)) { e.preventDefault(); e.dataTransfer.dropEffect = foreign(dragItem) ? 'copy' : 'move' }
  }

  // \u5757\u62d6\u62fd\uff1a\u672c\u5217\u5185\u79fb\u52a8\uff08\u53ef\u8de8\u5206\u533a\uff09\uff1b\u5916\u6765\u5219\u4ea4\u7ed9 onExternalDrop \u590d\u5236
  const blkDragStart = (si: number, bi: number) => (e: React.DragEvent) => {
    dragItem = { kind: 'block', owner, si, bi }
    e.dataTransfer.effectAllowed = owner === 'pool' ? 'copy' : 'move'
    e.dataTransfer.setData('text/plain', 'blk')
    window.requestAnimationFrame(() => { force((n) => n + 1); setOpen(null) })
  }
  const blkDragOver = (si: number, bi: number) => (e: React.DragEvent) => {
    const it = dragItem
    if (!it || it.kind !== 'block') return
    if (!mine(it) && !foreign(it)) return
    e.preventDefault()
    e.dataTransfer.dropEffect = foreign(it) ? 'copy' : 'move'
    const r = e.currentTarget.getBoundingClientRect()
    let slot = e.clientY < r.top + r.height / 2 ? bi : bi + 1
    if (mine(it) && it.si === si) {            // \u540c\u5206\u533a\u91cd\u6392\uff1a\u6d88\u9664\u76f8\u90bb\u6b7b\u533a
      if (bi === it.bi) { setBlkSlot(null); return }
      if (slot === it.bi + 1 && bi === it.bi + 1) slot = bi + 1
      else if (slot === it.bi && bi === it.bi - 1) slot = bi
    }
    setBlkSlot({ si, slot })
  }
  const blkDrop = (si: number) => (e: React.DragEvent) => {
    e.preventDefault(); e.stopPropagation()
    const it = dragItem
    const s = blkSlot
    const slot = s?.si === si ? s.slot : sections[si].blocks.length
    clearDrag()
    if (!it || it.kind !== 'block') return
    if (foreign(it)) { onExternalDrop!(it, { si, slot }); return }
    if (!mine(it)) return
    const next = sections.map((sec) => ({ ...sec, blocks: [...sec.blocks] }))
    const [moved] = next[it.si].blocks.splice(it.bi, 1)
    let to = slot
    if (it.si === si && it.bi < to) to -= 1
    next[si].blocks.splice(to, 0, moved)
    setSections(next)
  }

  // \u5206\u533a\u62d6\u62fd\uff1a\u672c\u5217\u5185\u91cd\u6392\uff1b\u5916\u6765\u5206\u533a\uff08\u6c60\u2192\u7b80\u5386\uff09\u6574\u5757\u590d\u5236
  const secDragStart = (si: number) => (e: React.DragEvent) => {
    dragItem = { kind: 'section', owner, si }
    e.dataTransfer.effectAllowed = owner === 'pool' ? 'copy' : 'move'
    e.dataTransfer.setData('text/plain', 'sec')
    window.requestAnimationFrame(() => { force((n) => n + 1); setOpen(null) })
  }
  const secDragOver = (si: number) => (e: React.DragEvent) => {
    const it = dragItem
    if (!it || it.kind !== 'section') return
    if (!mine(it) && !foreign(it)) return
    e.preventDefault()
    e.dataTransfer.dropEffect = foreign(it) ? 'copy' : 'move'
    const r = e.currentTarget.getBoundingClientRect()
    let slot = e.clientY < r.top + r.height / 2 ? si : si + 1
    if (mine(it)) {
      if (si === it.si) { setSecSlot(null); return }
      if (slot === it.si + 1 && si === it.si + 1) slot = si + 1
      else if (slot === it.si && si === it.si - 1) slot = si
    }
    setSecSlot(slot)
  }
  const secDrop = (e: React.DragEvent) => {
    e.preventDefault()
    const it = dragItem
    const slot = secSlot
    clearDrag()
    if (!it || it.kind !== 'section') return
    if (foreign(it)) { onExternalDrop!(it, { si: null, slot: slot ?? sections.length }); return }
    if (!mine(it) || slot === null) return
    let to = slot
    if (it.si < to) to -= 1
    if (to === it.si) return
    const list = [...sections]
    const [m] = list.splice(it.si, 1)
    list.splice(to, 0, m)
    setSections(list)
  }
  const clearDrag = () => { dragItem = null; setBlkSlot(null); setSecSlot(null); setHot(false); force((n) => n + 1) }

  // \u6574\u5217\u515c\u5e95\u843d\u533a\uff1a\u5916\u6765\u5185\u5bb9\u62d6\u5230\u7a7a\u767d\u5904 \u2192 \u8ffd\u52a0\u5230\u672b\u5c3e
  const columnDragOver = (e: React.DragEvent) => {
    if (!foreign(dragItem)) return
    e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; setHot(true)
  }
  const columnDrop = (e: React.DragEvent) => {
    if (!foreign(dragItem)) return
    e.preventDefault()
    const it = dragItem
    clearDrag()
    if (it) onExternalDrop!(it, { si: null, slot: sections.length })
  }

  const detailInput = 'w-full rounded-lg bg-bg-card px-3 py-2 text-sm text-text-1 focus:outline-none focus:ring-1 focus:ring-signal-blue'
  const draggingBlock = (it: DragItem | null, si: number, bi: number) =>
    !!it && it.owner === owner && it.kind === 'block' && it.si === si && it.bi === bi
  const draggingSection = (it: DragItem | null, si: number) =>
    !!it && it.owner === owner && it.kind === 'section' && it.si === si

  return (
    <div onDragEnter={acceptEnter} onDragOver={columnDragOver} onDragLeave={() => setHot(false)} onDrop={columnDrop}
      className="rounded-xl transition"
      style={{ outline: hot ? '2px dashed rgba(10,132,255,0.5)' : '2px dashed transparent', outlineOffset: 4 }}>
      <div className="space-y-4" onDrop={secDrop}>
        {sections.length === 0 && (
          <div className="rounded-xl px-3 py-6 text-center text-[11px] leading-relaxed text-text-3"
            style={{ border: '1px dashed rgba(255,255,255,0.14)' }}>
            {onExternalDrop ? '\u4ece\u5de6\u4fa7\u4fe1\u606f\u6c60\u62d6\u5185\u5bb9\u8fc7\u6765\uff0c\u6216\u70b9\u6761\u76ee\u4e0a\u7684 \u2192 \u6309\u94ae' : '\u8fd8\u6ca1\u6709\u5206\u533a\uff0c\u7528\u4e0b\u65b9\u6309\u94ae\u6dfb\u52a0'}
          </div>
        )}
        {sections.map((sec, si) => {
          const isLastSec = si === sections.length - 1
          return (
            <div key={si} onDragEnter={acceptEnter} onDragOver={secDragOver(si)}
              style={{
                opacity: draggingSection(dragItem, si) ? 0.35 : 1,
                borderTop: secSlot === si ? '2px solid #0a84ff' : '2px solid transparent',
                borderBottom: isLastSec && secSlot === sections.length ? '2px solid #0a84ff' : '2px solid transparent',
                transition: 'opacity .15s',
              }}>
              <div className="mb-2 flex items-center gap-1.5 rounded-lg py-0.5 pl-0.5"
                style={{ borderLeft: '3px solid rgba(10,132,255,0.55)' }}>
                <div draggable title={'\u6309\u4f4f\u62d6\u52a8\u6574\u4e2a\u5206\u533a'} onDragStart={secDragStart(si)} onDragEnd={clearDrag}
                  className="group flex shrink-0 cursor-grab select-none items-center rounded px-1.5 py-1.5 transition hover:bg-bg-card2 active:cursor-grabbing">
                  <span className="text-[15px] leading-none text-text-2 opacity-70 transition group-hover:opacity-100">{'\u283f'}</span>
                </div>
                <input value={sec.name} onChange={(e) => patchSection(si, { name: e.target.value })}
                  className="min-w-0 flex-1 rounded-lg bg-transparent px-1.5 py-1 text-[15px] font-bold tracking-wide text-text-1 transition hover:bg-bg-card2 focus:bg-bg-card2 focus:outline-none focus:ring-1 focus:ring-signal-blue"
                  placeholder={'\u5206\u533a\u540d'} />
                <span className="shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium text-text-3" style={{ background: 'rgba(255,255,255,0.06)' }}>{sec.blocks.length}</span>
                {onQuickAddSection && sec.blocks.length > 0 && (
                  <button type="button" title={'\u6574\u4e2a\u5206\u533a\u52a0\u5165\u5f53\u524d\u7b80\u5386'} onClick={() => onQuickAddSection(si)}
                    className="shrink-0 rounded-md px-2 py-1 text-[12px] font-medium text-signal-bright transition hover:bg-signal-blue/15">{'\u21d2 \u5168\u90e8'}</button>
                )}
                <button type="button" title={'\u65b0\u589e\u4e00\u6761'} onClick={() => addBlock(si)}
                  className="shrink-0 rounded-md px-2 py-1 text-[12px] font-medium text-text-2 transition hover:bg-bg-card2 hover:text-text-1">{'+ \u65b0\u589e'}</button>
                <button type="button" title={'\u5220\u9664\u5206\u533a'} onClick={() => removeSection(si)}
                  className="shrink-0 rounded-md px-1.5 py-1 text-[12px] text-text-3 transition hover:bg-signal-red/10 hover:text-signal-red">{'\u2715'}</button>
              </div>

              {sec.blocks.length === 0 ? (
                <div className="ml-2 pl-2.5" style={{ borderLeft: '1px solid rgba(255,255,255,0.08)' }} onDrop={blkDrop(si)} onDragEnter={acceptEnter} onDragOver={(e) => { if (foreign(dragItem) || mine(dragItem)) { e.preventDefault(); e.dataTransfer.dropEffect = foreign(dragItem) ? 'copy' : 'move'; setBlkSlot({ si, slot: 0 }) } }}>
                  <button type="button" onClick={() => addBlock(si)}
                    className="w-full rounded-[10px] py-2 text-[11px] text-text-3 transition hover:text-text-1"
                    style={{ border: blkSlot?.si === si ? '1px solid #0a84ff' : '1px dashed rgba(255,255,255,0.14)' }}>{'\u7a7a\u5206\u533a \u00b7 \u70b9\u51fb\u6dfb\u52a0'}</button>
                </div>
              ) : (
                <div className="ml-2 space-y-1.5 pl-2.5" style={{ borderLeft: '1px solid rgba(255,255,255,0.08)' }} onDrop={blkDrop(si)}>
                  {sec.blocks.map((blk, bi) => {
                    const k = `${si}:${bi}`
                    const isOpen = open === k
                    const isLast = bi === sec.blocks.length - 1
                    const slotHere = blkSlot?.si === si
                    return (
                      <div key={k} onDragEnter={acceptEnter} onDragOver={blkDragOver(si, bi)}
                        style={{
                          borderTop: slotHere && blkSlot?.slot === bi ? '2px solid #0a84ff' : '2px solid transparent',
                          borderBottom: isLast && slotHere && blkSlot?.slot === sec.blocks.length ? '2px solid #0a84ff' : '2px solid transparent',
                        }}>
                        <div className="overflow-hidden rounded-[10px] transition"
                          style={{
                            background: isOpen ? 'rgba(255,255,255,0.055)' : 'rgba(255,255,255,0.035)',
                            border: isOpen ? '1px solid rgba(10,132,255,0.4)' : '1px solid rgba(255,255,255,0.07)',
                            opacity: draggingBlock(dragItem, si, bi) ? 0.35 : 1,
                          }}>
                          <div draggable={!isOpen} onDragStart={blkDragStart(si, bi)} onDragEnd={clearDrag}
                            onClick={() => setOpen(isOpen ? null : k)}
                            className={`group flex select-none items-center gap-1.5 py-2 pl-1.5 pr-2.5 ${isOpen ? 'cursor-pointer' : 'cursor-grab active:cursor-grabbing'}`}>
                            <span className="rounded px-1 py-0.5 text-[14px] leading-none text-text-3 opacity-55 transition group-hover:bg-bg-card2 group-hover:opacity-100">{'\u283f'}</span>
                            <span className={`min-w-0 flex-1 truncate text-[13px] ${blk.title ? 'font-medium text-text-1' : 'text-text-3'}`}>
                              {blk.title || '\u672a\u547d\u540d\u6761\u76ee'}</span>
                            {blk.time && <span className="shrink-0 text-[11px] text-text-3" style={{ fontVariantNumeric: 'tabular-nums' }}>{blk.time}</span>}
                            {onQuickAdd && (
                              <button type="button" title={'\u52a0\u5165\u5f53\u524d\u7b80\u5386'}
                                onClick={(e) => { e.stopPropagation(); onQuickAdd(si, bi) }}
                                className="shrink-0 rounded px-1 text-[11px] text-signal-bright opacity-0 transition group-hover:opacity-100 hover:bg-signal-blue/10">{'\u2192'}</button>
                            )}
                            <span className="shrink-0 text-[11px] text-text-3 transition" style={{ transform: isOpen ? 'rotate(180deg)' : 'none' }}>{'\u25be'}</span>
                          </div>
                          <div style={{ display: 'grid', gridTemplateRows: isOpen ? '1fr' : '0fr', transition: 'grid-template-rows .28s ease' }}>
                            <div className="min-h-0 overflow-hidden">
                              <div className="space-y-2 px-2.5 pb-2.5 pt-1">
                                <div className="flex items-center gap-1.5">
                                  <input className={detailInput} style={inputStyle} placeholder={'\u6807\u9898'}
                                    value={blk.title} onChange={(e) => updateBlock(si, bi, { title: e.target.value })} />
                                  {showStyle && <MarkButtons marks={blk.style?.title}
                                    onToggle={(m) => updateBlock(si, bi, { style: toggleMark(blk.style, 'title', m) })} />}
                                </div>
                                <div className="flex items-center gap-1.5">
                                  <input className="w-32 shrink-0 rounded-lg bg-bg-card px-2 py-2 text-sm text-text-1 focus:outline-none" style={inputStyle}
                                    placeholder={'\u65f6\u95f4'} value={blk.time} onChange={(e) => updateBlock(si, bi, { time: e.target.value })} />
                                  {showStyle && <MarkButtons marks={blk.style?.time}
                                    onToggle={(m) => updateBlock(si, bi, { style: toggleMark(blk.style, 'time', m) })} />}
                                </div>
                                <div className="flex items-start gap-1.5">
                                  <textarea className={`${detailInput} leading-relaxed`} style={{ ...inputStyle, minHeight: compact ? 96 : 120 }}
                                    placeholder={'\u8981\u70b9\uff0c\u6bcf\u884c\u4e00\u6761'} value={blk.bullets.join('\n')}
                                    onChange={(e) => updateBlock(si, bi, { bullets: e.target.value.split('\n') })} />
                                  {showStyle && (
                                    <span className="flex flex-col gap-0.5">
                                      <MarkButtons marks={blk.style?.bullets}
                                        onToggle={(m) => updateBlock(si, bi, { style: toggleMark(blk.style, 'bullets', m) })} />
                                    </span>
                                  )}
                                </div>
                                <input className="w-full rounded bg-bg-card px-2.5 py-2 text-[12px] text-text-2 focus:outline-none" style={inputStyle}
                                  placeholder={summaryHint} value={blk.summary}
                                  onChange={(e) => updateBlock(si, bi, { summary: e.target.value })} />
                                <div className="flex items-center gap-1">
                                  <button type="button" onClick={() => moveBlock(si, bi, -1)} disabled={bi === 0}
                                    className="rounded px-2 py-1 text-[12px] text-text-3 transition hover:bg-bg-card2 hover:text-text-1 disabled:opacity-30">{'\u2191'}</button>
                                  <button type="button" onClick={() => moveBlock(si, bi, 1)} disabled={bi === sec.blocks.length - 1}
                                    className="rounded px-1.5 py-1 text-[11px] text-text-3 transition hover:text-text-1 disabled:opacity-30">{'\u2193'}</button>
                                  <button type="button" onClick={() => removeBlock(si, bi)}
                                    className="ml-auto rounded px-2 py-1 text-[12px] text-signal-red transition hover:bg-signal-red/10">{'\u5220\u9664'}</button>
                                </div>
                              </div>
                            </div>
                          </div>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          )
        })}

        <div className="flex flex-wrap items-center gap-1 border-t pt-2.5" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
          <span className="mr-1 text-[11px] text-text-3">{'\u52a0\u5206\u533a'}</span>
          {SECTION_PRESETS.filter((p) => !sections.some((s) => s.name === p)).map((p) => (
            <button key={p} type="button" onClick={() => addSection(p)}
              className="rounded-md px-2 py-1 text-[11px] text-text-2 transition hover:bg-bg-card2 hover:text-text-1"
              style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.08)' }}>{p}</button>
          ))}
          <button type="button" onClick={() => addSection('\u65b0\u5206\u533a')}
            className="rounded-md px-2 py-1 text-[11px] font-medium text-signal-bright transition hover:bg-signal-blue/15">{'+ \u81ea\u5b9a\u4e49'}</button>
        </div>
      </div>
    </div>
  )
}

function BasicInfoCard({ doc, onChange, dev }: { doc: ResumeBlocks; onChange: (d: ResumeBlocks) => void; dev: string }) {
  return (
    <Card title={'\u57fa\u672c\u4fe1\u606f'} dev={dev}>
      <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
        {BASIC_FIELDS.map(({ key, label }) => (
          <label key={key} className="flex flex-col gap-1">
            <span className="text-[11px] text-text-3">{label}</span>
            <input className={inputCls} style={inputStyle} value={doc.basic_info[key] ?? ''}
              onChange={(e) => onChange({ ...doc, basic_info: { ...doc.basic_info, [key]: e.target.value } })} />
          </label>
        ))}
      </div>
    </Card>
  )
}

// \u2500\u2500 \u5206\u9875 1\uff1a\u7b80\u5386\u5de5\u4f5c\u53f0\uff08\u4fe1\u606f\u6c60 | \u5f53\u524d\u7b80\u5386 | \u9884\u89c8\uff09\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
function Workbench({ onErr, pool, setPool, doc, setDoc, poolDirty, docDirty, activeName, savePool, saveDoc, reloadPool, onActiveChanged }: {
  onErr: (m: string | null) => void
  pool: ResumeBlocks
  setPool: (p: ResumeBlocks) => void
  doc: ResumeBlocks
  setDoc: (d: ResumeBlocks) => void
  poolDirty: boolean
  docDirty: boolean
  activeName: string
  savePool: () => Promise<void>
  saveDoc: () => Promise<void>
  reloadPool: () => Promise<void>
  onActiveChanged: () => Promise<void>
}) {
  const [savingPool, setSavingPool] = useState(false)
  const [savingDoc, setSavingDoc] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [savingAs, setSavingAs] = useState(false)
  const [newName, setNewName] = useState('')
  const [newTarget, setNewTarget] = useState('')
  const [nameTouched, setNameTouched] = useState(false)   // \u7528\u6237\u6539\u8fc7\u540d\u5b57\u5c31\u522b\u518d\u81ea\u52a8\u8986\u76d6
  const [snaps, setSnaps] = useState<PoolSnapshot[]>([])
  const [snapCur, setSnapCur] = useState<PoolCurrent | null>(null)
  const [showSnaps, setShowSnaps] = useState(false)
  const [buildNote, setBuildNote] = useState<string | null>(null)
  // \u6539\u52a8\u5b83\u5c31\u91cd\u5efa PoolDiffPanel\uff0c\u8ba9\u5b83\u91cd\u65b0\u62c9\u5f85\u786e\u8ba4\u63d0\u6848\u3002
  const [pendingKey, setPendingKey] = useState(0)
  const fileRef = useRef<HTMLInputElement>(null)

  const html = useMemo(() => buildResumeHtml(doc), [doc])
  const loadSnaps = () => { void API.getPoolSnapshots().then((r) => { setSnaps(r.snapshots); setSnapCur(r.current) }).catch(() => {}) }

  // \u6c60 \u2192 \u7b80\u5386\uff1a\u590d\u5236\u5757\uff0c\u843d\u5230\u540c\u540d\u5206\u533a\uff08\u6ca1\u6709\u5c31\u6309\u6c60\u91cc\u7684\u5206\u533a\u540d\u65b0\u5efa\uff09
  const copyBlockToResume = (poolSi: number, poolBi: number, target?: { si: number | null; slot: number }) => {
    const src = pool.sections[poolSi]
    const blk = src?.blocks[poolBi]
    if (!blk) return
    const sections = doc.sections.map((x) => ({ ...x, blocks: [...x.blocks] }))
    let si = target && target.si !== null ? target.si : sections.findIndex((x) => x.name === src.name)
    if (si < 0 || si >= sections.length) {
      sections.push({ name: src.name, blocks: [] })
      si = sections.length - 1
    }
    if (sections[si].blocks.some((b) => b.title === blk.title && b.time === blk.time)) return
    const slot = target && target.si !== null ? Math.min(target.slot, sections[si].blocks.length) : sections[si].blocks.length
    sections[si].blocks.splice(slot, 0, { ...blk, bullets: [...blk.bullets] })
    setDoc({ ...doc, sections })
  }
  const copySectionToResume = (poolSi: number, slot?: number) => {
    const src = pool.sections[poolSi]
    if (!src) return
    const sections = doc.sections.map((x) => ({ ...x, blocks: [...x.blocks] }))
    const existing = sections.findIndex((x) => x.name === src.name)
    const clone = src.blocks.map((b) => ({ ...b, bullets: [...b.bullets] }))
    if (existing >= 0) {
      const have = new Set(sections[existing].blocks.map((b) => `${b.title}|${b.time}`))
      sections[existing].blocks.push(...clone.filter((b) => !have.has(`${b.title}|${b.time}`)))
    } else {
      sections.splice(slot ?? sections.length, 0, { name: src.name, blocks: clone })
    }
    setDoc({ ...doc, sections })
  }
  const onResumeExternalDrop = (it: DragItem, target: { si: number | null; slot: number }) => {
    if (it.owner !== 'pool') return
    if (it.kind === 'block') copyBlockToResume(it.si, it.bi, target)
    else copySectionToResume(it.si, target.si === null ? target.slot : undefined)
  }

  const doSavePool = async () => {
    setSavingPool(true); onErr(null)
    try { await savePool() } catch (e) { onErr((e as Error).message) } finally { setSavingPool(false) }
  }
  const doSaveDoc = async () => {
    setSavingDoc(true); onErr(null)
    try { await saveDoc() } catch (e) { onErr((e as Error).message) } finally { setSavingDoc(false) }
  }
  const exportPdf = async () => {
    setExporting(true); onErr(null)
    try {
      if (docDirty) await saveDoc()
      const label = [doc.basic_info.name, activeName].filter(Boolean).join('_') || 'resume'
      const blob = await API.printResumePdf(buildResumeHtml(doc), label)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `${label}.pdf`
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
    } catch (e) { onErr((e as Error).message) } finally { setExporting(false) }
  }
  const upload = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    if (poolDirty && !window.confirm('\u4fe1\u606f\u6c60\u6709\u672a\u4fdd\u5b58\u7684\u4fee\u6539\uff0c\u4e0a\u4f20\u89e3\u6790\u540e\u4f1a\u4ee5\u670d\u52a1\u5668\u4e0a\u7684\u5185\u5bb9\u4e3a\u51c6\u3002\u8981\u5148\u653e\u5f03\u8fd9\u4e9b\u4fee\u6539\u5417\uff1f')) {
      if (fileRef.current) fileRef.current.value = ''
      return
    }
    setUploading(true); onErr(null)
    // \u4e0a\u4f20\u89e3\u6790\u4e0d\u518d\u76f4\u63a5\u5165\u6c60\uff0c\u800c\u662f\u4ea7\u51fa\u4e00\u4efd\u5f85\u786e\u8ba4\u63d0\u6848\uff08\u89c1 services/pool_diff.py\uff09\u3002
    // \u6240\u4ee5\u8fd9\u91cc\u4e0d\u91cd\u62c9\u6c60\uff08\u5b83\u8fd8\u6ca1\u53d8\uff09\uff0c\u800c\u662f\u53eb\u63d0\u6848\u9762\u677f\u91cd\u65b0\u53d6\u6570\u3002
    try { await API.uploadResume(file); setPendingKey((n) => n + 1) }
    catch (e2) { onErr((e2 as Error).message) }
    finally { setUploading(false); if (fileRef.current) fileRef.current.value = '' }
  }
  const restoreSnap = async (fname: string) => {
    if (!window.confirm(CONFIRM_RESTORE)) return
    onErr(null)
    try { await API.restorePoolSnapshot(fname); await reloadPool(); setShowSnaps(false); setBuildNote(null); loadSnaps() }
    catch (e) { onErr((e as Error).message) }
  }

  // \u628a\u5f53\u524d\u6b63\u5728\u7f16\u8f91\u7684\u8fd9\u4e00\u7248\u5b58\u6210\u4e00\u4efd\u65b0\u7684\u300c\u5df2\u4fdd\u5b58\u7b80\u5386\u300d\uff08\u76f8\u5f53\u4e8e\u53e6\u5b58\u4e3a\uff0c\u4e4b\u540e\u7f16\u8f91\u65b0\u7684\u90a3\u4efd\uff09
  const saveAsNew = async () => {
    const person = doc.basic_info.name || ''
    const name = (newName.trim() || defaultResumeName(person, newTarget))
    setSavingAs(true); onErr(null)
    try {
      await saveDoc()                                  // \u5148\u628a\u5f53\u524d\u7f16\u8f91\u843d\u5230\u6fc0\u6d3b\u4efd\uff0c\u65b0\u5efa\u624d\u590d\u5236\u5f97\u5230\u6700\u65b0\u5185\u5bb9
      const item = await API.createResume(name, newTarget.trim(), true)
      await API.activateResume(item.slug)
      await onActiveChanged()
      setNewName(''); setNewTarget(''); setNameTouched(false)
    } catch (e) { onErr((e as Error).message) } finally { setSavingAs(false) }
  }

  const poolCount = pool.sections.reduce((n, x) => n + x.blocks.length, 0)
  const docCount = doc.sections.reduce((n, x) => n + x.blocks.length, 0)
  const colHead = 'mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-text-3'
  const saveBtn = 'rounded-lg px-4 py-1.5 text-[13px] font-semibold transition disabled:cursor-default'
  const esc_saving = '\u4fdd\u5b58\u4e2d\u2026'
  const esc_save = '\u4fdd\u5b58'
  const esc_saved = '\u2713 \u5df2\u4fdd\u5b58'
  const CONFIRM_BUILD = '\u7528 LLM \u628a\u81ea\u6211\u63cf\u8ff0\u878d\u8fdb\u4fe1\u606f\u6c60\uff08\u4f1a\u91cd\u65b0\u6574\u7406\u5206\u533a\uff09\u3002\u6574\u7406\u524d\u4f1a\u81ea\u52a8\u7559\u4e00\u4efd\u5feb\u7167\uff0c\u53ef\u56de\u6eda\u3002\u7ee7\u7eed\uff1f'
  const CONFIRM_RESTORE = '\u56de\u6eda\u5230\u8fd9\u4e2a\u7248\u672c\uff1f\u5f53\u524d\u5185\u5bb9\u4f1a\u5148\u81ea\u52a8\u7559\u4e00\u4efd\u5feb\u7167\u3002'
  const NOTE_SHRINK_A = '\u26a0 \u6574\u7406\u540e\u6761\u76ee\u53d8\u5c11\u4e86\uff08'
  const NOTE_SHRINK_B = ' \u6761\uff09\u3002\u8bf7\u6838\u5bf9\u4e0b\u65b9\u5185\u5bb9\uff1b\u4e0d\u5bf9\u5c31\u70b9\u300c\u5386\u53f2\u7248\u672c\u300d\u56de\u6eda\uff0c\u6216\u8005\u76f4\u63a5\u4e0d\u4fdd\u5b58\uff08\u672a\u70b9\u4fdd\u5b58\u4e0d\u4f1a\u5199\u76d8\uff09\u3002'
  const NOTE_OK_A = '\u6574\u7406\u5b8c\u6210\uff08'
  const NOTE_OK_B = ' \u6761\uff09\u3002\u6838\u5bf9\u65e0\u8bef\u540e\u8bb0\u5f97\u4fdd\u5b58\u3002'
  const LABEL_HISTORY = '\u5386\u53f2\u7248\u672c'
  const HINT_HISTORY = '\u6bcf\u6b21\u4fdd\u5b58\u524d\u81ea\u52a8\u7559\u6863\u3002\u4fdd\u7559\u6700\u8fd1 10 \u4e2a\u7248\u672c\uff0c\u5916\u52a0\u6700\u8fd1 14 \u5929\u91cc\u6bcf\u5929\u6700\u65e9\u7684\u90a3\u4e2a\uff08\u7eff\u6807\u300c\u6bcf\u65e5\u300d\uff09\u2014\u2014\u4e00\u5929\u5185\u53cd\u590d\u4fdd\u5b58\u4e0d\u4f1a\u628a\u524d\u51e0\u5929\u7684\u5b8c\u597d\u7248\u672c\u6324\u6389\u3002\u7eff\u706f = \u5f53\u524d\u6b63\u5728\u7528\u7684\u90a3\u4e00\u7248\u3002'
  const LABEL_DAILY = '\u6bcf\u65e5'
  const LABEL_DAILY_TIP = '\u5f53\u5929\u6700\u65e9\u7684\u5b58\u6863\uff0c\u4e0d\u4f1a\u88ab\u540e\u7eed\u4fdd\u5b58\u6324\u6389'
  const HINT_NO_HISTORY = '\u8fd8\u6ca1\u6709\u5386\u53f2\u7248\u672c\uff1b\u4fdd\u5b58\u4e00\u6b21\u4fe1\u606f\u6c60\u540e\u5c31\u4f1a\u6709\u4e86\u3002'
  const LABEL_SEC = ' \u5206\u533a \u00b7 '
  const LABEL_BLK = ' \u6761'
  const LABEL_RESTORE = '\u56de\u6eda'
  const LABEL_CURRENT = '\u5f53\u524d\u7248\u672c\uff08\u6b63\u5728\u4f7f\u7528\uff09'
  const LABEL_IN_USE = '\u4f7f\u7528\u4e2d'
  const LABEL_SAME_TIP = '\u8fd9\u4e00\u7248\u5c31\u662f\u5f53\u524d\u6b63\u5728\u7528\u7684\u5185\u5bb9'
  const dirtyDot = <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: '#f5a623' }} />

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input ref={fileRef} type="file" accept=".pdf,.docx" onChange={upload} disabled={uploading} className="hidden" id="wb-upload" />
        <label htmlFor="wb-upload"
          className={`cursor-pointer rounded-full px-4 py-2 text-sm text-text-1 transition ${uploading ? 'cursor-not-allowed opacity-50' : 'hover:brightness-110'}`}
          style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.14)' }}>
          {uploading ? '\u89e3\u6790\u4e2d\u2026\uff08\u7ea6 1 \u5206\u949f\uff09' : '\u4e0a\u4f20\u672c\u5730\u7b80\u5386\u5165\u6c60'}</label>
        <button type="button" onClick={() => void exportPdf()} disabled={exporting}
          className="rounded-full px-5 py-2 text-sm text-text-1 transition hover:brightness-110 disabled:opacity-50"
          style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)' }}>
          {exporting ? '\u5bfc\u51fa\u4e2d\u2026' : '\u5bfc\u51fa\u5f53\u524d\u7b80\u5386 PDF'}</button>
        <span className="ml-auto text-xs text-text-3">
          {poolDirty || docDirty ? '\u6709\u672a\u4fdd\u5b58\u7684\u4fee\u6539\uff0c\u8bb0\u5f97\u70b9\u5404\u680f\u7684\u300c\u4fdd\u5b58\u300d' : '\u6539\u52a8\u5df2\u5168\u90e8\u4fdd\u5b58'}</span>
      </div>

      <div className="mb-4">
        <PoolDiffPanel key={pendingKey} onApplied={() => { void reloadPool(); setPendingKey((n) => n + 1) }} />
      </div>

      {/* \u628a\u5f53\u524d\u8fd9\u4e00\u7248\u5b58\u6210\u65b0\u7684\u300c\u5df2\u4fdd\u5b58\u7b80\u5386\u300d\u2014\u2014\u65b0\u5efa\u7b80\u5386\u7684\u552f\u4e00\u5165\u53e3\uff08\u539f\u5728\u5df2\u4fdd\u5b58\u7b80\u5386\u9875\uff0c\u4e0e\u300c\u5f53\u524d\u7b80\u5386\u300d\u6982\u5ff5\u51b2\u7a81\uff09 */}
      <div className="mb-4 flex flex-wrap items-end gap-2 rounded-xl px-3 py-2.5"
        style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}>
        <span className="pb-1.5 text-[12px] font-medium text-text-2">{'\u5b58\u4e3a\u65b0\u7b80\u5386'}</span>
        <label className="flex flex-col gap-1">
          <span className="text-[11px] text-text-3">{'\u76ee\u6807\u5c97\u4f4d'}</span>
          <input className="w-40 rounded bg-bg-card px-2 py-1.5 text-xs text-text-1 focus:outline-none" style={inputStyle}
            placeholder={'\u5982 \u6e38\u620f\u7b56\u5212'} value={newTarget}
            onChange={(e) => setNewTarget(e.target.value)} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[11px] text-text-3">{'\u7b80\u5386\u540d\uff08\u53ef\u6539\uff09'}</span>
          <input className="w-56 rounded bg-bg-card px-2 py-1.5 text-xs text-text-1 focus:outline-none" style={inputStyle}
            placeholder={defaultResumeName(doc.basic_info.name || '', newTarget)}
            value={nameTouched ? newName : ''}
            onChange={(e) => { setNewName(e.target.value); setNameTouched(true) }} />
        </label>
        <button type="button" onClick={() => void saveAsNew()} disabled={savingAs}
          className="rounded-lg px-4 py-1.5 text-[13px] font-semibold text-white transition hover:brightness-110 disabled:opacity-50"
          style={{ background: '#0a84ff' }}>{savingAs ? '\u4fdd\u5b58\u4e2d\u2026' : '\u5b58\u4e3a\u65b0\u7b80\u5386'}</button>
        <span className="text-[11px] text-text-3">{'\u4f1a\u628a\u5f53\u524d\u7f16\u8f91\u5185\u5bb9\u53e6\u5b58\u4e00\u4efd\uff0c\u4e4b\u540e\u7f16\u8f91\u65b0\u7684\u90a3\u4efd'}</span>
      </div>

      <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-center">
        {/* \u2460 \u4fe1\u606f\u6c60 */}
        {/* \u4e09\u5217\u5747\u53c2\u4e0e\u62c9\u4f38\uff0c\u5404\u81ea\u5c01\u9876\uff1a\u4fe1\u606f\u6c60 44rem < \u5f53\u524d\u7b80\u5386 52rem\uff08\u53ea\u7a0d\u5bbd\uff0c\u591a\u51fa\u6765\u7684\u4f4d\u7f6e\u7ed9 B/I/U\uff09 */}
        <div className="min-w-0 flex-1 xl:max-w-[44rem]">
          <div className={colHead}>
            {'\u4fe1\u606f\u6c60'}<DevLabel name="PoolColumn" />
            <span className="font-normal normal-case text-text-3">{`${poolCount} \u6761`}</span>
            {poolDirty && dirtyDot}
            <button type="button" onClick={() => void doSavePool()} disabled={savingPool || !poolDirty}
              className={`${saveBtn} ml-auto`}
              style={poolDirty
                ? { background: '#0a84ff', color: '#fff', boxShadow: '0 0 0 3px rgba(10,132,255,0.22)' }
                : { background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.45)', border: '1px solid rgba(255,255,255,0.12)' }}>
              {savingPool ? '\u4fdd\u5b58\u4e2d\u2026' : poolDirty ? '\u4fdd\u5b58\u4fe1\u606f\u6c60' : '\u2713 \u5df2\u4fdd\u5b58'}</button>
          </div>
          <div className="space-y-3">
            <Card title={'\u57fa\u672c\u4fe1\u606f'} dev="PoolBasic">
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
                {BASIC_FIELDS.map(({ key, label }) => (
                  <label key={key} className="flex flex-col gap-1">
                    <span className="text-[11px] text-text-3">{label}</span>
                    <input className={inputCls} style={inputStyle} value={pool.basic_info[key] ?? ''}
                      onChange={(e) => {
                        const bi = { ...pool.basic_info, [key]: e.target.value }
                        setPool({ ...pool, basic_info: bi })
                        setDoc({ ...doc, basic_info: bi })
                      }} />
                  </label>
                ))}
              </div>
            </Card>
            <Card title={'\u5168\u90e8\u7d20\u6750'} dev="PoolSections" action={
              <div className="flex items-center gap-2">
              <button type="button" onClick={() => { setShowSnaps((v) => !v); if (!showSnaps) loadSnaps() }}
                className="rounded-lg px-2.5 py-1 text-[11px] text-text-3 transition hover:bg-bg-card2 hover:text-text-1"
                style={{ border: '1px solid rgba(255,255,255,0.1)' }}>{LABEL_HISTORY}</button>
              <button type="button" onClick={() => void doSavePool()} disabled={savingPool || !poolDirty}
                className={saveBtn}
                style={poolDirty
                  ? { background: '#0a84ff', color: '#fff', boxShadow: '0 0 0 3px rgba(10,132,255,0.22)' }
                  : { background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.45)', border: '1px solid rgba(255,255,255,0.12)' }}>
                {savingPool ? esc_saving : poolDirty ? esc_save : esc_saved}</button>
              </div>
            }>
              {buildNote && (
                <div className="mb-3 rounded-lg px-3 py-2 text-[11px] leading-relaxed"
                  style={{ background: 'rgba(245,166,35,0.1)', border: '1px solid rgba(245,166,35,0.3)', color: '#f5a623' }}>
                  {buildNote}
                </div>
              )}
              {showSnaps && (
                <div className="mb-3 rounded-lg p-2.5" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.09)' }}>
                  <p className="mb-2 text-[11px] text-text-3">{HINT_HISTORY}</p>
                  <div className="space-y-1">
                    {/* \u5f53\u524d\u7248\u672c\u4e5f\u5217\u8fdb\u6765\uff0c\u770b\u6e05\u81ea\u5df1\u5728\u54ea\u91cc\u518d\u56de\u6eda */}
                    {snapCur && (
                      <div className="flex items-center gap-2 rounded px-2 py-1.5"
                        style={{ background: 'rgba(48,209,88,0.1)', border: '1px solid rgba(48,209,88,0.35)' }}>
                        <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: '#30d158' }} />
                        <span className="flex-1 truncate text-[11px] font-medium" style={{ color: '#30d158' }}>
                          {LABEL_CURRENT}{snapCur.saved_at ? ` \u00b7 ${snapCur.saved_at}` : ''}</span>
                        <span className="shrink-0 text-[11px] text-text-3">{snapCur.sections}{LABEL_SEC}{snapCur.blocks}{LABEL_BLK}</span>
                      </div>
                    )}
                    {snaps.length === 0 ? <p className="pt-1 text-[11px] text-text-3">{HINT_NO_HISTORY}</p> : snaps.map((sn) => (
                      <div key={sn.file} className="flex items-center gap-2 rounded px-2 py-1"
                        style={sn.is_current
                          ? { background: 'rgba(48,209,88,0.08)', border: '1px solid rgba(48,209,88,0.25)' }
                          : { background: 'rgba(255,255,255,0.04)', border: '1px solid transparent' }}>
                        {sn.is_current
                          ? <span className="inline-block h-2 w-2 shrink-0 rounded-full" title={LABEL_SAME_TIP} style={{ background: '#30d158' }} />
                          : <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: 'rgba(255,255,255,0.16)' }} />}
                        <span className="flex-1 truncate text-[11px] text-text-2">{sn.saved_at}</span>
                        {sn.daily && (
                          <span className="shrink-0 rounded px-1.5 py-0.5 text-[10px]" title={LABEL_DAILY_TIP}
                            style={{ background: 'rgba(48,209,88,0.14)', color: '#30d158' }}>{LABEL_DAILY}</span>
                        )}
                        <span className="shrink-0 text-[11px] text-text-3">{sn.sections}{LABEL_SEC}{sn.blocks}{LABEL_BLK}</span>
                        {sn.is_current
                          ? <span className="shrink-0 px-2 py-0.5 text-[11px]" style={{ color: '#30d158' }}>{LABEL_IN_USE}</span>
                          : <button type="button" onClick={() => void restoreSnap(sn.file)}
                              className="shrink-0 rounded px-2 py-0.5 text-[11px] font-medium text-signal-bright transition hover:bg-signal-blue/15">{LABEL_RESTORE}</button>}
                      </div>
                    ))}
                  </div>
                </div>
              )}
              <p className="mb-3 text-[11px] leading-relaxed text-text-3">{'\u8fd9\u91cc\u662f\u4f60\u7684\u5168\u90e8\u4fe1\u606f\uff0c\u6295\u4ec0\u4e48\u5c97\u90fd\u4ece\u8fd9\u91cc\u6311\u3002\u62d6\u6761\u76ee\u5230\u4e2d\u95f4\u6216\u70b9 \u2192 \u52a0\u5165\u5f53\u524d\u7b80\u5386\uff08\u6c60\u91cc\u4ecd\u4fdd\u7559\uff09\u3002\u6539\u5b8c\u8bb0\u5f97\u70b9\u300c\u4fdd\u5b58\u300d\u3002'}</p>
              <SectionEditor doc={pool} onChange={setPool} owner="pool" compact
                onQuickAdd={(si, bi) => copyBlockToResume(si, bi)}
                onQuickAddSection={(si) => copySectionToResume(si)}
                summaryHint={'\u6982\u62ec\uff08\u4e0d\u4e0a\u7b80\u5386\uff0cAI \u6311\u5757\u7d22\u5f15\uff09'} />
            </Card>
          </div>
        </div>

        {/* \u2461 \u5f53\u524d\u7b80\u5386 */}
        <div className="min-w-0 flex-1 xl:grow-[1.15] xl:max-w-[52rem]">
          <div className={colHead}>
            {'\u5f53\u524d\u7b80\u5386'}<DevLabel name="ResumeColumn" />
            <span className="font-normal normal-case text-text-3">{activeName ? `${activeName} \u00b7 ${docCount} \u6761` : `${docCount} \u6761`}</span>
            {docDirty && dirtyDot}
            <button type="button" onClick={() => void doSaveDoc()} disabled={savingDoc || !docDirty}
              className={`${saveBtn} ml-auto`}
              style={docDirty
                ? { background: '#0a84ff', color: '#fff', boxShadow: '0 0 0 3px rgba(10,132,255,0.22)' }
                : { background: 'rgba(255,255,255,0.05)', color: 'rgba(255,255,255,0.45)', border: '1px solid rgba(255,255,255,0.12)' }}>
              {savingDoc ? '\u4fdd\u5b58\u4e2d\u2026' : docDirty ? '\u4fdd\u5b58\u7b80\u5386' : '\u2713 \u5df2\u4fdd\u5b58'}</button>
          </div>
          <Card title={'\u7b80\u5386\u5185\u5bb9'} dev="ResumeSections">
            <p className="mb-3 text-[10px] leading-relaxed text-text-3">{'\u8fd9\u4efd\u7b80\u5386\u5b9e\u9645\u5305\u542b\u7684\u5185\u5bb9\u3002\u6539\u5b83\u4e0d\u5f71\u54cd\u4fe1\u606f\u6c60\uff1b\u5220\u6761\u76ee\u53ea\u4ece\u8fd9\u4efd\u7b80\u5386\u79fb\u9664\u3002'}</p>
            <SectionEditor doc={doc} onChange={setDoc} owner="resume" compact showStyle
              onExternalDrop={onResumeExternalDrop}
              summaryHint={'\u6982\u62ec\uff08\u4e0d\u4e0a\u7b80\u5386\uff09'} />
          </Card>
        </div>

        {/* \u2462 \u9884\u89c8 */}
        <div className="min-w-0 xl:basis-[50rem] xl:grow-0">
          <div className={colHead}>{'\u9884\u89c8\uff08A4\uff09'}<DevLabel name="ResumePreview" /></div>
          <div className="sticky top-4"><A4Preview html={html} /></div>
        </div>
      </div>
    </div>
  )
}

// \u2500\u2500 \u5206\u9875 2\uff1a\u5df2\u4fdd\u5b58\u7b80\u5386\uff08\u591a\u4efd\u7ba1\u7406 + \u6700\u8fd1\u751f\u6210 + AI \u81ea\u52a8\u5b9a\u5236\u5f00\u5173\uff09\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
function SavedTab({ onErr, onActiveChanged, flushEdits }: {
  onErr: (m: string | null) => void
  onActiveChanged: () => Promise<void>
  flushEdits: () => Promise<void>
}) {
  const [resumes, setResumes] = useState<ResumeIndex | null>(null)
  const [exportsList, setExportsList] = useState<ResumeExport[]>([])
  const [busy, setBusy] = useState(false)
  const [aiOn, setAiOn] = useState(() => window.localStorage.getItem('resume.aiCompose') === 'on')
  const [jobTitle, setJobTitle] = useState('')
  const [jdText, setJdText] = useState('')
  const [composing, setComposing] = useState(false)
  const [previewSlug, setPreviewSlug] = useState<string>('')
  const [previewDoc, setPreviewDoc] = useState<ResumeBlocks | null>(null)
  const metaTimer = useRef<number | null>(null)
  const previewName = resumes?.items.find((i) => i.slug === previewSlug)?.name ?? ''

  const showPreview = (slug: string) => {
    setPreviewSlug(slug)
    void API.getResumeDoc(slug).then(setPreviewDoc).catch(() => setPreviewDoc(null))
  }
  const refresh = () => {
    void API.getResumes().then((r) => {
      setResumes(r)
      if (!previewSlug && r.active) showPreview(r.active)
    }).catch((e) => onErr((e as Error).message))
    void API.getResumeExports().then((r) => setExportsList(r.exports)).catch(() => {})
  }
  useEffect(refresh, [])

  const activate = async (slug: string) => {
    setBusy(true); onErr(null)
    try { await flushEdits(); await API.activateResume(slug); await onActiveChanged(); refresh() }
    catch (e) { onErr((e as Error).message) } finally { setBusy(false) }
  }
  const remove = async (slug: string) => {
    if (!window.confirm('\u5220\u9664\u8fd9\u4efd\u7b80\u5386\uff1f\u4e0d\u53ef\u6062\u590d\u3002')) return
    try { await API.deleteResume(slug); await onActiveChanged(); setPreviewSlug(''); refresh() }
    catch (e) { onErr((e as Error).message) }
  }
  const updateMeta = (slug: string, patch: { name?: string; target?: string }) => {
    setResumes((r) => (r ? { ...r, items: r.items.map((it) => (it.slug === slug ? { ...it, ...patch } : it)) } : r))
    if (metaTimer.current) window.clearTimeout(metaTimer.current)
    metaTimer.current = window.setTimeout(() => { void API.updateResumeMeta(slug, patch).catch(() => {}) }, 600)
  }
  const compose = async () => {
    setComposing(true); onErr(null)
    try {
      await flushEdits()
      const r = await API.composeResume({ job_title: jobTitle.trim(), jd_text: jdText.trim() })
      await onActiveChanged()
      setJobTitle(''); setJdText(''); refresh(); showPreview(r.resume.slug)
    } catch (e) { onErr((e as Error).message) } finally { setComposing(false) }
  }
  const toggleAi = () => {
    const next = !aiOn
    setAiOn(next)
    window.localStorage.setItem('resume.aiCompose', next ? 'on' : 'off')
  }

  return (
    <div className="flex flex-col gap-4 xl:flex-row xl:items-start">
      <div className="min-w-0 flex-1 space-y-4">
      <Card title={'\u6211\u7684\u7b80\u5386'} dev="ResumeList">
        <p className="mb-3 text-[11px] leading-relaxed text-text-3">{'\u70b9\u5361\u7247\u770b\u9884\u89c8\uff1b\u70b9\u300c\u7f16\u8f91\u300d\u628a\u90a3\u4efd\u5207\u5230\u300c\u7b80\u5386\u5de5\u4f5c\u53f0\u300d\u91cc\u6539\u3002\u6295\u9012\u65f6\u6309\u5c97\u4f4d\u9009\u7528\u5bf9\u5e94\u7248\u672c\u3002'}</p>
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
          {(resumes?.items ?? []).map((it) => {
            const isActive = it.slug === resumes?.active
            return (
              <div key={it.slug}
                className={`cursor-pointer rounded-xl p-3 transition hover:brightness-110`}
                style={{
                  background: isActive ? 'rgba(10,132,255,0.12)' : 'rgba(255,255,255,0.04)',
                  border: isActive ? '1px solid rgba(10,132,255,0.45)' : '1px solid rgba(255,255,255,0.07)',
                  outline: it.slug === previewSlug ? '1px solid rgba(255,255,255,0.35)' : 'none', outlineOffset: 2,
                }}
                onClick={() => showPreview(it.slug)}>
                <div className="space-y-1.5" onClick={(e) => { if (isActive) e.stopPropagation() }}>
                  {isActive ? (
                    <>
                      <input className="w-full rounded bg-bg-card px-2 py-1 text-xs font-medium text-text-1 focus:outline-none" style={inputStyle}
                        value={it.name} onChange={(e) => updateMeta(it.slug, { name: e.target.value })} />
                      <input className="w-full rounded bg-bg-card px-2 py-1 text-[11px] text-text-2 focus:outline-none" style={inputStyle}
                        placeholder={'\u76ee\u6807\u5c97\u4f4d'} value={it.target} onChange={(e) => updateMeta(it.slug, { target: e.target.value })} />
                      <div className="flex items-center gap-1.5">
                        <p className="text-[11px] text-signal-bright">{'\u25cf \u6b63\u5728\u7f16\u8f91'}</p>
                        <PdfStatePill state={it.pdf_state} exportedAt={it.pdf_exported_at} />
                      </div>
                    </>
                  ) : (
                    <div className="flex items-start justify-between gap-1">
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5">
                          <p className="truncate text-xs font-medium text-text-1">{it.name}</p>
                          <PdfStatePill state={it.pdf_state} exportedAt={it.pdf_exported_at} />
                        </div>
                        <p className="truncate text-[11px] text-text-3">{it.target || '\u672a\u8bbe\u76ee\u6807\u5c97\u4f4d'}</p>
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        <button type="button" title={'\u5207\u6362\u4e3a\u7f16\u8f91\u8fd9\u4efd'} disabled={busy}
                          onClick={(e) => { e.stopPropagation(); void activate(it.slug) }}
                          className="rounded-md px-2 py-1 text-[11px] font-medium text-signal-bright transition hover:bg-signal-blue/15 disabled:opacity-40">{'\u7f16\u8f91'}</button>
                        <button type="button" title={'\u5220\u9664'} onClick={(e) => { e.stopPropagation(); void remove(it.slug) }}
                          className="px-1 text-text-3 transition hover:text-signal-red">{'\u2715'}</button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>
        <p className="mt-3 border-t pt-3 text-[11px] text-text-3" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
          {'\u65b0\u5efa\u7b80\u5386\u8bf7\u5230\u300c\u7b80\u5386\u5de5\u4f5c\u53f0\u300d\u2014\u2014\u7f16\u8f91\u597d\u5185\u5bb9\u540e\u70b9\u300c\u5b58\u4e3a\u65b0\u7b80\u5386\u300d\u3002'}</p>
      </Card>

      <Card title={'\u6700\u8fd1\u751f\u6210'} dev="ResumeExports">
        {exportsList.length === 0 ? (
          <p className="text-[11px] text-text-3">{'\u8fd8\u6ca1\u6709\u5bfc\u51fa\u8bb0\u5f55\uff1b\u5728\u5de5\u4f5c\u53f0\u70b9\u300c\u5bfc\u51fa PDF\u300d\u540e\u4f1a\u5b58\u6863\u5728\u8fd9\u91cc\u3002'}</p>
        ) : (
          <div className="space-y-1.5">
            {exportsList.map((ex) => (
              <div key={ex.file} className="flex items-center justify-between gap-2 rounded-lg px-2.5 py-1.5" style={{ background: 'rgba(255,255,255,0.04)' }}>
                <a href={`/api/resume/exports/${encodeURIComponent(ex.file)}`} target="_blank" rel="noreferrer"
                  className="min-w-0 flex-1 truncate text-[11px] text-signal-bright transition hover:brightness-125">{ex.file.replace(/\.pdf$/, '')}</a>
                <span className="shrink-0 text-[11px] text-text-3">{ex.mtime}</span>
                <span className="shrink-0 text-[10px] text-text-3">{Math.max(1, Math.round(ex.size / 1024))}{' KB'}</span>
                <button type="button" title={'\u5220\u9664'}
                  onClick={() => { void API.deleteResumeExport(ex.file).then(() => setExportsList((l) => l.filter((x) => x.file !== ex.file))).catch((e) => onErr((e as Error).message)) }}
                  className="shrink-0 px-1 text-text-3 transition hover:text-signal-red">{'\u2715'}</button>
              </div>
            ))}
          </div>
        )}
      </Card>

      <Card title={'AI \u81ea\u52a8\u5b9a\u5236\uff08\u5b9e\u9a8c\uff09'} dev="ResumeCompose" action={
        <button type="button" onClick={toggleAi}
          className="flex items-center gap-2 rounded-full px-1 py-1 text-[11px] text-text-3 transition hover:text-text-1">
          <span className="relative inline-block h-4 w-7 rounded-full transition"
            style={{ background: aiOn ? '#0a84ff' : 'rgba(255,255,255,0.15)' }}>
            <span className="absolute top-0.5 h-3 w-3 rounded-full bg-white transition-all" style={{ left: aiOn ? 14 : 2 }} />
          </span>
          {aiOn ? '\u5df2\u5f00\u542f' : '\u5df2\u5173\u95ed'}
        </button>
      }>
        <p className="text-[11px] leading-relaxed text-text-3">
          {'\u9ed8\u8ba4\u5173\u95ed\uff1a\u7b80\u5386\u5185\u5bb9\u7531\u4f60\u81ea\u5df1\u6311\u9009\u7ec4\u5408\uff0cAI \u53ea\u8d1f\u8d23\u6295\u9012\u65f6\u5224\u65ad\u8be5\u53d1\u54ea\u4e00\u4efd\u3002\u5f00\u542f\u540e\uff0c\u53ef\u4ee5\u8ba9 AI \u76f4\u63a5\u6309\u5c97\u4f4d JD \u4ece\u4fe1\u606f\u6c60\u6311\u5185\u5bb9\u3001\u751f\u6210\u4e00\u6574\u4efd\u65b0\u7b80\u5386\uff08\u5b83\u53ea\u6311\u9009\u4e0e\u6392\u5e8f\uff0c\u4e0d\u6539\u5199\u4f60\u7684\u539f\u6587\uff09\u3002'}
        </p>
        {aiOn && (
          <div className="mt-3 flex flex-wrap items-end gap-2 border-t pt-3" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
            <label className="flex flex-col gap-1">
              <span className="text-[11px] text-text-3">{'\u76ee\u6807\u5c97\u4f4d'}</span>
              <input className="w-44 rounded bg-bg-card px-2 py-1.5 text-xs text-text-1 focus:outline-none" style={inputStyle}
                placeholder={'\u5982 \u6e38\u620f\u7b56\u5212'} value={jobTitle} onChange={(e) => setJobTitle(e.target.value)} />
            </label>
            <label className="flex min-w-[16rem] flex-1 flex-col gap-1">
              <span className="text-[11px] text-text-3">{'JD \u6b63\u6587\uff08\u53ef\u9009\uff0c\u7c98\u4e0a\u66f4\u51c6\uff09'}</span>
              <textarea className="w-full rounded bg-bg-card px-2 py-1.5 text-[11px] text-text-2 focus:outline-none" style={{ ...inputStyle, minHeight: 52 }}
                value={jdText} onChange={(e) => setJdText(e.target.value)} />
            </label>
            <button type="button" disabled={composing || !(jobTitle.trim() || jdText.trim())} onClick={() => void compose()}
              className="rounded-lg px-4 py-2 text-xs text-white transition hover:brightness-110 disabled:opacity-40"
              style={{ background: '#0a84ff' }}>{composing ? '\u7ec4\u5408\u4e2d\u2026' : '\u751f\u6210\u65b0\u7b80\u5386'}</button>
          </div>
        )}
      </Card>

      <details className="group">
        <summary className="flex cursor-pointer select-none items-center gap-2.5 rounded-xl px-4 py-3 text-sm font-medium text-text-1 transition hover:brightness-125"
          style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid rgba(255,255,255,0.12)' }}>
          <span className="text-[13px] text-text-3 transition group-open:rotate-90">{'\u25b6'}</span>
          <span>{'\u8fdb\u9636\u529f\u80fd'}</span>
          <span className="text-[11px] font-normal text-text-3">{'\u9884\u5236\u6a21\u677f \u00b7 \u6309\u5df2\u6295\u5c97\u4f4d\u751f\u6210\u65b9\u6848\u4e0e\u62db\u547c\u8bed'}</span>
        </summary>
        <div className="mt-4 space-y-5">
          <TemplatesCard />
          <TailorCard />
        </div>
      </details>
      </div>

      <div className="min-w-0 flex-1">
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-text-3">
          {'\u9884\u89c8\uff08A4\uff09'}<DevLabel name="SavedPreview" />
          <span className="font-normal normal-case text-text-3">{previewName}</span>
        </div>
        <div className="sticky top-4">
          {previewDoc ? <A4Preview html={buildResumeHtml(previewDoc)} />
            : <div className="rounded-xl px-4 py-10 text-center text-xs text-text-3" style={{ border: '1px dashed rgba(255,255,255,0.14)' }}>{'\u9009\u4e00\u4efd\u7b80\u5386\u67e5\u770b\u9884\u89c8'}</div>}
        </div>
      </div>
    </div>
  )
}

export default function Resume() {
  const [tab, setTab] = useState<'workbench' | 'saved'>(() =>
    (window.localStorage.getItem('resume.tab2') as 'workbench' | 'saved') || 'workbench')
  const [err, setErr] = useState<string | null>(null)
  // \u7f16\u8f91\u72b6\u6001\u653e\u5728\u9875\u9762\u7ea7\uff1a\u5207\u5230\u300c\u5df2\u4fdd\u5b58\u7b80\u5386\u300d\u518d\u5207\u56de\u6765\uff0c\u672a\u4fdd\u5b58\u7684\u4fee\u6539\u4ecd\u5728
  const [pool, setPoolState] = useState<ResumeBlocks | null>(null)
  const [doc, setDocState] = useState<ResumeBlocks | null>(null)
  const [poolDirty, setPoolDirty] = useState(false)
  const [docDirty, setDocDirty] = useState(false)
  const [activeName, setActiveName] = useState('')

  const setPool = (p: ResumeBlocks) => { setPoolState(p); setPoolDirty(true) }
  const setDoc = (d: ResumeBlocks) => { setDocState(d); setDocDirty(true) }
  const reloadPool = async () => { setPoolState(await API.getPool()); setPoolDirty(false) }
  const reloadDoc = async () => { setDocState(await API.getResumeBlocks()); setDocDirty(false) }
  const reloadMeta = async () => {
    const r = await API.getResumes()
    setActiveName(r.items.find((i) => i.slug === r.active)?.name ?? '')
  }
  useEffect(() => {
    void reloadPool().catch((e) => setErr((e as Error).message))
    void reloadDoc().catch((e) => setErr((e as Error).message))
    void reloadMeta().catch(() => {})
  }, [])

  // \u5173\u6807\u7b7e\u9875/\u5237\u65b0\u524d\uff0c\u6d4f\u89c8\u5668\u62e6\u4e00\u4e0b\u672a\u4fdd\u5b58\u7684\u4fee\u6539
  useEffect(() => {
    const h = (e: BeforeUnloadEvent) => { if (poolDirty || docDirty) { e.preventDefault(); e.returnValue = '' } }
    window.addEventListener('beforeunload', h)
    return () => window.removeEventListener('beforeunload', h)
  }, [poolDirty, docDirty])

  const savePool = async () => { if (pool) { await API.savePool(pool); setPoolDirty(false) } }
  const saveDoc = async () => { if (doc) { await API.saveResumeBlocks(doc); setDocDirty(false) } }
  // \u5207\u6362/\u65b0\u5efa/\u751f\u6210\u7b80\u5386\u524d\u5148\u628a\u672a\u4fdd\u5b58\u7684\u6539\u52a8\u843d\u76d8\uff0c\u907f\u514d\u88ab\u670d\u52a1\u7aef\u5185\u5bb9\u8986\u76d6
  const flushEdits = async () => { if (poolDirty) await savePool(); if (docDirty) await saveDoc() }

  const switchTab = (t: 'workbench' | 'saved') => { setTab(t); setErr(null); window.localStorage.setItem('resume.tab2', t) }

  return (
    <div className="relative">
      <DevLabel name="ResumePage" float />
      <div className="mb-3 flex items-center gap-3">
        <div className="inline-flex gap-1 rounded-xl bg-bg-card2 p-1" style={{ border: '1px solid rgba(255,255,255,0.06)' }}>
          {([['workbench', '\u7b80\u5386\u5de5\u4f5c\u53f0'], ['saved', '\u5df2\u4fdd\u5b58\u7b80\u5386']] as const).map(([k, label]) => (
            <button key={k} type="button" onClick={() => switchTab(k)}
              className={`rounded-lg px-4 py-1.5 text-sm font-medium transition ${tab === k ? 'text-white' : 'text-text-3 hover:text-text-1'}`}
              style={tab === k ? { background: '#0a84ff' } : undefined}>{label}</button>
          ))}
        </div>
        {(poolDirty || docDirty) && (
          <span className="flex items-center gap-1.5 text-[11px]" style={{ color: '#f5a623' }}>
            <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: '#f5a623' }} />
            {'\u6709\u672a\u4fdd\u5b58\u7684\u4fee\u6539'}
          </span>
        )}
      </div>
      {err && <div className="mb-3 rounded-lg bg-signal-red/10 px-4 py-2 text-xs text-signal-red">{err}</div>}
      {!pool || !doc ? <div className="text-sm text-text-3">{'\u52a0\u8f7d\u4e2d\u2026'}</div>
        : tab === 'workbench'
          ? <Workbench onErr={setErr} pool={pool} setPool={setPool} doc={doc} setDoc={setDoc}
              poolDirty={poolDirty} docDirty={docDirty} activeName={activeName}
              savePool={savePool} saveDoc={saveDoc} reloadPool={reloadPool}
              onActiveChanged={async () => { await reloadDoc(); await reloadMeta() }} />
          : <SavedTab onErr={setErr} flushEdits={flushEdits}
              onActiveChanged={async () => { await reloadDoc(); await reloadMeta() }} />}
    </div>
  )
}
