import { useEffect, useMemo, useState } from 'react'
import { API, type PendingApplication, type PendingApplicationField, type PendingApplicationFieldKind } from '@/api'
import DevLabel from '@/components/dev/DevLabel'

// Layer 2 (\u4eba\u5de5\u5ba1\u6279) minimal implementation for the multi-site apply
// architecture. See docs/multi-site-expansion-design.md. Layer 1 does not exist
// yet -- rows are seeded via scripts/seed_pending_application.py until it does.
// This page only does review + approve/reject; it never talks to a browser or a
// site directly.

const T_INTRO_A = '\u8de8\u7ad9\u70b9\u6295\u9012\u5ba1\u6279\u3002'
const T_INTRO_B = '\u5ba1\u6838 Layer 1 \u8bc6\u522b\u51fa\u7684\u5f85\u586b\u5b57\u6bb5\uff0c\u8bc1\u4ef6\u7c7b\u5b57\u6bb5\u9700\u4eb2\u81ea\u586b\u5199\u3002\u70b9\u201c\u6279\u51c6\u201d\u662f\u6574\u6761\u94fe\u8def\u91cc\u552f\u4e00\u7684 go \u4fe1\u53f7\u3002'
const T_EMPTY_T = '\u8fd8\u6ca1\u6709\u5f85\u5ba1\u6279\u7684\u6295\u9012'
const T_EMPTY_D = 'Layer 1 \u8fd8\u672a\u5b9e\u73b0\uff0c\u53ef\u7528 scripts/seed_pending_application.py \u9020\u51e0\u6761\u6837\u4f8b\u6570\u636e\u3002'
const T_FILTER_ALL = '\u5168\u90e8'
const T_FILTER_PENDING = '\u5f85\u5ba1\u6279'
const T_FILTER_APPROVED = '\u5df2\u6279\u51c6'
const T_FILTER_REJECTED = '\u5df2\u9a73\u56de'
const T_NO_SELECTION = '\u9009\u4e2d\u5de6\u4fa7\u4e00\u6761\u8bb0\u5f55\u67e5\u770b\u8be6\u60c5'
const T_OPEN_URL = '\u6253\u5f00\u94fe\u63a5'
const T_APPROVE = '\u6279\u51c6'
const T_REJECT = '\u9a73\u56de'
const T_REJECT_REASON_PLACEHOLDER = '\u9a73\u56de\u7406\u7531\uff08\u53ef\u9009\uff09'
const T_CONFIRM_REJECT = '\u786e\u8ba4\u9a73\u56de'
const T_CANCEL = '\u53d6\u6d88'
const T_NEEDS_MANUAL = '\u9700\u624b\u586b'
const T_MISSING_GOV_ID = '\u8fd8\u6709\u8bc1\u4ef6\u7c7b\u5b57\u6bb5\u672a\u586b\uff0c\u65e0\u6cd5\u6279\u51c6'
const T_DECIDED_AT = '\u5904\u7406\u65f6\u95f4'
const T_REASON_LABEL = '\u9a73\u56de\u7406\u7531'
const T_SAVING = '\u63d0\u4ea4\u4e2d\u2026'

const KIND_LABEL: Record<PendingApplicationFieldKind, string> = {
  demographic: '\u4eba\u53e3\u5b66\u5b57\u6bb5',
  open_question: '\u5f00\u653e\u95ee\u9898',
  government_id: '\u8bc1\u4ef6\u53f7\u7801',
}

const KIND_ACCENT: Record<PendingApplicationFieldKind, string> = {
  demographic: '#0a84ff',
  open_question: '#30d158',
  government_id: '#ff453a',
}

const STATUS_STYLE: Record<PendingApplication['status'], { label: string; color: string; bg: string }> = {
  pending: { label: '\u5f85\u5ba1\u6279', color: '#ff9f0a', bg: 'rgba(255,159,10,0.15)' },
  approved: { label: '\u5df2\u6279\u51c6', color: '#30d158', bg: 'rgba(48,209,88,0.15)' },
  rejected: { label: '\u5df2\u9a73\u56de', color: '#ff453a', bg: 'rgba(255,69,58,0.15)' },
}

function StatusBadge({ status }: { status: PendingApplication['status'] }) {
  const s = STATUS_STYLE[status]
  return (
    <span className="rounded-full px-2 py-0.5 text-[12px] font-semibold" style={{ background: s.bg, color: s.color }}>
      {s.label}
    </span>
  )
}

function missingGovId(fields: PendingApplicationField[]): boolean {
  return fields.some((f) => f.kind === 'government_id' && !f.candidate_value.trim())
}

