import { useEffect, useMemo, useState } from 'react'
import { API, type PersonalInfo as PersonalInfoData } from '@/api'
import DevLabel from '@/components/dev/DevLabel'

// \u4e2a\u4eba\u4fe1\u606f\u9875\uff1a\u7ba1\u7406 data/personal_info/identity.yaml\uff08\u6027\u522b/\u51fa\u751f\u65e5\u671f/\u8bc1\u4ef6\u7c7b\u578b\u7b49\u8eab\u4efd
// \u4e8b\u5b9e\uff0c\u4ee5\u53ca Layer 2 \u5ba1\u6279\u65f6\u81ea\u52a8\u8bb0\u4f4f\u7684\u65b0\u5b57\u6bb5\uff09\u3002
//
// \u59d3\u540d/\u7535\u8bdd/\u90ae\u7bb1**\u523b\u610f\u53ea\u8bfb**\u2014\u2014\u5b83\u4eec\u7684\u552f\u4e00\u771f\u6e90\u662f\u7b80\u5386\u7cfb\u7edf\u7684\u4fe1\u606f\u6c60
// (info_pool.basic_info)\uff0c\u90a3\u8fb9\u5df2\u7ecf\u6709\u5b8c\u6574\u7684\u7f16\u8f91 UI + \u5feb\u7167/\u56de\u6eda\u3002\u540c\u4e00\u4efd\u6570\u636e\u53ea\u7559
// \u4e00\u4e2a\u5199\u5165\u53e3\uff0c\u907f\u514d\u4e24\u6761\u5199\u8def\u5f84\u4e92\u76f8\u8986\u76d6\uff082026-08-13 \u8ddf\u7528\u6237\u5bf9\u9f50\uff09\u3002
//
// \u8bc1\u4ef6\u53f7\u7801\u7c7b\u5b57\u6bb5\u5728\u540e\u7aef save_identity \u4f1a\u88ab\u786c\u62d2\u7edd\uff0c\u8fd9\u91cc\u4e5f\u660e\u786e\u544a\u77e5\u7528\u6237\uff0c\u4e0d\u7ed9\u8f93\u5165\u5f15\u5bfc\u3002

const T_INTRO_A = '\u4e2a\u4eba\u4fe1\u606f\u3002'
const T_INTRO_B = '\u591a\u7ad9\u70b9\u6295\u9012\u65f6\u81ea\u52a8\u586b\u8868\u7528\u7684\u8eab\u4efd\u4e8b\u5b9e\u3002\u59d3\u540d/\u7535\u8bdd/\u90ae\u7bb1\u6765\u81ea\u7b80\u5386\u4fe1\u606f\u6c60\uff0c\u5728\u300c\u7b80\u5386\u300d\u9875\u7f16\u8f91\uff1b\u4e0b\u65b9\u8eab\u4efd\u4fe1\u606f\u5728\u8fd9\u91cc\u7ef4\u62a4\u3002'
const T_BASIC_TITLE = '\u57fa\u672c\u4fe1\u606f'
const T_BASIC_HINT = '\u6765\u81ea\u7b80\u5386\u4fe1\u606f\u6c60\uff0c\u6b64\u5904\u53ea\u8bfb\u2014\u2014\u53bb\u300c\u7b80\u5386\u300d\u9875\u7f16\u8f91'
const T_NAME = '\u59d3\u540d'
const T_PHONE = '\u7535\u8bdd'
const T_EMAIL = '\u90ae\u7bb1'
const T_EMPTY_VALUE = '\uff08\u672a\u586b\u5199\uff09'
const T_IDENTITY_TITLE = '\u8eab\u4efd\u4fe1\u606f'
const T_IDENTITY_HINT = '\u5ba1\u6279\u8de8\u7ad9\u70b9\u6295\u9012\u65f6\uff0c\u4f60\u586b\u7684\u65b0\u5b57\u6bb5\u4f1a\u81ea\u52a8\u8bb0\u4f4f\u5e76\u51fa\u73b0\u5728\u8fd9\u91cc'
const T_IDENTITY_EMPTY = '\u8fd8\u6ca1\u6709\u8eab\u4efd\u4fe1\u606f\u3002\u53ef\u4ee5\u5728\u4e0b\u65b9\u65b0\u589e\uff0c\u6216\u5728\u5ba1\u6279\u6295\u9012\u65f6\u586b\u5199\u540e\u81ea\u52a8\u8bb0\u4f4f\u3002'
const T_ADD_TITLE = '\u65b0\u589e\u5b57\u6bb5'
const T_ADD_KEY_PLACEHOLDER = '\u5b57\u6bb5\u540d\uff0c\u5982 \u5b66\u6821\u540d\u79f0'
const T_ADD_VALUE_PLACEHOLDER = '\u503c'
const T_ADD_BTN = '\u65b0\u589e'
const T_DELETE = '\u5220\u9664'
const T_SAVE = '\u4fdd\u5b58'
const T_SAVING = '\u4fdd\u5b58\u4e2d\u2026'
const T_SAVED = '\u5df2\u4fdd\u5b58'
const T_UNSAVED = '\u6709\u672a\u4fdd\u5b58\u7684\u4fee\u6539'
const T_GOV_ID_WARN = '\u8bc1\u4ef6\u53f7\u7801\u7c7b\u4fe1\u606f\u4e0d\u4f1a\u88ab\u5b58\u50a8\uff0c\u4e5f\u6c38\u8fdc\u4e0d\u4f1a\u81ea\u52a8\u586b\u5199\u2014\u2014\u9700\u8981\u65f6\u8bf7\u5728\u7f51\u9875\u4e0a\u672c\u4eba\u624b\u52a8\u8f93\u5165\u3002'

function ReadOnlyRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-center gap-3 py-2">
      <span className="w-24 shrink-0 text-[14px] text-text-3">{label}</span>
      <span className={`text-[14px] ${value ? 'text-text-1' : 'text-text-3'}`}>
        {value || T_EMPTY_VALUE}
      </span>
    </div>
  )
}

export default function PersonalInfo() {
  const [data, setData] = useState<PersonalInfoData | null>(null)
  const [identity, setIdentity] = useState<Record<string, string>>({})
  const [newKey, setNewKey] = useState('')
  const [newValue, setNewValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [justSaved, setJustSaved] = useState(false)

  useEffect(() => {
    API.getPersonalInfo()
      .then((d) => {
        setData(d)
        setIdentity(d.identity)
      })
      .catch(() => setData({ basic: { name: '', phone: '', email: '' }, identity: {} }))
  }, [])

  const dirty = useMemo(() => {
    if (!data) return false
    const a = JSON.stringify(data.identity)
    const b = JSON.stringify(identity)
    return a !== b
  }, [data, identity])

  function updateField(key: string, value: string) {
    setIdentity((prev) => ({ ...prev, [key]: value }))
    setJustSaved(false)
  }

  function removeField(key: string) {
    setIdentity((prev) => {
      const next = { ...prev }
      delete next[key]
      return next
    })
    setJustSaved(false)
  }

  function addField() {
    const key = newKey.trim()
    if (!key || key in identity) return
    setIdentity((prev) => ({ ...prev, [key]: newValue.trim() }))
    setNewKey('')
    setNewValue('')
    setJustSaved(false)
  }

  async function handleSave() {
    setSaving(true)
    try {
      const result = await API.savePersonalInfo(identity)
      setData((prev) => (prev ? { ...prev, identity: result.identity } : prev))
      setIdentity(result.identity)
      setJustSaved(true)
      window.setTimeout(() => setJustSaved(false), 3000)
    } finally {
      setSaving(false)
    }
  }

  const identityKeys = Object.keys(identity)

  return (
    <div className="relative mx-auto max-w-3xl space-y-5">
      <DevLabel name="PersonalInfo" float />

      <p className="text-[15px] leading-relaxed text-text-2">
        <span className="text-text-1">{T_INTRO_A}</span>
        {T_INTRO_B}
      </p>

      <div className="rounded-2xl bg-bg-card p-5 shadow-card">
        <div className="mb-1 flex items-baseline gap-2.5">
          <h2 className="text-[16px] font-semibold text-text-1">{T_BASIC_TITLE}</h2>
          <span className="text-[13px] text-text-3">{T_BASIC_HINT}</span>
        </div>
        <div className="divide-y" style={{ borderColor: 'rgba(255,255,255,0.06)' }}>
          <ReadOnlyRow label={T_NAME} value={data?.basic.name ?? ''} />
          <ReadOnlyRow label={T_PHONE} value={data?.basic.phone ?? ''} />
          <ReadOnlyRow label={T_EMAIL} value={data?.basic.email ?? ''} />
        </div>
      </div>

      <div className="rounded-2xl bg-bg-card p-5 shadow-card">
        <div className="mb-1 flex items-baseline gap-2.5">
          <h2 className="text-[16px] font-semibold text-text-1">{T_IDENTITY_TITLE}</h2>
          <span className="text-[13px] text-text-3">{T_IDENTITY_HINT}</span>
        </div>

        <p className="mb-3 rounded-lg px-3 py-1.5 text-[13px]" style={{ background: 'rgba(255,69,58,0.10)', color: '#ff6961' }}>
          {T_GOV_ID_WARN}
        </p>

        {identityKeys.length === 0 ? (
          <p className="py-2 text-[14px] text-text-3">{T_IDENTITY_EMPTY}</p>
        ) : (
          <div className="space-y-2">
            {identityKeys.map((key) => (
              <div key={key} className="flex items-center gap-2.5">
                <span className="w-32 shrink-0 truncate text-[14px] text-text-2" title={key}>{key}</span>
                <input
                  type="text"
                  value={identity[key]}
                  onChange={(e) => updateField(key, e.target.value)}
                  className="flex-1 rounded-lg px-3 py-1.5 text-[14px] text-white focus:outline-none"
                  style={{ background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.1)' }}
                />
                <button
                  type="button"
                  onClick={() => removeField(key)}
                  className="shrink-0 rounded-lg px-2.5 py-1.5 text-[13px] text-text-3 transition hover:text-text-1"
                  style={{ background: 'rgba(255,255,255,0.05)' }}
                >
                  {T_DELETE}
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="mt-4 border-t pt-4" style={{ borderColor: 'rgba(255,255,255,0.06)' }}>
          <p className="mb-2 text-[13px] text-text-3">{T_ADD_TITLE}</p>
          <div className="flex items-center gap-2.5">
            <input
              type="text"
              value={newKey}
              onChange={(e) => setNewKey(e.target.value)}
              placeholder={T_ADD_KEY_PLACEHOLDER}
              className="w-32 shrink-0 rounded-lg px-3 py-1.5 text-[14px] text-white focus:outline-none"
              style={{ background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.1)' }}
            />
            <input
              type="text"
              value={newValue}
              onChange={(e) => setNewValue(e.target.value)}
              placeholder={T_ADD_VALUE_PLACEHOLDER}
              onKeyDown={(e) => { if (e.key === 'Enter') addField() }}
              className="flex-1 rounded-lg px-3 py-1.5 text-[14px] text-white focus:outline-none"
              style={{ background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,255,255,0.1)' }}
            />
            <button
              type="button"
              onClick={addField}
              disabled={!newKey.trim() || newKey.trim() in identity}
              className="shrink-0 rounded-lg px-3 py-1.5 text-[13px] text-white transition disabled:cursor-not-allowed disabled:opacity-40"
              style={{ background: '#0a84ff' }}
            >
              {T_ADD_BTN}
            </button>
          </div>
        </div>

        <div className="mt-4 flex items-center gap-3">
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={!dirty || saving}
            className="rounded-lg px-4 py-1.5 text-[13.5px] font-medium text-white transition disabled:cursor-not-allowed disabled:opacity-40"
            style={{ background: '#30a14e' }}
          >
            {saving ? T_SAVING : T_SAVE}
          </button>
          {dirty && !saving && <span className="text-[13px]" style={{ color: '#ff9f0a' }}>{T_UNSAVED}</span>}
          {justSaved && <span className="text-[13px]" style={{ color: '#30d158' }}>{T_SAVED}</span>}
        </div>
      </div>
    </div>
  )
}
