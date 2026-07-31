import { useEffect, useRef, useState, type ChangeEvent, type ReactNode } from 'react'
import { API, type Profile, type PromptTemplate } from '@/api'
import DevLabel from '@/components/dev/DevLabel'

// \u2500\u2500 Option sets (match boss_search_url.py code maps) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
const CITY_OPTIONS = ['\u5168\u56fd', '\u5317\u4eac', '\u4e0a\u6d77', '\u5e7f\u5dde', '\u6df1\u5733', '\u676d\u5dde', '\u6210\u90fd', '\u5357\u4eac', '\u6b66\u6c49', '\u897f\u5b89', '\u91cd\u5e86', '\u5929\u6d25', '\u82cf\u5dde', '\u5408\u80a5', '\u90d1\u5dde', '\u957f\u6c99', '\u6d4e\u5357', '\u9752\u5c9b', '\u53a6\u95e8', '\u5b81\u6ce2', '\u65e0\u9521']
const EXPERIENCE_OPTIONS = ['\u7ecf\u9a8c\u4e0d\u9650', '\u5728\u6821\u751f', '\u5e94\u5c4a\u751f', '1\u5e74\u4ee5\u5185', '1-3\u5e74', '3-5\u5e74', '5-10\u5e74', '10\u5e74\u4ee5\u4e0a']
const DEGREE_OPTIONS = ['\u521d\u4e2d\u53ca\u4ee5\u4e0b', '\u4e2d\u4e13', '\u9ad8\u4e2d', '\u5927\u4e13', '\u672c\u79d1', '\u7855\u58eb', '\u535a\u58eb']
const SALARY_OPTIONS = ['3K\u4ee5\u4e0b', '3-5K', '5-10K', '10-20K', '20-50K', '50K\u4ee5\u4e0a']
const JOB_TYPE_OPTIONS = ['\u5168\u804c', '\u5b9e\u4e60', '\u517c\u804c']
const FINANCING_OPTIONS = ['\u672a\u878d\u8d44', '\u5929\u4f7f\u8f6e', 'A\u8f6e', 'B\u8f6e', 'C\u8f6e', 'D\u8f6e\u53ca\u4ee5\u4e0a', '\u5df2\u4e0a\u5e02', '\u4e0d\u9700\u8981\u878d\u8d44']
const SCALE_OPTIONS = ['0-20\u4eba', '20-99\u4eba', '100-499\u4eba', '500-999\u4eba', '1000-9999\u4eba', '10000\u4eba\u4ee5\u4e0a']
const LLM_PROVIDERS = [
  { value: 'claude_cli', label: 'Claude CLI' },
  { value: 'anthropic_api', label: 'Anthropic API' },
  { value: 'openai_compatible', label: 'OpenAI Compatible' },
  { value: 'ollama', label: 'Ollama (\u672c\u5730)' },
]

const inputCls = 'w-full rounded-lg bg-bg-card2 px-3 py-2 text-sm text-text-1 focus:outline-none focus:ring-1 focus:ring-signal-blue'
const inputStyle: React.CSSProperties = { border: '1px solid rgba(255,255,255,0.08)', letterSpacing: '-0.224px' }

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

function FieldRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2">
      <label className="text-xs font-medium text-text-3" style={{ letterSpacing: '-0.12px' }}>{label}</label>
      {children}
    </div>
  )
}

function ChipSelect({
  options,
  selected,
  onChange,
  multi = true,
}: {
  options: string[]
  selected: string[]
  onChange: (next: string[]) => void
  multi?: boolean
}) {
  const toggle = (opt: string) => {
    if (multi) onChange(selected.includes(opt) ? selected.filter((x) => x !== opt) : [...selected, opt])
    else onChange(selected.includes(opt) ? [] : [opt])
  }
  return (
    <div className="flex flex-wrap gap-2">
      {options.map((opt) => {
        const active = selected.includes(opt)
        return (
          <button
            key={opt}
            type="button"
            onClick={() => toggle(opt)}
            className={`rounded-full px-3 py-1 text-xs font-medium transition ${active ? '' : 'hover:brightness-150'}`}
            style={{
              background: active ? 'rgba(10,132,255,0.18)' : 'rgba(255,255,255,0.06)',
              color: active ? '#2997ff' : '#adadb8',
              border: active ? '1px solid rgba(10,132,255,0.4)' : '1px solid rgba(255,255,255,0.08)',
              letterSpacing: '-0.12px',
            }}
          >
            {opt}
          </button>
        )
      })}
    </div>
  )
}

function SaveButton({ saving, saved, onClick, savedText }: { saving: boolean; saved: boolean; onClick: () => void; savedText?: string }) {
  return (
    <div className="mt-6 flex flex-wrap items-center gap-4 pt-5" style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
      <button
        type="button"
        onClick={onClick}
        disabled={saving}
        className="rounded-full px-6 py-2 text-sm text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50"
        style={{ background: '#0a84ff', letterSpacing: '-0.224px' }}
      >
        {saving ? '\u4fdd\u5b58\u4e2d\u2026' : '\u4fdd\u5b58'}
      </button>
      {saved && <span className="text-sm text-signal-green" style={{ letterSpacing: '-0.224px' }}>{savedText ?? '\u2713 \u5df2\u4fdd\u5b58'}</span>}
    </div>
  )
}