function ApplicationRow({ app, active, onClick }: { app: PendingApplication; active: boolean; onClick: () => void }) {
  const needsManual = app.status === 'pending' && missingGovId(app.fields)
  return (
    <button
      type="button"
      onClick={onClick}
      className={`w-full rounded-xl px-3.5 py-3 text-left transition ${active ? '' : 'hover:bg-bg-hover'}`}
      style={active ? { background: 'rgba(10,132,255,0.12)', border: '1px solid rgba(10,132,255,0.3)' } : { border: '1px solid transparent' }}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate text-[14.5px] font-semibold text-text-1">{app.job_title}</span>
        <StatusBadge status={app.status} />
      </div>
      <div className="mt-1 flex items-center gap-2 text-[13px] text-text-3">
        <span className="rounded px-1.5 py-px font-mono" style={{ background: 'rgba(255,255,255,0.06)' }}>{app.site_name}</span>
        {app.company && <span className="truncate">{app.company}</span>}
      </div>
      {needsManual && (
        <p className="mt-1.5 text-[12px]" style={{ color: '#ff453a' }}>{T_NEEDS_MANUAL}</p>
      )}
    </button>
  )
}

type Filter = 'all' | PendingApplication['status']

export default function CrossSiteApplications() {
  const [apps, setApps] = useState<PendingApplication[]>([])
  const [filter, setFilter] = useState<Filter>('pending')
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [editedFields, setEditedFields] = useState<Record<string, string>>({})
  const [rejecting, setRejecting] = useState(false)
  const [rejectReason, setRejectReason] = useState('')
  const [saving, setSaving] = useState(false)
  const [justSavedFacts, setJustSavedFacts] = useState<string[] | null>(null)

  const refresh = () => {
    API.getPendingApplications(filter === 'all' ? undefined : filter)
      .then((r) => setApps(r.applications))
      .catch(() => setApps([]))
  }

  useEffect(() => { refresh() }, [filter])

  const selected = useMemo(() => apps.find((a) => a.id === selectedId) ?? null, [apps, selectedId])

  function selectApp(app: PendingApplication) {
    setSelectedId(app.id)
    setRejecting(false)
    setRejectReason('')
    const init: Record<string, string> = {}
    for (const f of app.fields) init[f.field_id] = f.candidate_value
    setEditedFields(init)
  }

  const canApprove = useMemo(() => {
    if (!selected) return false
    return selected.fields.every((f) => f.kind !== 'government_id' || (editedFields[f.field_id] ?? '').trim() !== '')
  }, [selected, editedFields])

  async function handleApprove() {
    if (!selected || !canApprove) return
    setSaving(true)
    try {
      const finalFields: PendingApplicationField[] = selected.fields.map((f) => ({ ...f, candidate_value: editedFields[f.field_id] ?? '' }))
      const result = await API.approvePendingApplication(selected.id, finalFields)
      refresh()
      setSelectedId(null)
      if (result.saved_new_facts.length > 0) {
        setJustSavedFacts(result.saved_new_facts)
        window.setTimeout(() => setJustSavedFacts(null), 5000)
      }
    } finally {
      setSaving(false)
    }
  }

  async function handleReject() {
    if (!selected) return
    setSaving(true)
    try {
      await API.rejectPendingApplication(selected.id, rejectReason.trim() || undefined)
      refresh()
      setSelectedId(null)
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="relative grid h-full grid-cols-[360px_1fr] gap-4">
      <DevLabel name="CrossSiteApplications" float />

      <div className="flex min-h-0 flex-col gap-3">
        <p className="text-[15px] leading-relaxed text-text-2">
          <span className="text-text-1">{T_INTRO_A}</span>
          {T_INTRO_B}
        </p>

        {justSavedFacts && (
          <div className="rounded-lg px-3 py-1.5 text-[13px]" style={{ background: 'rgba(48,209,88,0.12)', color: '#30d158' }}>
            {'\u5df2\u8bb0\u4f4f\u65b0\u4fe1\u606f\uff1a'}{justSavedFacts.join('\u3001')}
          </div>
        )}

        <div className="flex flex-wrap gap-1.5">
          {(['pending', 'approved', 'rejected', 'all'] as Filter[]).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFilter(f)}
              className={`rounded-lg px-3 py-1.5 text-[13.5px] font-medium transition ${filter === f ? 'text-text-1' : 'text-text-3 hover:text-text-2'}`}
              style={filter === f ? { background: 'rgba(10,132,255,0.18)', boxShadow: 'inset 0 0 0 1px rgba(10,132,255,0.35)' } : { border: '1px solid rgba(255,255,255,0.08)' }}
            >
              {f === 'all' ? T_FILTER_ALL : f === 'pending' ? T_FILTER_PENDING : f === 'approved' ? T_FILTER_APPROVED : T_FILTER_REJECTED}
            </button>
          ))}
        </div>

        <div className="flex-1 space-y-1.5 overflow-y-auto">
          {apps.length === 0 && (
            <div className="rounded-xl p-5 text-center" style={{ border: '1px dashed rgba(255,255,255,0.12)' }}>
              <p className="text-[14.5px] font-semibold text-text-1">{T_EMPTY_T}</p>
              <p className="mt-1.5 text-[13px] leading-relaxed text-text-3">{T_EMPTY_D}</p>
            </div>
          )}
          {apps.map((app) => (
            <ApplicationRow key={app.id} app={app} active={app.id === selectedId} onClick={() => selectApp(app)} />
          ))}
        </div>
      </div>

      <div className="min-h-0 overflow-y-auto rounded-2xl bg-bg-card p-5 shadow-card">
        {!selected ? (
          <p className="flex h-full items-center justify-center text-[14px] text-text-3">{T_NO_SELECTION}</p>
        ) : (
          <div className="space-y-4">
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-[18px] font-semibold text-text-1">{selected.job_title}</h2>
                  <StatusBadge status={selected.status} />
                </div>
                <div className="mt-1 flex items-center gap-2 text-[13.5px] text-text-3">
                  <span className="rounded px-1.5 py-px font-mono" style={{ background: 'rgba(255,255,255,0.06)' }}>{selected.site_name}</span>
                  {selected.company && <span>{selected.company}</span>}
                </div>
              </div>
              {selected.job_url && (
                <button
                  type="button"
                  onClick={() => void API.browseUrl(selected.job_url)}
                  className="shrink-0 rounded-lg px-2.5 py-1.5 text-[13px] text-text-2 transition hover:text-text-1"
                  style={{ background: 'rgba(255,255,255,0.07)' }}
                >
                  {T_OPEN_URL}
                </button>
              )}
            </div>

            {selected.status !== 'pending' && (
              <div className="rounded-xl p-3 text-[13.5px]" style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)' }}>
                <p className="text-text-3">{T_DECIDED_AT}: <span className="text-text-2">{selected.decided_at}</span></p>
                {selected.status === 'rejected' && selected.reason && (
                  <p className="mt-1 text-text-3">{T_REASON_LABEL}: <span className="text-text-2">{selected.reason}</span></p>
                )}
              </div>
            )}

            <div className="space-y-2.5">
              {selected.fields.map((f) => {
                const accent = KIND_ACCENT[f.kind]
                const value = editedFields[f.field_id] ?? f.candidate_value
                const isEmpty = !value.trim()
                const editable = selected.status === 'pending'
                return (
                  <div key={f.field_id} className="rounded-xl p-3" style={{ background: 'rgba(255,255,255,0.03)', border: `1px solid ${f.kind === 'government_id' && isEmpty && editable ? 'rgba(255,69,58,0.4)' : 'rgba(255,255,255,0.07)'}` }}>
                    <div className="mb-1.5 flex items-center gap-2">
                      <span className="text-[14px] font-medium text-text-1">{f.label}</span>
                      <span className="rounded-full px-1.5 py-px text-[11px] font-semibold" style={{ background: `${accent}26`, color: accent }}>
                        {KIND_LABEL[f.kind]}
                      </span>
                    </div>
                    {editable ? (
                      <input
                        type="text"
                        value={value}
                        onChange={(e) => setEditedFields((prev) => ({ ...prev, [f.field_id]: e.target.value }))}
                        placeholder={f.kind === 'government_id' ? T_NEEDS_MANUAL : ''}
                        className="w-full rounded-lg px-3 py-1.5 text-[14px] text-white focus:outline-none"
                        style={{ background: 'rgba(0,0,0,0.35)', border: `1px solid ${f.kind === 'government_id' && isEmpty ? 'rgba(255,69,58,0.4)' : 'rgba(255,255,255,0.1)'}` }}
                      />
                    ) : (
                      <p className="text-[14px] text-text-2">{value || '\u2014'}</p>
                    )}
                  </div>
                )
              })}
            </div>

            {selected.status === 'pending' && (
              <div className="space-y-2.5 border-t border-border-subtle pt-3.5">
                {!canApprove && (
                  <p className="text-[13px]" style={{ color: '#ff453a' }}>{T_MISSING_GOV_ID}</p>
                )}
                {rejecting ? (
                  <div className="space-y-2">
                    <textarea
                      value={rejectReason}
                      onChange={(e) => setRejectReason(e.target.value)}
                      rows={2}
                      placeholder={T_REJECT_REASON_PLACEHOLDER}
                      className="w-full rounded-xl px-3 py-2 text-sm text-white focus:outline-none"
                      style={{ background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,69,58,0.3)' }}
                    />
                    <div className="flex items-center gap-2">
                      <button type="button" disabled={saving} onClick={() => void handleReject()} className="rounded-lg px-3 py-1.5 text-[13px] font-medium text-white disabled:opacity-50" style={{ background: '#ff453a' }}>
                        {saving ? T_SAVING : T_CONFIRM_REJECT}
                      </button>
                      <button type="button" onClick={() => setRejecting(false)} className="rounded-lg bg-bg-card2 px-3 py-1.5 text-[13px] text-text-2">
                        {T_CANCEL}
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <button type="button" disabled={!canApprove || saving} onClick={() => void handleApprove()} className="rounded-lg px-4 py-1.5 text-[13.5px] font-medium text-white disabled:cursor-not-allowed disabled:opacity-40" style={{ background: '#30a14e' }}>
                      {saving ? T_SAVING : T_APPROVE}
                    </button>
                    <button type="button" disabled={saving} onClick={() => setRejecting(true)} className="rounded-lg bg-bg-card2 px-4 py-1.5 text-[13.5px] text-text-2">
                      {T_REJECT}
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
