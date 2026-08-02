import { useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from 'react'
import { API, type ResumeBlocks, type ResumeBlock, type ResumeBasicInfo, type ResumeTemplate, type ResumePlan, type ResumeIndex, type ResumeExport, type Job } from '@/api'
import DevLabel from '@/components/dev/DevLabel'

type Cat = 'education' | 'internship' | 'project' | 'skills' | 'awards'
const CATS: Array<{ key: Cat; label: string }> = [
  { key: 'education', label: '\u6559\u80b2' },
  { key: 'internship', label: '\u5b9e\u4e60\u7ecf\u5386' },
  { key: 'project', label: '\u9879\u76ee\u7ecf\u5386' },
  { key: 'skills', label: '\u6280\u80fd\u7279\u957f' },
  { key: 'awards', label: '\u83b7\u5956\u8363\u8a89' },
]
const BASIC_FIELDS: Array<{ key: keyof ResumeBasicInfo; label: string }> = [
  { key: 'name', label: '\u59d3\u540d' },
  { key: 'phone', label: '\u7535\u8bdd' },
  { key: 'email', label: '\u90ae\u7bb1' },
  { key: 'city', label: '\u57ce\u5e02' },
  { key: 'degree', label: '\u5b66\u5386' },
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
const escHtml = (s: string) =>
  String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')

const catLabel = (k: string) => CATS.find((c) => c.key === k)?.label ?? k

// FlowCV\u300cclassic\u300d\u98ce\u683c\uff1a\u5c45\u4e2d\u5927\u6807\u9898 + \u8054\u7cfb\u884c + \u5206\u533a\u6574\u884c\u4e0b\u5212\u7ebf + \u6761\u76ee\u7c97\u6807\u9898/\u53f3\u7070\u65e5\u671f\u3002
// px \u753b\u5e03(794=A4@96dpi\u5bbd)\uff0c\u9884\u89c8 iframe \u4e0e\u5bfc\u51fa PDF \u540c\u6e90\uff1b\u5206\u533a\u987a\u5e8f\u8ddf\u968f section_order\u3002
function buildResumeHtml(blocks: ResumeBlocks): string {
  const bi = blocks.basic_info
  const contact = [bi.email, bi.phone, bi.city].filter(Boolean).map(escHtml).join('<span class="sep">\u00b7</span>')
  const order = (blocks.section_order?.length ? blocks.section_order : CATS.map((c) => c.key)) as Cat[]
  const secs = order.map((key) => {
    const list = (blocks[key] || []).filter((b) => b.title || b.bullets.some((x) => x.trim()))
    if (!list.length) return ''
    const entries = list
      .map((b) => {
        const bullets = b.bullets.filter((x) => x.trim()).map((x) => `<li>${escHtml(x)}</li>`).join('')
        const head = `<div class="e-head"><span class="e-title">${escHtml(b.title)}</span>${b.time ? `<span class="e-date">${escHtml(b.time)}</span>` : ''}</div>`
        return `<div class="entry">${head}${bullets ? `<ul>${bullets}</ul>` : ''}</div>`
      })
      .join('')
    return `<div class="section"><div class="s-title">${escHtml(catLabel(key))}</div>${entries}</div>`
  }).join('')
  return `<!doctype html><html><head><meta charset="utf-8"><style>
@page { size:A4; margin:0; }
* { box-sizing:border-box; }
html,body { margin:0; padding:0; }
body { width:794px; min-height:1123px; padding:46px 56px; background:#fff; color:#1a1a1a;
  font-family: Georgia, "Times New Roman", "Microsoft YaHei", "PingFang SC", serif; font-size:14px; line-height:1.52; }
.name { text-align:center; font-size:31px; font-weight:700; letter-spacing:2px; margin:0 0 10px; }
.contact { text-align:center; font-size:12.5px; color:#333; margin-bottom:4px; }
.contact .sep { margin:0 10px; color:#c2c2c2; }
.subtitle { text-align:center; font-size:12.5px; color:#555; margin-bottom:4px; }
.section { margin-top:17px; }
.s-title { font-size:15px; font-weight:700; letter-spacing:1px; padding-bottom:4px; margin-bottom:8px; border-bottom:1px solid #1a1a1a; }
.entry { margin-bottom:10px; }
.e-head { display:flex; justify-content:space-between; align-items:baseline; gap:12px; }
.e-title { font-weight:700; font-size:14px; }
.e-date { color:#777; font-size:12px; white-space:nowrap; font-variant-numeric:tabular-nums; }
ul { margin:4px 0 0; padding-left:17px; }
li { margin-bottom:2px; }
</style></head><body>
<div class="name">${escHtml(bi.name)}</div>
${contact ? `<div class="contact">${contact}</div>` : ''}
${bi.target_title ? `<div class="subtitle">${escHtml(bi.target_title)}</div>` : ''}
${secs}
</body></html>`
}

// \u53f3\u4fa7\u56fa\u5b9a A4\uff1aiframe \u4ee5 794x(\u5185\u5bb9\u9ad8) \u539f\u751f\u6e32\u67d3\uff0c\u6309\u9762\u677f\u5bbd\u7b49\u6bd4 scale\uff0c\u5c45\u4e2d\u5e26\u7eb8\u5f20\u9634\u5f71\u3002
function A4Preview({ html }: { html: string }) {
  const boxRef = useRef<HTMLDivElement>(null)
  const [scale, setScale] = useState(0.72)
  const [pageH, setPageH] = useState(1123)
  useEffect(() => {
    const el = boxRef.current
    if (!el) return
    const update = () => { const w = el.clientWidth; if (w) setScale(Math.min(1, w / 794)) }
    update()
    const ro = new ResizeObserver(update)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const onLoad = (e: React.SyntheticEvent<HTMLIFrameElement>) => {
    const doc = e.currentTarget.contentDocument
    if (doc && doc.body) setPageH(Math.max(1123, doc.body.scrollHeight + 2))
  }
  return (
    <div ref={boxRef} className="w-full overflow-auto" style={{ maxHeight: 'calc(100vh - 170px)' }}>
      <div style={{ width: 794 * scale, height: pageH * scale, margin: '0 auto' }}>
        <iframe title="resume-preview" srcDoc={html} onLoad={onLoad} className="bg-white shadow-card"
          style={{ width: 794, height: pageH, border: 0, transformOrigin: 'top left', transform: `scale(${scale})` }} />
      </div>
    </div>
  )
}

// \u5de6\u4fa7\u72ec\u7acb\u680f\uff1a\u591a\u4efd\u7b80\u5386\uff08\u6bcf\u4efd\u72ec\u7acb\u5b8c\u6574\uff0c\u6309\u5c97\u4f4d\u547d\u540d\uff09+ \u6700\u8fd1\u751f\u6210\uff08\u5bfc\u51fa PDF \u5b58\u6863\uff09
function SidePanel({ resumes, exports, busy, onSwitch, onCreate, onDelete, onMeta, onDeleteExport }: {
  resumes: ResumeIndex | null
  exports: ResumeExport[]
  busy: boolean
  onSwitch: (slug: string) => void
  onCreate: (name: string, target: string) => void
  onDelete: (slug: string) => void
  onMeta: (slug: string, patch: { name?: string; target?: string }) => void
  onDeleteExport: (fname: string) => void
}) {
  const [newName, setNewName] = useState('')
  const [newTarget, setNewTarget] = useState('')
  return (
    <div className="w-full shrink-0 space-y-4 lg:w-60">
      <Card title={'\u6211\u7684\u7b80\u5386'} dev="ResumeList">
        <p className="mb-3 text-[11px] leading-relaxed text-text-3">{'\u6bcf\u4efd\u72ec\u7acb\u7f16\u8f91\uff1b\u7ed9\u4e0d\u540c\u5c97\u4f4d\u5404\u5efa\u4e00\u4efd\uff0c\u6295\u5bf9\u5e94\u5c97\u4f4d\u65f6\u7528\u5bf9\u5e94\u7248\u672c\u3002'}</p>
        <div className="space-y-2">
          {(resumes?.items ?? []).map((it) => {
            const isActive = it.slug === resumes?.active
            return (
              <div key={it.slug}
                className={`rounded-xl p-3 transition ${isActive ? '' : 'cursor-pointer hover:brightness-110'}`}
                style={{ background: isActive ? 'rgba(10,132,255,0.12)' : 'rgba(255,255,255,0.04)', border: isActive ? '1px solid rgba(10,132,255,0.45)' : '1px solid rgba(255,255,255,0.07)' }}
                onClick={() => { if (!isActive && !busy) onSwitch(it.slug) }}>
                {isActive ? (
                  <div className="space-y-1.5" onClick={(e) => e.stopPropagation()}>
                    <input className="w-full rounded bg-bg-card px-2 py-1 text-xs font-medium text-text-1 focus:outline-none" style={inputStyle}
                      value={it.name} onChange={(e) => onMeta(it.slug, { name: e.target.value })} />
                    <input className="w-full rounded bg-bg-card px-2 py-1 text-[11px] text-text-2 focus:outline-none" style={inputStyle}
                      placeholder={'\u76ee\u6807\u5c97\u4f4d\uff08\u5982 AI Agent \u5f00\u53d1\uff09'} value={it.target} onChange={(e) => onMeta(it.slug, { target: e.target.value })} />
                    <p className="text-[10px] text-signal-bright">{'\u25cf \u5f53\u524d\u7f16\u8f91'}</p>
                  </div>
                ) : (
                  <div className="flex items-start justify-between gap-1">
                    <div className="min-w-0">
                      <p className="truncate text-xs font-medium text-text-1">{it.name}</p>
                      {it.target && <p className="truncate text-[11px] text-text-3">{it.target}</p>}
                    </div>
                    <button type="button" title={'\u5220\u9664'} onClick={(e) => { e.stopPropagation(); onDelete(it.slug) }}
                      className="shrink-0 px-1 text-text-3 transition hover:text-signal-red">{'\u2715'}</button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
        <div className="mt-3 space-y-1.5 border-t pt-3" style={{ borderColor: 'rgba(255,255,255,0.07)' }}>
          <input className="w-full rounded bg-bg-card px-2 py-1.5 text-xs text-text-1 focus:outline-none" style={inputStyle}
            placeholder={'\u65b0\u7b80\u5386\u540d\u79f0'} value={newName} onChange={(e) => setNewName(e.target.value)} />
          <input className="w-full rounded bg-bg-card px-2 py-1.5 text-[11px] text-text-2 focus:outline-none" style={inputStyle}
            placeholder={'\u76ee\u6807\u5c97\u4f4d\uff08\u53ef\u9009\uff09'} value={newTarget} onChange={(e) => setNewTarget(e.target.value)} />
          <button type="button" disabled={busy || !newName.trim()}
            onClick={() => { onCreate(newName.trim(), newTarget.trim()); setNewName(''); setNewTarget('') }}
            className="w-full rounded-lg px-2 py-1.5 text-xs text-signal-bright transition hover:bg-signal-blue/10 disabled:opacity-40">
            {'+ \u590d\u5236\u5f53\u524d\u4e3a\u65b0\u7b80\u5386'}</button>
        </div>
      </Card>

      <Card title={'\u6700\u8fd1\u751f\u6210'} dev="ResumeExports">
        {exports.length === 0 ? (
          <p className="text-[11px] text-text-3">{'\u8fd8\u6ca1\u6709\u5bfc\u51fa\u8bb0\u5f55\uff1b\u70b9\u300c\u5bfc\u51fa PDF\u300d\u540e\u4f1a\u5b58\u6863\u5728\u8fd9\u91cc\u3002'}</p>
        ) : (
          <div className="space-y-1.5">
            {exports.map((ex) => (
              <div key={ex.file} className="flex items-center justify-between gap-1 rounded-lg px-2 py-1.5" style={{ background: 'rgba(255,255,255,0.04)' }}>
                <a href={`/api/resume/exports/${encodeURIComponent(ex.file)}`} target="_blank" rel="noreferrer"
                  className="min-w-0 flex-1 truncate text-[11px] text-signal-bright transition hover:brightness-125" title={ex.file}>
                  {ex.file.replace(/\.pdf$/, '')}
                </a>
                <span className="shrink-0 text-[10px] text-text-3">{Math.max(1, Math.round(ex.size / 1024))}{' KB'}</span>
                <button type="button" title={'\u5220\u9664'} onClick={() => onDeleteExport(ex.file)}
                  className="shrink-0 px-1 text-text-3 transition hover:text-signal-red">{'\u2715'}</button>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  )
}

export default function Resume() {
  const [blocks, setBlocks] = useState<ResumeBlocks | null>(null)
  const [resumes, setResumes] = useState<ResumeIndex | null>(null)
  const [exportsList, setExportsList] = useState<ResumeExport[]>([])
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [building, setBuilding] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [switching, setSwitching] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)
  const metaTimer = useRef<number | null>(null)
  // \u5c55\u5f00\u72b6\u6001\uff1a\u4e00\u6b21\u5c55\u5f00\u4e00\u6761\uff08FlowCV \u5f0f\uff09\uff1b\u62d6\u52a8\u5f00\u59cb\u5373\u5168\u90e8\u6536\u8d77
  const [open, setOpen] = useState<string | null>(null)
  // \u5757\u62d6\u62fd\uff1adragKey \u6807\u6e90\u6761\u6837\u5f0f\uff1bblkSlot=\u63d2\u5165\u69fd\u4f4d\uff08\u6307\u793a\u7ebf\u4f4d\u7f6e\uff09
  const dragBlk = useRef<{ cat: Cat; i: number } | null>(null)
  const [dragKey, setDragKey] = useState<string | null>(null)
  const [blkSlot, setBlkSlot] = useState<{ cat: Cat; slot: number } | null>(null)
  // \u5206\u533a\u62d6\u62fd
  const dragSec = useRef<Cat | null>(null)
  const [secDragKey, setSecDragKey] = useState<Cat | null>(null)
  const [secSlot, setSecSlot] = useState<number | null>(null)

  const refreshMeta = () => {
    void API.getResumes().then(setResumes).catch(() => {})
    void API.getResumeExports().then((r) => setExportsList(r.exports)).catch(() => {})
  }
  useEffect(() => {
    void API.getResumeBlocks().then(setBlocks).catch((e) => setErr((e as Error).message))
    refreshMeta()
  }, [])

  const resumeHtml = useMemo(() => (blocks ? buildResumeHtml(blocks) : ''), [blocks])

  if (!blocks) return <div className="text-sm text-text-3">{err ?? '\u52a0\u8f7d\u4e2d\u2026'}</div>

  const sectionOrder = (blocks.section_order?.length ? blocks.section_order : CATS.map((c) => c.key)) as Cat[]
  const activeMeta = resumes?.items.find((it) => it.slug === resumes.active)

  const setBasic = (k: keyof ResumeBasicInfo, v: string) =>
    setBlocks((b) => (b ? { ...b, basic_info: { ...b.basic_info, [k]: v } } : b))
  const setCatList = (cat: Cat, list: ResumeBlock[]) => setBlocks((b) => (b ? { ...b, [cat]: list } : b))
  const addBlock = (cat: Cat) => { setCatList(cat, [...blocks[cat], emptyBlock()]); setOpen(`${cat}:${blocks[cat].length}`) }
  const updateBlock = (cat: Cat, i: number, patch: Partial<ResumeBlock>) =>
    setCatList(cat, blocks[cat].map((b, j) => (j === i ? { ...b, ...patch } : b)))
  const removeBlock = (cat: Cat, i: number) => { setCatList(cat, blocks[cat].filter((_, j) => j !== i)); setOpen(null) }
  const moveBlock = (cat: Cat, i: number, dir: -1 | 1) => {
    const list = [...blocks[cat]]
    const j = i + dir
    if (j < 0 || j >= list.length) return
    const tmp = list[i]; list[i] = list[j]; list[j] = tmp
    setCatList(cat, list)
    setOpen(`${cat}:${j}`)
  }

  // \u2500\u2500 \u5757\u62d6\u62fd\uff08\u6761\u72b6\uff1a\u6574\u6761\u53ef\u62d6\uff0c\u63d2\u5165\u7ebf\u6307\u793a\u843d\u70b9\uff09\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  const blockDragStart = (cat: Cat, i: number) => (e: React.DragEvent) => {
    dragBlk.current = { cat, i }
    setDragKey(`${cat}:${i}`)
    setOpen(null)
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', 'blk')
  }
  const blockDragOver = (cat: Cat, i: number) => (e: React.DragEvent) => {
    if (dragBlk.current?.cat !== cat) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    const r = e.currentTarget.getBoundingClientRect()
    const before = e.clientY < r.top + r.height / 2
    setBlkSlot({ cat, slot: before ? i : i + 1 })
  }
  const blockDrop = (cat: Cat) => (e: React.DragEvent) => {
    e.preventDefault()
    const from = dragBlk.current
    const s = blkSlot
    blockDragEnd()
    if (!from || !s || from.cat !== cat || s.cat !== cat) return
    let to = s.slot
    if (from.i < to) to -= 1
    if (to === from.i) return
    const list = [...blocks[cat]]
    const [moved] = list.splice(from.i, 1)
    list.splice(to, 0, moved)
    setCatList(cat, list)
  }
  const blockDragEnd = () => { dragBlk.current = null; setDragKey(null); setBlkSlot(null) }

  // \u2500\u2500 \u5206\u533a\u62d6\u62fd \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
  const secDragStart = (cat: Cat) => (e: React.DragEvent) => {
    dragSec.current = cat
    setSecDragKey(cat)
    setOpen(null)
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', 'sec')
  }
  const secDragOver = (si: number) => (e: React.DragEvent) => {
    if (!dragSec.current) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    const r = e.currentTarget.getBoundingClientRect()
    const before = e.clientY < r.top + r.height / 2
    setSecSlot(before ? si : si + 1)
  }
  const secDrop = () => (e: React.DragEvent) => {
    e.preventDefault()
    const from = dragSec.current
    const slot = secSlot
    secDragEnd()
    if (!from || slot === null) return
    const fi = sectionOrder.indexOf(from)
    let to = slot
    if (fi < to) to -= 1
    if (to === fi) return
    const order = [...sectionOrder]
    order.splice(fi, 1)
    order.splice(to, 0, from)
    setBlocks((b) => (b ? { ...b, section_order: order } : b))
  }
  const secDragEnd = () => { dragSec.current = null; setSecDragKey(null); setSecSlot(null) }

  const save = async () => {
    setSaving(true); setErr(null); setSaved(false)
    try {
      await API.saveResumeBlocks(blocks)
      setSaved(true); window.setTimeout(() => setSaved(false), 3000)
      refreshMeta()
    } catch (e) { setErr((e as Error).message) } finally { setSaving(false) }
  }
  const build = async () => {
    if (!window.confirm('\u5c06\u6839\u636e\u5f53\u524d\u5757\u5e93 + \u81ea\u6211\u63cf\u8ff0\uff0c\u7528 LLM \u91cd\u65b0\u6574\u7406\u5757\u5e93\uff0c\u8986\u76d6\u5f53\u524d\u5185\u5bb9\u3002\u7ee7\u7eed\uff1f')) return
    setBuilding(true); setErr(null)
    try { setBlocks(await API.buildResumeBlocks(blocks.self_description)) }
    catch (e) { setErr((e as Error).message) } finally { setBuilding(false) }
  }
  const handleUpload = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true); setErr(null)
    try {
      await API.uploadResume(file)
      setBlocks(await API.getResumeBlocks())
      refreshMeta()
    } catch (e2) { setErr((e2 as Error).message) }
    finally { setUploading(false); if (fileRef.current) fileRef.current.value = '' }
  }
  const exportPdf = async () => {
    setExporting(true); setErr(null)
    try {
      const label = [blocks.basic_info.name, activeMeta?.name].filter(Boolean).join('_') || 'resume'
      const blob = await API.printResumePdf(buildResumeHtml(blocks), label)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url; a.download = `${label}.pdf`
      document.body.appendChild(a); a.click(); a.remove()
      URL.revokeObjectURL(url)
      refreshMeta()
    } catch (e) { setErr((e as Error).message) } finally { setExporting(false) }
  }
  const switchResume = async (slug: string) => {
    setSwitching(true); setErr(null)
    try {
      await API.saveResumeBlocks(blocks)
      await API.activateResume(slug)
      setBlocks(await API.getResumeBlocks())
      setOpen(null)
      refreshMeta()
    } catch (e) { setErr((e as Error).message) } finally { setSwitching(false) }
  }
  const createResume = async (name: string, target: string) => {
    setSwitching(true); setErr(null)
    try {
      await API.saveResumeBlocks(blocks)
      const item = await API.createResume(name, target, true)
      await API.activateResume(item.slug)
      setBlocks(await API.getResumeBlocks())
      setOpen(null)
      refreshMeta()
    } catch (e) { setErr((e as Error).message) } finally { setSwitching(false) }
  }
  const deleteResume = async (slug: string) => {
    if (!window.confirm('\u5220\u9664\u8fd9\u4efd\u7b80\u5386\uff1f\u4e0d\u53ef\u6062\u590d\u3002')) return
    try { await API.deleteResume(slug); setBlocks(await API.getResumeBlocks()); refreshMeta() }
    catch (e) { setErr((e as Error).message) }
  }
  const updateMeta = (slug: string, patch: { name?: string; target?: string }) => {
    setResumes((r) => (r ? { ...r, items: r.items.map((it) => (it.slug === slug ? { ...it, ...patch } : it)) } : r))
    if (metaTimer.current) window.clearTimeout(metaTimer.current)
    metaTimer.current = window.setTimeout(() => { void API.updateResumeMeta(slug, patch).catch(() => {}) }, 600)
  }
  const deleteExport = async (fname: string) => {
    try { await API.deleteResumeExport(fname); setExportsList((l) => l.filter((x) => x.file !== fname)) }
    catch (e) { setErr((e as Error).message) }
  }

  const detailInput = 'w-full rounded-lg bg-bg-card px-3 py-2 text-sm text-text-1 focus:outline-none focus:ring-1 focus:ring-signal-blue'

  return (
    <div className="relative">
      <DevLabel name="ResumePage" float />
      {err && <div className="mb-4 rounded-lg bg-signal-red/10 px-4 py-2 text-xs text-signal-red">{err}</div>}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input ref={fileRef} type="file" accept=".pdf,.docx" onChange={handleUpload} disabled={uploading} className="hidden" id="resume-upload-input" />
        <label htmlFor="resume-upload-input"
          className={`cursor-pointer rounded-full px-4 py-2 text-sm text-text-1 transition ${uploading ? 'cursor-not-allowed opacity-50' : 'hover:brightness-110'}`}
          style={{ background: 'rgba(255,255,255,0.08)', border: '1px solid rgba(255,255,255,0.14)' }}>
          {uploading ? '\u89e3\u6790\u4e2d\u2026\uff08\u7ea6 1 \u5206\u949f\uff09' : '\u4e0a\u4f20\u7b80\u5386'}</label>
        <button type="button" onClick={() => void save()} disabled={saving}
          className="rounded-full px-5 py-2 text-sm text-white transition hover:brightness-110 disabled:opacity-50"
          style={{ background: '#0a84ff' }}>{saving ? '\u4fdd\u5b58\u4e2d\u2026' : '\u4fdd\u5b58'}</button>
        <button type="button" onClick={() => void exportPdf()} disabled={exporting}
          className="rounded-full px-5 py-2 text-sm text-text-1 transition hover:brightness-110 disabled:opacity-50"
          style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.12)' }}>
          {exporting ? '\u5bfc\u51fa\u4e2d\u2026' : '\u5bfc\u51fa PDF'}</button>
        {saved && <span className="text-sm text-signal-green">{'\u2713 \u5df2\u4fdd\u5b58'}</span>}
        {switching && <span className="text-sm text-text-3">{'\u5207\u6362\u4e2d\u2026'}</span>}
        <span className="ml-auto text-xs text-text-3">{'\u70b9\u6761\u76ee\u5c55\u5f00\u7f16\u8f91\uff0c\u6309\u4f4f\u53ef\u62d6\u52a8\u6392\u5e8f'}</span>
      </div>

      <div className="flex flex-col gap-5 lg:flex-row lg:items-start">
        <SidePanel resumes={resumes} exports={exportsList} busy={switching}
          onSwitch={(s) => void switchResume(s)} onCreate={(n, t) => void createResume(n, t)}
          onDelete={(s) => void deleteResume(s)} onMeta={updateMeta} onDeleteExport={(f) => void deleteExport(f)} />

        <div className="min-w-0 flex-1 space-y-4 lg:max-w-[520px]">
          <Card title={'\u57fa\u672c\u4fe1\u606f'} dev="ResumeBasic">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {BASIC_FIELDS.map(({ key, label }) => (
                <label key={key} className="flex flex-col gap-1.5">
                  <span className="text-xs text-text-3">{label}</span>
                  <input className={inputCls} style={inputStyle} value={blocks.basic_info[key] ?? ''} onChange={(e) => setBasic(key, e.target.value)} />
                </label>
              ))}
            </div>
          </Card>

          <Card title={'\u81ea\u6211\u63cf\u8ff0'} dev="ResumeSelfDesc" action={
            <button type="button" onClick={() => void build()} disabled={building}
              className="rounded-lg px-3 py-1.5 text-xs text-text-1 transition disabled:opacity-40"
              style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)' }}>
              {building ? '\u6574\u7406\u4e2d\u2026' : '\u878d\u5165\u5757\u5e93'}</button>
          }>
            <p className="mb-2 text-xs text-text-3">{'\u8865\u5145\u6ca1\u5199\u5168\u7684\u7ecf\u5386/\u7279\u957f\uff1b\u70b9\u53f3\u4e0a\u7528 LLM \u628a\u8fd9\u6bb5\u63cf\u8ff0\u878d\u8fdb\u4e0b\u65b9\u5757\u5e93\uff08\u8986\u76d6\uff09\u3002'}</p>
            <textarea className={inputCls} style={{ ...inputStyle, minHeight: 110 }} value={blocks.self_description}
              onChange={(e) => setBlocks((b) => (b ? { ...b, self_description: e.target.value } : b))} />
          </Card>

          <Card title={'\u7b80\u5386\u5185\u5bb9'} dev="ResumeSections">
            <p className="mb-4 text-[11px] text-text-3">{'\u70b9\u6761\u76ee\u5c55\u5f00\u7f16\u8f91\uff1b\u6761\u76ee\u548c\u5206\u533a\u90fd\u53ef\u6309\u4f4f\u62d6\u52a8\u6392\u5e8f\uff0c\u84dd\u7ebf\u662f\u843d\u70b9\u3002'}</p>
            <div className="space-y-5" onDrop={secDrop()}>
              {sectionOrder.map((key, si) => {
                const label = catLabel(key)
                const list = blocks[key]
                const isLastSec = si === sectionOrder.length - 1
                return (
                  <div key={key}
                    onDragOver={secDragOver(si)}
                    style={{
                      opacity: secDragKey === key ? 0.35 : 1,
                      borderTop: secSlot === si ? '2px solid #0a84ff' : '2px solid transparent',
                      borderBottom: isLastSec && secSlot === sectionOrder.length ? '2px solid #0a84ff' : '2px solid transparent',
                      transition: 'opacity .15s',
                    }}>
                    <div className="mb-2 flex items-center gap-2">
                      <div draggable title={'\u62d6\u52a8\u8c03\u6574\u5206\u533a\u987a\u5e8f'}
                        onDragStart={secDragStart(key)} onDragEnd={secDragEnd}
                        className="group flex min-w-0 flex-1 cursor-grab select-none items-center gap-2 rounded-lg px-1 py-1 transition active:cursor-grabbing"
                        style={{ margin: '-4px 0 -4px -4px' }}>
                        <span className="text-[13px] leading-none text-text-3 opacity-60 transition group-hover:opacity-100">{'\u2af6'}</span>
                        <span className="text-[13px] font-semibold tracking-wide text-text-1">{label}</span>
                        <span className="rounded-full px-1.5 text-[10px] text-text-3" style={{ background: 'rgba(255,255,255,0.06)' }}>{list.length}</span>
                      </div>
                      <button type="button" onClick={() => addBlock(key)}
                        className="ml-auto rounded-lg px-2.5 py-1 text-[11px] text-signal-bright transition hover:bg-signal-blue/10">{'+ \u6dfb\u52a0'}</button>
                    </div>

                    {list.length === 0 ? (
                      <button type="button" onClick={() => addBlock(key)}
                        className="w-full rounded-[10px] py-2.5 text-[11px] text-text-3 transition hover:text-text-1"
                        style={{ border: '1px dashed rgba(255,255,255,0.14)' }}>{'\u7a7a\u5206\u533a \u00b7 \u70b9\u51fb\u6dfb\u52a0\u4e00\u6761'}</button>
                    ) : (
                      <div className="space-y-1.5" onDrop={blockDrop(key)}>
                        {list.map((blk, i) => {
                          const k = `${key}:${i}`
                          const isOpen = open === k
                          const isLast = i === list.length - 1
                          const slotHere = blkSlot?.cat === key
                          return (
                            <div key={k}
                              onDragOver={blockDragOver(key, i)}
                              style={{
                                borderTop: slotHere && blkSlot?.slot === i ? '2px solid #0a84ff' : '2px solid transparent',
                                borderBottom: isLast && slotHere && blkSlot?.slot === list.length ? '2px solid #0a84ff' : '2px solid transparent',
                              }}>
                              <div className="overflow-hidden rounded-[10px] transition"
                                style={{
                                  background: isOpen ? 'rgba(255,255,255,0.055)' : 'rgba(255,255,255,0.035)',
                                  border: isOpen ? '1px solid rgba(10,132,255,0.4)' : '1px solid rgba(255,255,255,0.07)',
                                  opacity: dragKey === k ? 0.35 : 1,
                                }}>
                                {/* \u6761\uff1a\u6536\u8d77\u6001\u6574\u6761\u53ef\u62d6\uff1b\u70b9\u51fb\u5c55\u5f00 */}
                                <div draggable={!isOpen}
                                  onDragStart={blockDragStart(key, i)} onDragEnd={blockDragEnd}
                                  onClick={() => setOpen(isOpen ? null : k)}
                                  className={`group flex select-none items-center gap-2.5 px-3 py-2.5 ${isOpen ? 'cursor-pointer' : 'cursor-grab active:cursor-grabbing'}`}>
                                  <span className="text-[13px] leading-none text-text-3 opacity-50 transition group-hover:opacity-100">{'\u2af6'}</span>
                                  <span className={`min-w-0 flex-1 truncate text-sm ${blk.title ? 'font-medium text-text-1' : 'text-text-3'}`}>
                                    {blk.title || '\u672a\u547d\u540d\u6761\u76ee'}</span>
                                  {blk.time && <span className="shrink-0 text-[11px] text-text-3" style={{ fontVariantNumeric: 'tabular-nums' }}>{blk.time}</span>}
                                  <span className="shrink-0 text-[10px] text-text-3 transition" style={{ transform: isOpen ? 'rotate(180deg)' : 'none' }}>{'\u25be'}</span>
                                </div>
                                {/* \u5c55\u5f00\u8be6\u60c5\uff08grid-rows \u8fc7\u6e21\uff09 */}
                                <div style={{ display: 'grid', gridTemplateRows: isOpen ? '1fr' : '0fr', transition: 'grid-template-rows .28s ease' }}>
                                  <div className="min-h-0 overflow-hidden">
                                    <div className="space-y-2.5 px-3 pb-3 pt-1">
                                      <div className="flex gap-2">
                                        <input className={detailInput} style={inputStyle} placeholder={'\u6807\u9898\uff08\u5355\u4f4d/\u9879\u76ee/\u6280\u80fd\u540d\uff09'}
                                          value={blk.title} onChange={(e) => updateBlock(key, i, { title: e.target.value })} />
                                        <input className="w-32 shrink-0 rounded-lg bg-bg-card px-3 py-2 text-sm text-text-1 focus:outline-none" style={inputStyle}
                                          placeholder={'\u65f6\u95f4'} value={blk.time} onChange={(e) => updateBlock(key, i, { time: e.target.value })} />
                                      </div>
                                      <textarea className={`${detailInput} leading-relaxed`} style={{ ...inputStyle, minHeight: 120 }}
                                        placeholder={'\u8981\u70b9\uff0c\u6bcf\u884c\u4e00\u6761'} value={blk.bullets.join('\n')}
                                        onChange={(e) => updateBlock(key, i, { bullets: e.target.value.split('\n') })} />
                                      <input className="w-full rounded bg-bg-card px-2.5 py-1.5 text-xs text-text-2 focus:outline-none" style={inputStyle}
                                        placeholder={'\u6982\u62ec\uff1a\u4e00\u53e5\u8bdd\u8bf4\u8fd9\u4e2a\u5757\u662f\u4ec0\u4e48\uff08\u4e0d\u4e0a\u7b80\u5386\uff1bAI \u6309 JD \u6311\u5757\u9760\u5b83\u2014\u2014\u5199\u5f97\u51c6\uff0c\u6311\u5757\u624d\u51c6\uff09'}
                                        value={blk.summary} onChange={(e) => updateBlock(key, i, { summary: e.target.value })} />
                                      <div className="flex items-center gap-1 pt-0.5">
                                        <button type="button" onClick={() => moveBlock(key, i, -1)} disabled={i === 0}
                                          className="rounded px-2 py-1 text-[11px] text-text-3 transition hover:text-text-1 disabled:opacity-30">{'\u2191 \u4e0a\u79fb'}</button>
                                        <button type="button" onClick={() => moveBlock(key, i, 1)} disabled={i === list.length - 1}
                                          className="rounded px-2 py-1 text-[11px] text-text-3 transition hover:text-text-1 disabled:opacity-30">{'\u2193 \u4e0b\u79fb'}</button>
                                        <button type="button" onClick={() => removeBlock(key, i)}
                                          className="ml-auto rounded px-2 py-1 text-[11px] text-signal-red transition hover:brightness-125">{'\u5220\u9664\u6761\u76ee'}</button>
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
            </div>
          </Card>
        </div>

        <div className="min-w-0 flex-1">
          <div className="sticky top-4">
            <div className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-text-3">{'\u5b9e\u65f6\u9884\u89c8\uff08A4\uff09'}<DevLabel name="ResumePreview" /></div>
            <A4Preview html={resumeHtml} />
          </div>
        </div>
      </div>

      <details className="mt-6">
        <summary className="cursor-pointer select-none text-sm text-text-3 transition hover:text-text-1">{'\u5c97\u4f4d\u5b9a\u5236\uff08\u8fdb\u9636\uff09\uff1a\u6309 JD \u7ec4\u5408\u5b9a\u5236\u7b80\u5386 / \u62db\u547c\u8bed'}</summary>
        <div className="mt-4 space-y-5">
          <TemplatesCard />
          <TailorCard />
        </div>
      </details>
    </div>
  )
}