// \u2500\u2500 Tab 1: \u6c42\u804c\u504f\u597d (search filters only \u2192 profile.yaml) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
interface PrefState {
  salary: string
  keywords: string
  cities: string[]
  experience: string[]
  degree: string[]
  job_types: string[]
  financing: string[]
  scale: string[]
}

function PreferencesTab() {
  const [form, setForm] = useState<PrefState>({
    salary: '', keywords: '', cities: [], experience: [], degree: [], job_types: [], financing: [], scale: [],
  })
  const [readOnly, setReadOnly] = useState<{ districts?: string[]; position_types?: string[] }>({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [previewing, setPreviewing] = useState(false)

  useEffect(() => {
    setLoading(true)
    API.getProfile()
      .then((p) => {
        setForm({
          salary: p.salary ?? '',
          keywords: (p.keywords ?? []).join(', '),
          cities: p.cities ?? [],
          experience: p.experience ?? [],
          degree: p.degree ?? [],
          job_types: p.job_types ?? [],
          financing: p.financing ?? [],
          scale: p.scale ?? [],
        })
        setReadOnly({ districts: p.districts, position_types: p.position_types })
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const setChip = (field: 'cities' | 'experience' | 'degree' | 'job_types' | 'financing' | 'scale') => (next: string[]) =>
    setForm((f) => ({ ...f, [field]: next }))
  const parseArr = (s: string): string[] => s.split(',').map((t) => t.trim()).filter(Boolean)

  const handleSave = async () => {
    setSaving(true); setSaved(false); setError(null)
    try {
      const payload: Profile = {
        salary: form.salary,
        keywords: parseArr(form.keywords),
        cities: form.cities,
        experience: form.experience,
        degree: form.degree,
        job_types: form.job_types,
        financing: form.financing,
        scale: form.scale,
      }
      await API.saveProfile(payload)
      setSaved(true)
      window.setTimeout(() => setSaved(false), 3000)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const handlePreview = async () => {
    setPreviewing(true); setPreviewUrl(null)
    try {
      const res = await API.previewSearch()
      setPreviewUrl(res.url)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setPreviewing(false)
    }
  }

  if (loading) return <p className="text-sm text-text-3">{'\u52a0\u8f7d\u4e2d\u2026'}</p>

  return (
    <Card title={'\u6c42\u804c\u504f\u597d'} dev="PreferencesTab">
      {error && <p className="mb-4 rounded-lg bg-signal-red/10 px-3 py-2 text-xs text-signal-red">{error}</p>}
      <div className="space-y-5">
        <FieldRow label={'\u804c\u4f4d\u5173\u952e\u8bcd\uff08\u9017\u53f7\u5206\u9694\uff09'}>
          <input className={inputCls} style={inputStyle} value={form.keywords} onChange={(e) => setForm((f) => ({ ...f, keywords: e.target.value }))} placeholder={'Python, \u540e\u7aef, AI'} />
        </FieldRow>
        <FieldRow label={'\u6c42\u804c\u57ce\u5e02'}>
          <ChipSelect options={CITY_OPTIONS} selected={form.cities} onChange={setChip('cities')} />
        </FieldRow>
        <FieldRow label={'\u85aa\u8d44\u8303\u56f4'}>
          <ChipSelect options={SALARY_OPTIONS} selected={form.salary ? [form.salary] : []} onChange={(next) => setForm((f) => ({ ...f, salary: next[0] ?? '' }))} multi={false} />
        </FieldRow>
        <FieldRow label={'\u7ecf\u9a8c\u8981\u6c42'}>
          <ChipSelect options={EXPERIENCE_OPTIONS} selected={form.experience} onChange={setChip('experience')} />
        </FieldRow>
        <FieldRow label={'\u5b66\u5386\u8981\u6c42'}>
          <ChipSelect options={DEGREE_OPTIONS} selected={form.degree} onChange={setChip('degree')} />
        </FieldRow>
        <FieldRow label={'\u804c\u4f4d\u7c7b\u578b'}>
          <ChipSelect options={JOB_TYPE_OPTIONS} selected={form.job_types} onChange={setChip('job_types')} />
        </FieldRow>
        <FieldRow label={'\u516c\u53f8\u89c4\u6a21'}>
          <ChipSelect options={SCALE_OPTIONS} selected={form.scale} onChange={setChip('scale')} />
        </FieldRow>
        <FieldRow label={'\u878d\u8d44\u9636\u6bb5'}>
          <ChipSelect options={FINANCING_OPTIONS} selected={form.financing} onChange={setChip('financing')} />
        </FieldRow>

        {((readOnly.districts?.length ?? 0) > 0 || (readOnly.position_types?.length ?? 0) > 0) && (
          <div className="space-y-1 rounded-lg px-4 py-3 text-xs text-text-3" style={{ background: '#2c2c2e', letterSpacing: '-0.12px' }}>
            {(readOnly.districts?.length ?? 0) > 0 && <p>{'\u533a\u57df\u7b5b\u9009\uff08\u53ea\u8bfb\uff09\uff1a'}{readOnly.districts?.join(', ')}</p>}
            {(readOnly.position_types?.length ?? 0) > 0 && <p>{'\u804c\u4f4d\u7c7b\u578b ID\uff08\u53ea\u8bfb\uff09\uff1a'}{readOnly.position_types?.join(', ')}</p>}
          </div>
        )}
      </div>

      <div className="mt-6 flex flex-wrap items-center gap-4 pt-5" style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
        <button type="button" onClick={() => void handleSave()} disabled={saving} className="rounded-full px-6 py-2 text-sm text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-50" style={{ background: '#0a84ff', letterSpacing: '-0.224px' }}>
          {saving ? '\u4fdd\u5b58\u4e2d\u2026' : '\u4fdd\u5b58'}
        </button>
        <button type="button" onClick={() => void handlePreview()} disabled={previewing} className="rounded-lg bg-bg-card2 px-4 py-2 text-sm text-text-2 transition hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-50" style={{ border: '1px solid rgba(255,255,255,0.08)', letterSpacing: '-0.224px' }}>
          {previewing ? '\u6784\u9020\u4e2d\u2026' : '\u9884\u89c8\u641c\u7d22 URL'}
        </button>
        {saved && <span className="text-sm text-signal-green" style={{ letterSpacing: '-0.224px' }}>{'\u2713 \u5df2\u4fdd\u5b58'}</span>}
      </div>

      {previewUrl && (
        <div className="mt-4 rounded-lg p-4" style={{ background: '#2c2c2e', border: '1px solid rgba(255,255,255,0.06)' }}>
          <p className="mb-2 text-xs font-medium text-text-3" style={{ letterSpacing: '-0.12px' }}>{'\u6784\u9020\u7684\u641c\u7d22 URL\uff08\u57fa\u4e8e\u5df2\u4fdd\u5b58\u7684 profile\uff09'}</p>
          <p className="break-all font-mono text-xs text-signal-bright" style={{ lineHeight: '1.6' }}>{previewUrl}</p>
          <div className="mt-3 flex gap-2">
            <button type="button" onClick={() => API.browseUrl(previewUrl)} className="rounded-lg bg-bg-card2 px-3 py-1.5 text-xs text-text-2 transition hover:text-text-1" style={{ border: '1px solid rgba(255,255,255,0.08)' }}>{'\u5728\u6d4f\u89c8\u5668\u6253\u5f00'}</button>
            <button type="button" onClick={() => void navigator.clipboard.writeText(previewUrl)} className="rounded-lg bg-bg-card2 px-3 py-1.5 text-xs text-text-2 transition hover:text-text-1" style={{ border: '1px solid rgba(255,255,255,0.08)' }}>{'\u590d\u5236'}</button>
          </div>
        </div>
      )}
    </Card>
  )
}

// \u2500\u2500 Tab 2: \u6a21\u578b (capability routing + per-tool provider, single source) \u2500\u2500\u2500\u2500\u2500
function ModelTab() {
  const [capFast, setCapFast] = useState('')
  const [capBalanced, setCapBalanced] = useState('')
  const [capPowerful, setCapPowerful] = useState('')
  const [toolScoreJob, setToolScoreJob] = useState('')
  const [toolAnalyzeIntent, setToolAnalyzeIntent] = useState('')
  const [available, setAvailable] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    API.getLlmConfig()
      .then((llm) => {
        setCapFast(llm.capabilities.fast ?? '')
        setCapBalanced(llm.capabilities.balanced ?? '')
        setCapPowerful(llm.capabilities.powerful ?? '')
        setToolScoreJob(llm.tool_providers.score_job ?? '')
        setToolAnalyzeIntent(llm.tool_providers.analyze_intent ?? '')
        setAvailable(llm.available_providers ?? [])
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  const handleSave = async () => {
    setSaving(true); setSaved(false); setError(null)
    try {
      await API.saveLlmConfig({
        capabilities: { fast: capFast, balanced: capBalanced, powerful: capPowerful },
        tool_providers: { score_job: toolScoreJob || null, analyze_intent: toolAnalyzeIntent || null },
      })
      setSaved(true)
      window.setTimeout(() => setSaved(false), 3000)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <p className="text-sm text-text-3">{'\u52a0\u8f7d\u4e2d\u2026'}</p>

  const providerOptions = [{ value: '', label: '\u9ed8\u8ba4\uff08\u6309\u80fd\u529b\u8def\u7531\uff09' }, ...available.map((p) => ({ value: p, label: p }))]
  const selectCls = inputCls

  return (
    <Card title={'\u6a21\u578b\u914d\u7f6e'} dev="ModelTab">
      {error && <p className="mb-4 rounded-lg bg-signal-red/10 px-3 py-2 text-xs text-signal-red">{error}</p>}
      <div className="space-y-5">
        <div className="grid grid-cols-3 gap-4">
          <FieldRow label={'\u5feb\u901f'}>
            <select className={selectCls} style={inputStyle} value={capFast} onChange={(e) => setCapFast(e.target.value)}>
              {available.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </FieldRow>
          <FieldRow label={'\u5747\u8861'}>
            <select className={selectCls} style={inputStyle} value={capBalanced} onChange={(e) => setCapBalanced(e.target.value)}>
              {available.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </FieldRow>
          <FieldRow label={'\u5f3a\u529b'}>
            <select className={selectCls} style={inputStyle} value={capPowerful} onChange={(e) => setCapPowerful(e.target.value)}>
              {available.map((p) => <option key={p} value={p}>{p}</option>)}
            </select>
          </FieldRow>
        </div>
        <div style={{ borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: '1.25rem' }}>
          <p className="mb-3 text-xs text-text-3">{'\u6307\u5b9a Tool \u4f7f\u7528\u7684 Provider\uff08\u53ef\u9009\uff0c\u7a7a\u8868\u793a\u8d70\u80fd\u529b\u8def\u7531\uff09'}</p>
          <div className="grid grid-cols-2 gap-4">
            <FieldRow label={'score_job'}>
              <select className={selectCls} style={inputStyle} value={toolScoreJob} onChange={(e) => setToolScoreJob(e.target.value)}>
                {providerOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </FieldRow>
            <FieldRow label={'analyze_intent'}>
              <select className={selectCls} style={inputStyle} value={toolAnalyzeIntent} onChange={(e) => setToolAnalyzeIntent(e.target.value)}>
                {providerOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </FieldRow>
          </div>
        </div>
      </div>
      <SaveButton saving={saving} saved={saved} onClick={() => void handleSave()} savedText={'\u2713 \u5df2\u5199\u5165 config.yaml'} />
    </Card>
  )
}

// \u2500\u2500 Tab 3: \u73af\u5883 & Session \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
interface OnboardingStatus {
  profile: boolean; resume: boolean; session: boolean; llm_provider: boolean
  all_ok: boolean
}
interface SessionResult { valid: boolean | null; name?: string; reason?: string; browser_open?: boolean }

const STATUS_ITEMS: Array<{ key: keyof Omit<OnboardingStatus, 'all_ok'>; label: string; desc: string }> = [
  { key: 'profile', label: 'Profile \u914d\u7f6e', desc: 'data/profile.yaml' },
  { key: 'resume', label: '\u7b80\u5386 YAML', desc: 'data/resume_blocks.yaml' },
  { key: 'session', label: '\u6d4f\u89c8\u5668 Session', desc: 'data/browser_profile' },
  { key: 'llm_provider', label: 'LLM \u63d0\u4f9b\u5546', desc: 'Claude CLI / API' },
]

function StatusCard({ label, desc, ready }: { label: string; desc: string; ready: boolean }) {
  return (
    <div className="flex items-center gap-3 rounded-xl bg-bg-card2 p-4">
      <span className={`text-base ${ready ? 'text-signal-green' : 'text-signal-red'}`}>{ready ? '\u2713' : '\u2717'}</span>
      <div>
        <p className="text-sm font-medium text-text-1" style={{ letterSpacing: '-0.224px' }}>{label}</p>
        <p className="font-mono text-xs text-text-3" style={{ letterSpacing: '-0.12px' }}>{desc}</p>
      </div>
    </div>
  )
}

function EnvironmentTab() {
  const [status, setStatus] = useState<OnboardingStatus | null>(null)
  const [loading, setLoading] = useState(false)
  const [uploadError, setUploadError] = useState<string | null>(null)
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [checking, setChecking] = useState(false)
  const [opening, setOpening] = useState(false)
  const [confirming, setConfirming] = useState(false)
  const [openingBoss, setOpeningBoss] = useState(false)
  const [loginOpen, setLoginOpen] = useState(false)
  const [result, setResult] = useState<SessionResult | null>(null)

  const loadStatus = () => {
    setLoading(true)
    API.getOnboarding().then((d) => setStatus(d as unknown as OnboardingStatus)).catch(() => {}).finally(() => setLoading(false))
  }
  useEffect(() => { loadStatus() }, [])

  const handleOpenBoss = async () => {
    setOpeningBoss(true)
    try { await API.openBossBrowser() } catch (e) { setResult({ valid: false, reason: String(e) }) } finally { setOpeningBoss(false) }
  }
  const handleCheck = async () => {
    setChecking(true)
    try { const r = (await API.checkSession()) as SessionResult; setResult(r); if (r.valid) loadStatus() }
    catch (e) { setResult({ valid: false, reason: String(e) }) } finally { setChecking(false) }
  }
  const handleOpenLogin = async () => {
    setOpening(true)
    try {
      const r = await API.openLogin()
      if (r.status === 'browser_opened' || r.status === 'already_open') setLoginOpen(true)
      else setResult({ valid: false, reason: r.reason ?? '\u6253\u5f00\u767b\u5f55\u6d4f\u89c8\u5668\u5931\u8d25' })
    } catch (e) { setResult({ valid: false, reason: String(e) }) } finally { setOpening(false) }
  }
  const handleConfirmLogin = async () => {
    setConfirming(true)
    try {
      const r = await API.confirmLogin()
      setLoginOpen(false)
      if (r.session) { setResult(r.session as unknown as SessionResult); loadStatus() }
      else setResult({ valid: false, reason: r.reason ?? '\u786e\u8ba4\u767b\u5f55\u5931\u8d25' })
    } catch (e) { setResult({ valid: false, reason: String(e) }) } finally { setConfirming(false) }
  }
  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true); setUploadError(null)
    try { await API.uploadResume(file); loadStatus() }
    catch (err) { setUploadError((err as Error).message) }
    finally { setUploading(false); if (fileInputRef.current) fileInputRef.current.value = '' }
  }

  let sessionNode: ReactNode
  if (!result) sessionNode = <p className="mt-1 text-xs text-text-3 opacity-60">{'\u70b9\u51fb\u6309\u94ae\u901a\u8fc7\u6d4f\u89c8\u5668\u9a8c\u8bc1\u767b\u5f55\u72b6\u6001'}</p>
  else if (result.valid === null) sessionNode = <p className="mt-1 text-xs text-signal-amber">{result.reason}</p>
  else if (result.valid) sessionNode = <p className="mt-1 text-sm font-semibold text-signal-green">{'\u5df2\u767b\u5f55'}{result.name ? ` \u00b7 ${result.name}` : ''}</p>
  else sessionNode = <p className="mt-1 text-xs text-signal-red">{result.reason ?? 'Session \u5df2\u5931\u6548'}</p>

  return (
    <div className="space-y-5">
      {status?.all_ok && (
        <div className="rounded-xl bg-signal-green/10 px-4 py-3 text-sm text-signal-green" style={{ letterSpacing: '-0.224px' }}>
          {'\u2713 \u7cfb\u7edf\u5df2\u5c31\u7eea\uff0c\u53ef\u4ee5\u5f00\u59cb\u8fd0\u884c\uff01'}
        </div>
      )}

      <Card title={'\u7cfb\u7edf\u72b6\u6001'} dev="SystemStatus">
        {loading ? <p className="text-sm text-text-3">{'\u52a0\u8f7d\u4e2d\u2026'}</p> : status ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {STATUS_ITEMS.map((item) => <StatusCard key={item.key} label={item.label} desc={item.desc} ready={Boolean(status[item.key])} />)}
          </div>
        ) : <p className="text-sm text-text-3">{'\u65e0\u6cd5\u83b7\u53d6\u72b6\u6001'}</p>}
      </Card>

      <Card title={'Boss\u76f4\u8058 Session'} dev="SessionCard">
        <div className="flex items-center gap-4">
          <div className="min-w-0 flex-1">{sessionNode}</div>
          <button type="button" onClick={() => void handleOpenBoss()} disabled={openingBoss} className="shrink-0 rounded-lg px-3 py-2 text-xs text-text-3 transition hover:text-text-1 disabled:opacity-40" style={{ letterSpacing: '-0.12px' }}>
            {openingBoss ? '\u6253\u5f00\u4e2d\u2026' : '\u6253\u5f00 Boss'}
          </button>
          <button type="button" onClick={() => void handleCheck()} disabled={checking || opening || confirming} className="shrink-0 rounded-lg px-4 py-2 text-xs font-medium text-text-1 transition disabled:opacity-40" style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid rgba(255,255,255,0.1)', letterSpacing: '-0.12px' }}>
            {checking ? '\u68c0\u67e5\u4e2d\uff08\u7ea6 10 \u79d2\uff09\u2026' : result ? '\u91cd\u65b0\u68c0\u67e5' : '\u68c0\u67e5 Session'}
          </button>
        </div>
        {((result !== null && result.valid === false) || loginOpen) && (
          <div className="mt-3 flex items-center gap-3">
            {loginOpen ? (
              <>
                <p className="text-xs text-signal-amber" style={{ letterSpacing: '-0.12px' }}>{'\u6d4f\u89c8\u5668\u5df2\u6253\u5f00\uff0c\u767b\u5f55\u540e\u70b9\u300c\u5b8c\u6210\u767b\u5f55\u300d'}</p>
                <button type="button" onClick={() => void handleConfirmLogin()} disabled={confirming} className="shrink-0 rounded-full px-4 py-1.5 text-xs text-white transition hover:brightness-110 disabled:opacity-50" style={{ background: '#0a84ff', letterSpacing: '-0.12px' }}>
                  {confirming ? '\u4fdd\u5b58\u4e2d\u2026' : '\u5b8c\u6210\u767b\u5f55'}
                </button>
              </>
            ) : (
              <button type="button" onClick={() => void handleOpenLogin()} disabled={opening} className="shrink-0 rounded-full px-4 py-1.5 text-xs text-white transition hover:brightness-110 disabled:opacity-50" style={{ background: '#0a84ff', letterSpacing: '-0.12px' }}>
                {opening ? '\u6253\u5f00\u4e2d\u2026' : '\u6253\u5f00\u767b\u5f55\u6d4f\u89c8\u5668'}
              </button>
            )}
          </div>
        )}
      </Card>

      <Card title={'LLM \u63d0\u4f9b\u5546'} dev="LLMProviders">
        <p className="mb-4 text-xs text-text-3" style={{ letterSpacing: '-0.12px' }}>{'\u63d0\u793a\uff1a\u80fd\u529b\u8def\u7531\u7684\u5177\u4f53 Provider \u5728\u300c\u6a21\u578b\u300d\u6807\u7b7e\u9875\u914d\u7f6e\u3002\u6b64\u5904\u4ec5\u4f9b\u53c2\u8003\u53ef\u7528\u9879\u3002'}</p>
        <div className="flex flex-wrap gap-2">
          {LLM_PROVIDERS.map(({ value, label }) => (
            <span key={value} className="rounded-full px-3 py-1 text-xs" style={{ background: 'rgba(255,255,255,0.06)', color: '#adadb8', border: '1px solid rgba(255,255,255,0.08)' }}>{label}</span>
          ))}
        </div>
      </Card>

      <Card title={'\u4e0a\u4f20\u7ed3\u6784\u5316\u7b80\u5386'} dev="ResumeUpload">
        <p className="mb-4 text-xs text-text-3" style={{ letterSpacing: '-0.12px' }}>{'\u4e0a\u4f20 PDF \u6216 DOCX \u7b80\u5386\u6587\u4ef6\uff0c\u7cfb\u7edf\u5c06\u81ea\u52a8\u89e3\u6790\u751f\u6210 resume_base.yaml\uff0c\u7528\u4e8e AI \u5b9a\u5236\u5316\u7b80\u5386\u3002'}</p>
        {uploadError && <p className="mb-3 rounded-lg bg-signal-red/10 px-3 py-2 text-xs text-signal-red">{uploadError}</p>}
        <div className="cursor-pointer rounded-xl bg-bg-card2 p-5 text-center transition hover:bg-bg-hover" style={{ border: '1px dashed rgba(255,255,255,0.12)' }} onClick={() => fileInputRef.current?.click()}>
          <p className="text-sm text-text-2" style={{ letterSpacing: '-0.224px' }}>{uploading ? '\u4e0a\u4f20\u4e2d\u2026' : '\u70b9\u51fb\u9009\u62e9\u6587\u4ef6\uff08PDF / DOCX\uff09'}</p>
          <p className="mt-1 text-xs text-text-3" style={{ letterSpacing: '-0.12px' }}>{'\u652f\u6301 .pdf \u548c .docx\uff0c\u6700\u5927 10 MB'}</p>
          <input ref={fileInputRef} type="file" accept=".pdf,.docx" className="hidden" onChange={(e) => void handleFileChange(e)} />
        </div>
      </Card>
    </div>
  )
}

// \u2500\u2500 Root \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500

// -- Tab: Prompt \u6a21\u677f\uff08\u53ef\u7f16\u8f91 system/task prompt\uff09--------------------------------
const PROMPT_LABELS: Record<string, string> = {
  system: '\u7cfb\u7edf\u89d2\u8272',
  score_job: '\u8bc4\u5206',
  analyze_intent: '\u610f\u56fe\u5206\u6790',
  generate_reply: '\u56de\u590d\u751f\u6210',
  resume_parse: '\u7b80\u5386\u89e3\u6790(\u6587\u672c)',
  resume_parse_vision: '\u7b80\u5386\u89e3\u6790(\u89c6\u89c9)',
  resume_build: '\u7b80\u5386\u5757\u5e93',
  resume_tailor: '\u7b80\u5386\u5b9a\u5236',
  resume_greeting: '\u62db\u547c\u8bed',
}
const PROMPT_DESC: Record<string, string> = {
  system: '\u7cfb\u7edf\u89d2\u8272 \u00b7 \u6240\u6709 AI \u73af\u8282\u5171\u7528',
  score_job: '\u8bc4\u5206 \u00b7 W1 \u804c\u4f4d\u6253\u5206',
  analyze_intent: '\u610f\u56fe\u5206\u6790 \u00b7 W2 HR \u610f\u56fe\u5224\u65ad',
  generate_reply: '\u56de\u590d\u751f\u6210 \u00b7 \u7ed9 HR \u7684\u8349\u7a3f',
  resume_parse: '\u7b80\u5386\u89e3\u6790(\u6587\u672c) \u00b7 pdfminer \u6587\u672c\u515c\u5e95\u8def\u5f84',
  resume_parse_vision: '\u7b80\u5386\u89e3\u6790(\u89c6\u89c9) \u00b7 \u8bfb\u7b80\u5386\u56fe\u7247\uff0c\u6392\u7248\u578b\u7b80\u5386\u4e3b\u8def\u5f84',
  resume_build: '\u7b80\u5386\u5757\u5e93 \u00b7 \u89e3\u6790\u7b80\u5386\u6574\u7406\u6210\u7ed3\u6784\u5316\u79ef\u6728',
  resume_tailor: '\u7b80\u5386\u5b9a\u5236 \u00b7 \u6309\u5c97\u4f4d\u4ece\u79ef\u6728\u5e93\u6311\u5757\u5fae\u8c03',
  resume_greeting: '\u62db\u547c\u8bed \u00b7 \u6309\u5c97\u4f4d\u751f\u6210\u6253\u62db\u547c\u8bed',
}

function PromptTemplatesTab() {
  const [prompts, setPrompts] = useState<PromptTemplate[]>([])
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [active, setActive] = useState('system')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState<Record<string, string>>({})
  const [err, setErr] = useState<Record<string, string>>({})

  const load = () => {
    setLoading(true)
    API.getPrompts()
      .then((ps) => {
        setPrompts(ps)
        setDrafts(Object.fromEntries(ps.map((p) => [p.name, p.content])))
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const save = async (name: string) => {
    setBusy(name); setErr((e) => ({ ...e, [name]: '' })); setNote((m) => ({ ...m, [name]: '' }))
    try {
      await API.savePrompt(name, drafts[name] ?? '')
      setNote((m) => ({ ...m, [name]: '\u2713 \u5df2\u4fdd\u5b58' }))
      load()
    } catch (e) {
      setErr((er) => ({ ...er, [name]: (e as Error).message }))
    } finally { setBusy(null) }
  }

  const reset = async (name: string) => {
    setBusy(name); setErr((e) => ({ ...e, [name]: '' })); setNote((m) => ({ ...m, [name]: '' }))
    try {
      await API.resetPrompt(name)
      setNote((m) => ({ ...m, [name]: '\u2713 \u5df2\u6062\u590d\u9ed8\u8ba4' }))
      load()
    } catch (e) {
      setErr((er) => ({ ...er, [name]: (e as Error).message }))
    } finally { setBusy(null) }
  }

  if (loading && !prompts.length) {
    return <Card title={'Prompt \u6a21\u677f'} dev="PromptTemplatesTab"><p className="text-sm text-text-3">{'\u52a0\u8f7d\u4e2d\u2026'}</p></Card>
  }

  const p = prompts.find((x) => x.name === active)
  const dirty = p ? (drafts[p.name] ?? '') !== p.content : false

  return (
    <Card title={'Prompt \u6a21\u677f'} dev="PromptTemplatesTab">
      {/* \u9009\u9879\u5361\uff1a\u77ed\u6807\u7b7e\u4e00\u884c */}
      <div className="mb-4 inline-flex flex-wrap gap-1 rounded-xl bg-bg-card2 p-1" style={{ border: '1px solid rgba(255,255,255,0.06)' }}>
        {prompts.map((t) => (
          <button key={t.name} type="button" onClick={() => setActive(t.name)}
            className={`flex items-center gap-1.5 rounded-lg px-4 py-1.5 text-sm font-medium transition ${active === t.name ? 'text-white' : 'text-text-3 hover:text-text-1'}`}
            style={active === t.name ? { background: '#0a84ff' } : undefined}>
            {PROMPT_LABELS[t.name] ?? t.name}
            {t.modified && <span className="inline-block h-1.5 w-1.5 rounded-full" style={{ background: active === t.name ? '#fff' : '#f5a623' }} />}
          </button>
        ))}
      </div>
      {p && (
        <div>
          <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="text-sm font-semibold text-text-1">{PROMPT_DESC[p.name] ?? p.name}</span>
            <code className="text-xs text-text-3">{p.name}</code>
            {p.modified && <span className="rounded-full px-2 py-0.5 text-xs" style={{ background: 'rgba(245,166,35,0.15)', color: '#f5a623' }}>{'\u25cf \u5df2\u4fee\u6539'}</span>}
          </div>
          {p.placeholders.length > 0 && (
            <p className="mb-2 text-xs text-text-3">
              {'\u5fc5\u987b\u4fdd\u7559\u5360\u4f4d\u7b26\uff1a'}<code className="text-signal-blue">{p.placeholders.map((ph) => '{{' + ph + '}}').join('  ')}</code>
            </p>
          )}
          <textarea
            className={inputCls}
            style={{ ...inputStyle, resize: 'vertical', minHeight: '560px', fontFamily: 'ui-monospace, SFMono-Regular, monospace', lineHeight: '1.6', fontSize: '13px' }}
            value={drafts[p.name] ?? ''}
            onChange={(e) => setDrafts((d) => ({ ...d, [p.name]: e.target.value }))}
            spellCheck={false}
          />
          {err[p.name] && <p className="mt-2 rounded-lg bg-signal-red/10 px-3 py-2 text-xs text-signal-red">{err[p.name]}</p>}
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <button type="button" onClick={() => void save(p.name)} disabled={busy === p.name || !dirty}
              className="rounded-full px-5 py-1.5 text-sm text-white transition hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
              style={{ background: '#0a84ff', letterSpacing: '-0.224px' }}>
              {busy === p.name ? '\u4fdd\u5b58\u4e2d\u2026' : '\u4fdd\u5b58'}
            </button>
            <button type="button" onClick={() => void reset(p.name)} disabled={busy === p.name || !p.modified}
              className="rounded-lg bg-bg-card2 px-4 py-1.5 text-sm text-text-2 transition hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-40"
              style={{ border: '1px solid rgba(255,255,255,0.08)' }}>
              {'\u6062\u590d\u9ed8\u8ba4'}
            </button>
            {note[p.name] && <span className="text-sm text-signal-green" style={{ letterSpacing: '-0.224px' }}>{note[p.name]}</span>}
          </div>
        </div>
      )}
    </Card>
  )
}

// -- Prompt \u6ce8\u5165\uff08\u5168\u5c40 + 3 \u4efb\u52a1\u5c42\uff0c\u72ec\u7acb\u4fdd\u5b58\uff09--------------------------------------
function InjectionSection() {
  const [inj, setInj] = useState({ global: '', score_job: '', analyze_intent: '', generate_reply: '' })
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    setLoading(true)
    API.getProfile()
      .then((p) => setInj({
        global: p.prompt_injection?.global ?? '',
        score_job: p.prompt_injection?.score_job ?? '',
        analyze_intent: p.prompt_injection?.analyze_intent ?? '',
        generate_reply: p.prompt_injection?.generate_reply ?? '',
      }))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const save = async () => {
    setSaving(true); setSaved(false); setError(null)
    try {
      await API.saveProfile({ prompt_injection: inj })
      setSaved(true); window.setTimeout(() => setSaved(false), 3000)
    } catch (e) { setError((e as Error).message) } finally { setSaving(false) }
  }

  const box = (key: keyof typeof inj, label: string, ph: string) => (
    <FieldRow label={label}>
      <textarea className={inputCls} style={{ ...inputStyle, resize: 'vertical', minHeight: '64px' }}
        value={inj[key]} onChange={(e) => setInj((s) => ({ ...s, [key]: e.target.value }))} placeholder={ph} rows={2} />
    </FieldRow>
  )

  if (loading) return null

  return (
    <Card title={'Prompt \u6ce8\u5165'} dev="InjectionSection">
      {error && <p className="mb-4 rounded-lg bg-signal-red/10 px-3 py-2 text-xs text-signal-red">{error}</p>}
      <p className="mb-4 text-xs text-text-3" style={{ letterSpacing: '-0.12px', lineHeight: '1.6' }}>
        {'\u5f80\u63d0\u793a\u8bcd\u6a21\u677f\u5c3e\u90e8\u8ffd\u52a0\u4f60\u7684\u6307\u4ee4\u3002\u5168\u5c40\u6ce8\u5165\u8fdb\u6240\u6709 AI \u73af\u8282\uff0c\u5176\u4f59\u5404\u81ea\u53ea\u5f71\u54cd\u5bf9\u5e94\u73af\u8282\u3002'}
      </p>
      <div className="space-y-5">
        {box('global', '\u5168\u5c40\u6ce8\u5165\uff08\u4f5c\u7528\u4e8e\u6240\u6709 AI \u73af\u8282\uff09', '\u5982\uff1a\u6211\u662f 2024 \u5c4a\u5e94\u5c4a\u751f\uff0c\u522b\u9ad8\u4f30\u6211\u7684\u7ecf\u9a8c\uff1b\u6211\u7279\u522b\u770b\u91cd\u8fdc\u7a0b\u529e\u516c')}
        {box('score_job', '\u8bc4\u5206\u6ce8\u5165\uff08\u53ea\u5f71\u54cd W1 \u6253\u5206\uff09', '\u5982\uff1a\u63d0\u4f9b\u8fdc\u7a0b\u529e\u516c\u7684\u5c97\u4f4d\u914c\u60c5\u52a0\u5206')}
        {box('analyze_intent', '\u610f\u56fe\u6ce8\u5165\uff08\u53ea\u5f71\u54cd W2 \u610f\u56fe\u5224\u65ad\uff09', '\u5982\uff1aHR \u8bf4\u201c\u65b9\u4fbf\u53d1\u4e2a\u5fae\u4fe1\u5417\u201d\u89c6\u4e3a\u8981\u7b80\u5386\u7684\u524d\u594f')}
        {box('generate_reply', '\u56de\u590d\u6ce8\u5165\uff08\u53ea\u5f71\u54cd\u7ed9 HR \u7684\u8349\u7a3f\uff09', '\u5982\uff1a\u8bed\u6c14\u53ef\u66f4\u4e3b\u52a8\uff0c\u53ef\u8868\u8fbe\u5e0c\u671b\u5c3d\u5feb\u6c9f\u901a')}
      </div>
      <SaveButton saving={saving} saved={saved} onClick={() => void save()} />
    </Card>
  )
}

// -- Tab: \u6a21\u578b & Prompt\uff08\u5de6\uff1d\u6a21\u578b\u8def\u7531+\u6ce8\u5165\uff0c\u53f3\uff1d\u53ef\u7f16\u8f91\u6a21\u677f\uff09--------------------------
function ModelPromptTab() {
  // Stacked: model routing (top) / prompt templates full-width (primary) / injection (appended to tail).
  return (
    <div className="space-y-5">
      <ModelTab />
      <PromptTemplatesTab />
      <InjectionSection />
    </div>
  )
}

type Tab = 'prefs' | 'modelprompt' | 'env'
const TABS: Array<{ key: Tab; label: string }> = [
  { key: 'prefs', label: '\u6c42\u804c\u504f\u597d' },
  { key: 'modelprompt', label: '\u6a21\u578b & Prompt' },
  { key: 'env', label: '\u73af\u5883 & Session' },
]

export default function Settings() {
  const [tab, setTab] = useState<Tab>('prefs')
  return (
    <div className="relative max-w-[1600px] space-y-5">
      <DevLabel name="Settings" float />
      <div className="inline-flex gap-1 rounded-xl bg-bg-card2 p-1" style={{ border: '1px solid rgba(255,255,255,0.06)' }}>
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`rounded-lg px-4 py-1.5 text-sm font-medium transition ${tab === t.key ? 'text-white' : 'text-text-3 hover:text-text-1'}`}
            style={tab === t.key ? { background: '#0a84ff' } : undefined}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'prefs' && <PreferencesTab />}
      {tab === 'modelprompt' && <ModelPromptTab />}
      {tab === 'env' && <EnvironmentTab />}
    </div>
  )
}
