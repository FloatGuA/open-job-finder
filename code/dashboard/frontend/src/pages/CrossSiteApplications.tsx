import { Fragment, useEffect, useMemo, useState } from 'react'
import {
  API,
  type PendingApplication,
  type PendingApplicationField,
  type FieldCandidate,
  type PendingApplicationFieldKind,
  type PendingJob,
  type SiteInfo,
  type SiteLimitInfo,
  type SiteManualInfo,
} from '@/api'
import DevLabel from '@/components/dev/DevLabel'

// Two human checkpoints of the multi-site apply architecture, one tab each
// (docs/multi-site-expansion-design.md):
//   Checkpoint 1 -- did the agent pick the RIGHT JOBS?   (pending_jobs)
//   Checkpoint 2 -- are the FIELD VALUES right?          (pending_applications)
// Split on purpose: picking the wrong job and filling a wrong field are different
// errors, and no amount of care on the second one rescues a mistake in the first.
//
// Checkpoint 1 is a RATIONING screen, not a browsing screen: the scarce resource is
// application slots on the target site, so the slot budget is the page's spine (the
// sticky site bar), not a banner someone scrolls past.

const T_TAB_1 = '\u9009\u5c97\u5ba1\u6279'
const T_TAB_2 = '\u5b57\u6bb5\u5ba1\u6279'
const T_TAB_1_SUB = 'Checkpoint 1'
const T_TAB_2_SUB = 'Checkpoint 2'

const T_FILTER_ALL = '\u5168\u90e8'
const T_FILTER_PENDING = '\u5f85\u5ba1\u6279'
const T_FILTER_APPROVED = '\u5df2\u6279\u51c6'
const T_FILTER_REJECTED = '\u5df2\u9a73\u56de'

// ---- Checkpoint 1 ----
const T_C1_INTRO = '\u5ba1\u6838\u9009\u5c97 agent \u627e\u56de\u6765\u7684\u5019\u9009\u5c97\u4f4d\u3002'
const T_C1_INTRO_2 = '\u7c7b\u522b\u662f agent \u81ea\u5df1\u5224\u7684\uff0c\u6539\u9519\u4e86\u76f4\u63a5\u6539\u2014\u2014\u5b83\u5360\u7684\u662f\u90a3\u4e00\u7c7b\u7684\u540d\u989d\u3002'
const T_C1_EMPTY_T = '\u8fd8\u6ca1\u6709\u5f85\u5ba1\u6279\u7684\u5c97\u4f4d'
const T_C1_EMPTY_D = 'python scripts/run_layer1.py --search-url <\u5165\u53e3\u9875> --site <\u7ad9\u70b9> --select-only'
const T_C1_SELECT_ALL = '\u5168\u9009\u672c\u7ad9'
const T_C1_CLEAR = '\u53d6\u6d88\u9009\u62e9'
const T_C1_BATCH_APPROVE = '\u6279\u51c6'
const T_C1_BATCH_REJECT = '\u9a73\u56de'
const T_C1_CORRECTED = 'agent \u5f52\u4e3a'
const T_C1_OPEN = '\u6253\u5f00\u5c97\u4f4d\u9875'
const T_C1_JD = '\u5c97\u4f4d\u539f\u6587'
const T_SITE_MANUAL = '\u7ad9\u70b9\u624b\u518c'
const T_CLEAR_SITE = '\u6e05\u6389\u5019\u9009'
const T_RESURVEY = '\u91cd\u65b0\u52d8\u5bdf'
const T_RESURVEY_CONFIRM = '\u786e\u8ba4\u4f5c\u5e9f\uff1f'
const T_RESURVEY_HINT = '\u4f5c\u5e9f\u8fd9\u4efd\u624b\u518c\uff0c\u4e0b\u4e00\u6b21 m1 \u4f1a\u91cd\u65b0\u52d8\u5bdf\u7ad9\u70b9\u7ed3\u6784\u3002\u5019\u9009\u6c60\u4e0d\u52a8\u3002\u624b\u518c\u91cc\u7684\u201c\u591a\u9009\u8fd8\u662f\u4e92\u65a5\u201d\u8fd9\u7c7b\u5224\u65ad\u53ef\u80fd\u662f\u9519\u7684\uff0c\u800c\u8f7b\u6821\u9a8c\u53d1\u73b0\u4e0d\u4e86'
const T_CLEAR_CONFIRM = '\u786e\u8ba4\u6e05\u6389\uff1f'
const T_CLEAR_CANCEL = '\u7b97\u4e86'
const T_CLEAR_HINT = '\u5220\u6389\u8fd9\u4e2a\u7ad9\u8fd8\u6ca1\u6279\u51c6\u7684\u5019\u9009\uff08\u5f85\u5ba1\u6279\uff0b\u5df2\u62d2\u7edd\uff09\uff0c\u597d\u628a\u8fd9\u4e2a\u7ad9\u91cd\u6536\u4e00\u904d\u3002\u5df2\u6279\u51c6\u7684\u4e0d\u52a8'
const T_MANUAL_NOTE = '\u73b0\u573a\u53d1\u73b0'
const T_MANUAL_SURVEYED = '\u63a2\u4e8e'
const T_C1_UNIT = '\u4e2a'
const T_C1_MAKE_GOLDEN = '\u786e\u8ba4\uff0c\u6559\u7ed9 agent'
const T_C1_IS_GOLDEN = '\u5df2\u5f55\u5165\u6837\u4f8b\u5e93'
const T_C1_UNDO_GOLDEN = '\u64a4\u9500'
const T_C1_GOLDEN_HINT = '\u786e\u8ba4\u540e\u4f1a\u4f5c\u4e3a\u4f8b\u5b50\u5199\u8fdb\u9009\u5c97 agent \u7684 prompt'

// ---- checkpoint 1: which resume gets sent ----
const T_RESUME_LABEL = '\u7b80\u5386'
const T_RESUME_NONE = '\u6ca1\u6709\u53ef\u53d1\u7684\u7b80\u5386'
const T_RESUME_FALLBACK = '\u515c\u5e95'
const T_PDF_READY = '\u53ef\u53d1\u9001'
const T_PDF_READY_HINT = '\u6709\u5df2\u5bfc\u51fa\u7684 PDF\uff0c\u4e14\u4e0d\u65e9\u4e8e\u7b80\u5386\u6700\u540e\u4fee\u6539'
const T_PDF_STALE = 'PDF \u8fc7\u671f'
const T_PDF_STALE_HINT = '\u7b80\u5386\u6539\u8fc7\u4e4b\u540e\u6ca1\u6709\u91cd\u65b0\u5bfc\u51fa\uff0cm2 \u4f1a\u62d2\u7edd\u7528\u8fd9\u4e00\u4efd'
const T_PDF_MISSING = '\u672a\u5bfc\u51fa'
const T_PDF_MISSING_HINT = '\u4ece\u6ca1\u5bfc\u51fa\u8fc7 PDF\uff0cm2 \u6ca1\u6cd5\u53d1\u9001'

// ---- slot budget ----
const T_SLOT_QUOTA = '\u540d\u989d'
const T_SLOT_APPROVED = '\u5df2\u6279\u51c6'
const T_SLOT_PICKED = '\u672c\u6b21\u9009\u4e2d'
const T_SLOT_LEFT = '\u5269'
const T_SLOT_OVER = '\u8d85\u51fa'
const T_SLOT_UNKNOWN = '\u4e0a\u9650\u672a\u77e5'
const T_SLOT_UNKNOWN_HINT = 'agent \u6ca1\u5728\u9875\u9762\u4e0a\u770b\u5230\u76f8\u5173\u8bf4\u660e\u3002\u8fd9\u4e0d\u7b49\u4e8e\u6ca1\u6709\u9650\u5236\u3002'
const T_SLOT_NO_LIMIT = '\u4e0d\u9650\u91cf'
const T_SLOT_APPLIED = '\u7ad9\u4e0a\u5df2\u6295\u9012'
const T_SLOT_EVIDENCE = '\u9875\u9762\u539f\u6587'
const T_GATE_CONFIRM = '\u8d85\u540d\u989d\uff0c\u4ecd\u8981\u6279\u51c6'
const T_LIMIT_EDIT = '\u6211\u77e5\u9053\uff0c\u6211\u6765\u586b'
const T_LIMIT_EDIT_SHORT = '\u6539'
const T_LIMIT_SAVE = '\u4fdd\u5b58'
const T_LIMIT_NO_LIMIT_BTN = '\u4e0d\u9650\u91cf'
const T_LIMIT_RESET = '\u9000\u56de\u672a\u77e5'
const T_LIMIT_PLACEHOLDER = '\u6700\u591a\u6295\u9012\u51e0\u4e2a'
const T_SCOPE_BUCKET = '\u4ec5\u9650'
const T_SCOPE_UNCLEAR = '\u8303\u56f4\u4e0d\u660e\uff0c\u4e0d\u7b97\u540d\u989d'
const T_GATE_NA = '\u4e0a\u9650\u6309\u62db\u8058\u9879\u76ee\u7b97\uff0c\u65e0\u6cd5\u6838\u5bf9\u603b\u6570'
const T_BRIEF = 'agent \u7b14\u8bb0'
const T_BUCKET_NONE = '\u672a\u8bb0\u5f55\u9879\u76ee'
const T_GATE_NO_BUCKET = '\u8fd9\u4e9b\u5c97\u4f4d\u6ca1\u8bb0\u5f55\u62db\u8058\u9879\u76ee\uff0c\u7b97\u4e0d\u8fdb\u4efb\u4f55\u540d\u989d'

const T_APPROVE = '\u6279\u51c6'
const T_REJECT = '\u9a73\u56de'
const T_CANCEL = '\u53d6\u6d88'
const T_SAVING = '\u63d0\u4ea4\u4e2d\u2026'
const T_REJECT_REASON_PLACEHOLDER = '\u9a73\u56de\u7406\u7531\uff08\u53ef\u9009\uff09'
const T_CONFIRM_REJECT = '\u786e\u8ba4\u9a73\u56de'
const T_REASON_LABEL = '\u9a73\u56de\u7406\u7531'
const T_DECIDED_AT = '\u5904\u7406\u65f6\u95f4'
// 撤销入口——2026-08-20 真机事故：误批之后没有任何撤销入口，只能维护者直接跑
// SQL 改库。样式刻意跟 T_C1_UNDO_GOLDEN 一样低调（文字+虚线下划线），
// 这是纠错入口，不是主操作。
const T_UNDO_DECISION = '\u64a4\u9500'
const T_UNDO_DECISION_HINT = '\u64a4\u9500\u8fd9\u6b21\u5ba1\u6279\u7ed3\u679c\uff0c\u6539\u56de\u5f85\u5ba1\u6279'

// ---- Checkpoint 2 ----
const T_INTRO_A = '\u8de8\u7ad9\u70b9\u6295\u9012\u5ba1\u6279\u3002'
const T_INTRO_B = '\u5ba1\u6838 Layer 1 \u8bc6\u522b\u51fa\u7684\u5f85\u586b\u5b57\u6bb5\uff0c\u8bc1\u4ef6\u7c7b\u5b57\u6bb5\u9700\u4eb2\u81ea\u586b\u5199\u3002\u70b9\u201c\u6279\u51c6\u201d\u662f\u6574\u6761\u94fe\u8def\u91cc\u552f\u4e00\u7684 go \u4fe1\u53f7\u3002'
const T_EMPTY_T = '\u8fd8\u6ca1\u6709\u5f85\u5ba1\u6279\u7684\u6295\u9012'
const T_EMPTY_D = '\u5148\u5728\u300c\u9009\u5c97\u5ba1\u6279\u300d\u6279\u51c6\u5c97\u4f4d\uff0c\u518d\u8dd1\u52d8\u5bdf\u8868\u5355\u3002'
const T_NO_SELECTION = '\u9009\u4e2d\u5de6\u4fa7\u4e00\u6761\u8bb0\u5f55\u67e5\u770b\u8be6\u60c5'
const T_OPEN_URL = '\u6253\u5f00\u94fe\u63a5'
const T_NEEDS_MANUAL = '\u9700\u624b\u586b'
const T_MISSING_GOV_ID = '\u8fd8\u6709\u8bc1\u4ef6\u7c7b\u5b57\u6bb5\u672a\u586b\uff0c\u65e0\u6cd5\u6279\u51c6'
const T_CANDIDATES = '\u4fe1\u606f\u6c60\u91cc\u6709\u591a\u4e2a\u53ef\u9009\uff0c\u70b9\u4e00\u4e2a\u586b\u5165'
const T_SCREENSHOT = '\u8868\u5355\u622a\u56fe'
const T_SCREENSHOT_HINT = '\u5b57\u6bb5\u540d\u5e38\u5e38\u4e0d\u591f\u5224\u65ad\u8be5\u586b\u4ec0\u4e48\u2014\u2014\u5bf9\u7167\u622a\u56fe\u770b\u5b83\u5728\u9875\u9762\u4e0a\u5c5e\u4e8e\u54ea\u4e2a\u5206\u533a\u3002'

const KIND_LABEL: Record<PendingApplicationFieldKind, string> = {
  demographic: '\u4eba\u53e3\u5b66\u5b57\u6bb5',
  open_question: '\u5f00\u653e\u95ee\u9898',
  government_id: '\u8bc1\u4ef6\u53f7\u7801',
  unknown_fact: '\u8d44\u6599\u91cc\u6ca1\u6709',
}

const KIND_ACCENT: Record<PendingApplicationFieldKind, string> = {
  demographic: '#0a84ff',
  open_question: '#30d158',
  government_id: '#ff453a',
  // 橙色：不是错，但要人动手。跟绿色的“已起草”分开。
  unknown_fact: '#ff9f0a',
}

type Status = 'pending' | 'approved' | 'rejected'
type Filter = 'all' | Status

const STATUS_STYLE: Record<Status, { label: string; color: string; bg: string }> = {
  pending: { label: T_FILTER_PENDING, color: '#ff9f0a', bg: 'rgba(255,159,10,0.15)' },
  approved: { label: T_FILTER_APPROVED, color: '#30d158', bg: 'rgba(48,209,88,0.15)' },
  rejected: { label: T_FILTER_REJECTED, color: '#ff453a', bg: 'rgba(255,69,58,0.15)' },
}

const RESUME_PDF_STATE_STYLE: Record<string, { label: string; hint: string; color: string; bg: string }> = {
  ready: { label: T_PDF_READY, hint: T_PDF_READY_HINT, color: '#30d158', bg: 'rgba(48,209,88,0.15)' },
  stale: { label: T_PDF_STALE, hint: T_PDF_STALE_HINT, color: '#ff9f0a', bg: 'rgba(255,159,10,0.15)' },
  missing: { label: T_PDF_MISSING, hint: T_PDF_MISSING_HINT, color: '#ff453a', bg: 'rgba(255,69,58,0.15)' },
}

// PDF 三态的第二份视觉映射（第一份是 Resume.tsx 的 `PdfStatePill`）。
// **刻意不复用**：这里 missing/stale 要比简历页更刺眼（在这一页看漏了，人会批准一个
// 注定被闸门拒绝的岗位），而简历页那份是密集列表里的小标记，抢眼反而碍事。
// 共享的只是**状态词汇** ready/stale/missing——它来自后端 `ResumeStore.pdf_status()`。
// 后端要是加了第四种状态或改了 stale 的语义，**两处都要改**；漏改一处的后果是
// 这里回落到 missing 样式（见下面的 `?? RESUME_PDF_STATE_STYLE.missing`），不会崩。
function ResumePdfPill({ state }: { state: string }) {
  const s = RESUME_PDF_STATE_STYLE[state] ?? RESUME_PDF_STATE_STYLE.missing
  return (
    <span
      className="rounded-full px-2 py-0.5 text-[11.5px] font-semibold"
      style={{ background: s.bg, color: s.color }}
      title={s.hint}
    >
      {s.label}
    </span>
  )
}

function StatusBadge({ status }: { status: Status }) {
  const s = STATUS_STYLE[status]
  return (
    <span className="rounded-full px-2 py-0.5 text-[12px] font-semibold" style={{ background: s.bg, color: s.color }}>
      {s.label}
    </span>
  )
}

function FilterBar({ value, onChange }: { value: Filter; onChange: (f: Filter) => void }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {(['pending', 'approved', 'rejected', 'all'] as Filter[]).map((f) => (
        <button
          key={f}
          type="button"
          onClick={() => onChange(f)}
          className={`rounded-lg px-3 py-1.5 text-[13.5px] font-medium transition ${value === f ? 'text-text-1' : 'text-text-3 hover:text-text-2'}`}
          style={value === f
            ? { background: 'rgba(10,132,255,0.18)', boxShadow: 'inset 0 0 0 1px rgba(10,132,255,0.35)' }
            : { border: '1px solid rgba(255,255,255,0.08)' }}
        >
          {f === 'all' ? T_FILTER_ALL : STATUS_STYLE[f].label}
        </button>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Checkpoint 1
// ---------------------------------------------------------------------------

const CATEGORY_COLORS: Record<string, string> = {
  'AI NATIVE': '#bf5af2',
  '\u5f00\u53d1': '#0a84ff',
  '\u4ea7\u54c1': '#30d158',
  '\u8fd0\u8425': '#ff9f0a',
  '\u6e38\u620f': '#ff453a',
  '\u6d4b\u8bd5': '#40c8e0',
}

function categoryColor(name: string): string {
  return CATEGORY_COLORS[name] || '#84848c'
}

/**
 * \u540d\u989d\u70b9\u9635\u3002**\u79bb\u6563\u5706\u70b9\uff0c\u4e0d\u662f\u8fdb\u5ea6\u6761**\uff1a3 \u4e2a\u540d\u989d\u662f\u4e2a\u53ef\u6570\u7684\u91cf\uff0c
 * \u8fdb\u5ea6\u6761\u4f1a\u628a\u5b83\u6e32\u67d3\u6210\u4e00\u4e2a\u6bd4\u4f8b\uff0c\u662f\u9519\u7684\u8868\u8fbe\u3002\u4e0a\u9650\u672a\u77e5\u65f6**\u753b\u4e0d\u51fa\u70b9**\u2014\u2014
 * \u201c\u753b\u4e0d\u51fa\u6765\u201d\u672c\u8eab\u5c31\u662f\u8bda\u5b9e\u7684\u4fe1\u53f7\uff0c\u6bd4\u753b\u4e00\u6761\u7070\u6761\u5047\u88c5\u77e5\u9053\u5206\u6bcd\u597d\u3002
 */
function SlotMeter({ quota, approved, picked }: { quota: number; approved: number; picked: number }) {
  const over = Math.max(0, approved + picked - quota)
  const pips: { key: string; fill: string; ring: string }[] = []
  for (let i = 0; i < quota; i += 1) {
    if (i < approved) pips.push({ key: `a${i}`, fill: '#30d158', ring: '#30d158' })
    else if (i < approved + picked) pips.push({ key: `p${i}`, fill: 'transparent', ring: '#0a84ff' })
    else pips.push({ key: `e${i}`, fill: 'transparent', ring: '#48484a' })
  }
  for (let i = 0; i < over; i += 1) pips.push({ key: `o${i}`, fill: '#ff453a', ring: '#ff453a' })

  return (
    <div className="flex items-center gap-[5px]" aria-hidden>
      {pips.map((p) => (
        <span
          key={p.key}
          className="h-[9px] w-[9px] rounded-full"
          style={{ background: p.fill, boxShadow: `inset 0 0 0 1.5px ${p.ring}` }}
        />
      ))}
    </div>
  )
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <span className="flex items-baseline gap-1">
      <span className="text-[12.5px] text-text-3">{label}</span>
      <span className="font-mono text-[13.5px] font-semibold" style={{ color: color || '#ffffff' }}>{value}</span>
    </span>
  )
}

function SiteBar({
  site,
  info,
  total,
  picked,
  pickedByBucket,
  busy,
  overBudget,
  gateArmed,
  onSelectAll,
  onClear,
  onApprove,
  onReject,
  onStartFill,
  fillPending,
  onLimitChanged,
}: {
  site: string
  info: SiteInfo | undefined
  total: number
  picked: number
  pickedByBucket: Record<string, number>
  busy: boolean
  overBudget: number
  gateArmed: boolean
  onSelectAll: () => void
  onClear: () => void
  onApprove: () => void
  onReject: () => void
  // 看完整站、批完之后，一次性把已批准的岗位排进填表队列。
  onStartFill: () => void
  fillPending: number
  onLimitChanged: () => void
}) {
  const limits = info?.limits ?? []
  const approved = info?.approved_here ?? 0
  // **\u53ea\u6709 site \u7ea7\u7684\u4e0a\u9650\u80fd\u7b97\u95f8\u95e8**\u3002bucket \u7ea7\u7684\u62ff\u5168\u7ad9\u5df2\u6279\u51c6\u6570\u53bb\u6bd4\u662f\u9519\u7684
  // \u2014\u2014pending_jobs \u6ca1\u8bb0\u6bcf\u4e2a\u5c97\u4f4d\u5c5e\u4e8e\u54ea\u4e2a\u62db\u8058\u9879\u76ee\uff0c\u7b97\u51fa\u6765\u53ea\u4f1a\u4f4e\u4f30\u989d\u5ea6\u3002
  const gate = limits.find((l) => l.scope === 'site' && l.status === 'limited') || null
  const approvedByBucket = info?.approved_by_bucket ?? {}
  // scope='unclear' \u4ecd\u7136\u7b97\u4e0d\u4e86\uff1aagent \u81ea\u5df1\u90fd\u8bf4\u4e0d\u6e05\u8fd9\u6761\u4e0a\u9650\u7ba1\u591a\u5927\u8303\u56f4\u3002
  const unclearOnly = limits.some((l) => l.status === 'limited' && l.scope === 'unclear')
  // \u6ca1\u8bb0 bucket \u7684\u65e7\u5c97\u4f4d\u88ab\u9009\u4e2d\u65f6\uff0c\u5b83\u4eec\u7b97\u4e0d\u8fdb\u4efb\u4f55\u9879\u76ee\u7684\u540d\u989d\u2014\u2014\u5f97\u8bf4\u51fa\u6765\u3002
  const hasBucketLimits = limits.some((l) => l.scope === 'bucket')
  const pickedOutsideBuckets = (pickedByBucket[''] || 0) > 0 && hasBucketLimits

  return (
    <div
      className="sticky top-0 z-10 backdrop-blur"
      style={{ background: 'rgba(28,28,30,0.94)', borderBottom: '1px solid rgba(255,255,255,0.10)' }}
    >
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
        <span className="font-mono text-[14px] font-semibold text-text-1">{site}</span>
        <span className="text-[13px] text-text-2">{total} {T_C1_UNIT}</span>

        <span className="h-4 w-px" style={{ background: 'rgba(255,255,255,0.12)' }} />

        {limits.length === 0 ? (
          <span className="flex items-center gap-x-3">
            <span
              className="rounded-full px-2 py-0.5 text-[12.5px] font-semibold"
              style={{ background: 'rgba(255,255,255,0.07)', color: '#adadb8' }}
            >
              {T_SLOT_UNKNOWN}
            </span>
            <Stat label={T_SLOT_APPROVED} value={String(approved)} color={approved > 0 ? '#30d158' : undefined} />
            {picked > 0 && <Stat label={T_SLOT_PICKED} value={String(picked)} color="#2997ff" />}
          </span>
        ) : (
          <span className="flex flex-wrap items-center gap-x-4 gap-y-2">
            {limits.map((l) => {
              const key = l.scope === 'bucket' ? l.scope_name : ''
              // \u6bcf\u6761\u4e0a\u9650\u53ea\u770b\u5b83\u7ba1\u7684\u90a3\u90e8\u5206\uff1abucket \u7ea7\u53ea\u6570\u90a3\u4e2a\u9879\u76ee\u91cc\u7684\uff0c
              // site \u7ea7\u624d\u6570\u5168\u7ad9\u3002\u6df7\u7740\u6570\u5c31\u662f\u8fd9\u4e00\u8f6e\u8981\u4fee\u7684\u90a3\u4e2a\u9519\u3002
              const a = l.scope === 'bucket' ? (approvedByBucket[key] || 0) : approved
              const p = l.scope === 'bucket' ? (pickedByBucket[key] || 0) : picked
              const cap = l.max_applications || 0
              const over = Math.max(0, a + p - cap)
              if (l.status !== 'limited') {
                return (
                  <span
                    key={key || 'site'}
                    className="rounded-full px-2 py-0.5 text-[12.5px] font-semibold"
                    style={{ background: 'rgba(48,209,88,0.14)', color: '#30d158' }}
                  >
                    {T_SLOT_NO_LIMIT}
                  </span>
                )
              }
              return (
                <span key={key || 'site'} className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
                  {l.scope === 'bucket' && (
                    <span className="text-[12.5px] text-text-2">{l.scope_name}</span>
                  )}
                  {l.scope === 'unclear' && (
                    <span className="text-[12.5px]" style={{ color: '#ff9f0a' }}>{T_SCOPE_UNCLEAR}</span>
                  )}
                  {l.scope === 'unclear' ? (
                    <Stat label={T_SLOT_QUOTA} value={String(cap)} />
                  ) : (
                    <>
                      <SlotMeter quota={cap} approved={a} picked={p} />
                      <Stat label={T_SLOT_QUOTA} value={String(cap)} />
                      {a > 0 && <Stat label={T_SLOT_APPROVED} value={String(a)} color="#30d158" />}
                      {p > 0 && <Stat label={T_SLOT_PICKED} value={String(p)} color="#2997ff" />}
                      {over > 0
                        ? <Stat label={T_SLOT_OVER} value={String(over)} color="#ff453a" />
                        : <Stat label={T_SLOT_LEFT} value={String(cap - a - p)} />}
                    </>
                  )}
                </span>
              )
            })}
          </span>
        )}

        <LimitEditor site={site} current={gate} onDone={onLimitChanged} />

        <ClearSiteButton site={site} onDone={onLimitChanged} />

        <div className="flex-1" />

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={picked > 0 ? onClear : onSelectAll}
            className="rounded-lg px-2.5 py-1.5 text-[13px] text-text-2 transition hover:text-text-1"
            style={{ background: 'rgba(255,255,255,0.07)' }}
          >
            {picked > 0 ? T_C1_CLEAR : T_C1_SELECT_ALL}
          </button>
          <button
            type="button"
            disabled={busy || picked === 0}
            onClick={onApprove}
            className="rounded-lg px-3.5 py-1.5 text-[13.5px] font-semibold text-white transition disabled:cursor-not-allowed disabled:opacity-35"
            style={{ background: gateArmed ? '#ff453a' : '#30a14e' }}
          >
            {busy ? T_SAVING : gateArmed ? `${T_GATE_CONFIRM} ${picked}` : `${T_C1_BATCH_APPROVE} ${picked || ''}`}
          </button>
          <button
            type="button"
            disabled={busy || picked === 0}
            onClick={onReject}
            className="rounded-lg bg-bg-card2 px-3 py-1.5 text-[13.5px] text-text-2 disabled:opacity-35"
          >
            {T_C1_BATCH_REJECT}
          </button>
          {/* 装填：批准只是标记，真正开跑由这里触发。禁用时说明原因，而不是让人
              对着一个点不动的按钮猜。 */}
          <button
            type="button"
            disabled={busy || fillPending === 0}
            onClick={onStartFill}
            title={fillPending === 0 ? '\u6ca1\u6709\u5f85\u52d8\u5bdf\u7684\u5c97\u4f4d\uff1a\u5148\u6279\u51c6\u51e0\u4e2a\uff0c\u6216\u8005\u5b83\u4eec\u90fd\u5df2\u7ecf\u52d8\u5bdf\u8fc7\u4e86' : '\u628a\u8fd9\u4e2a\u7ad9\u5df2\u6279\u51c6\u3001\u8fd8\u6ca1\u52d8\u5bdf\u8fc7\u7684\u5c97\u4f4d\u4e00\u6b21\u6027\u6392\u8fdb\u961f\u5217\uff08\u6bcf\u4e2a\u5c97\u4f4d\u4e00\u6b21 m2\uff09'}
            className="rounded-lg px-3 py-1.5 text-[13.5px] font-medium transition disabled:cursor-not-allowed disabled:opacity-35"
            style={{ background: 'rgba(255,159,10,0.16)', color: '#ff9f0a' }}
          >
            {'\u5f00\u59cb\u52d8\u5bdf\u8868\u5355'}{fillPending > 0 ? ` ${fillPending}` : ''}
          </button>
        </div>
      </div>

      {(limits.length === 0 || unclearOnly || pickedOutsideBuckets || info?.brief || limits.some((l) => l.evidence)) && (
        <div className="space-y-1 px-4 pb-2.5 text-[12.5px] leading-relaxed text-text-3">
          {limits.length === 0 && <p>{T_SLOT_UNKNOWN_HINT}</p>}
          {unclearOnly && <p style={{ color: '#ff9f0a' }}>{T_GATE_NA}</p>}
          {pickedOutsideBuckets && <p style={{ color: '#ff9f0a' }}>{T_GATE_NO_BUCKET}</p>}
          {limits.map((l) => (
            <p key={`ev-${l.scope_name || 'site'}`}>
              {l.applied_count >= 0 && (
                <span>{T_SLOT_APPLIED} {l.applied_count} {T_C1_UNIT}{'\u3000'}</span>
              )}
              {l.evidence && (
                <span>
                  {T_SLOT_EVIDENCE}
                  {'\uff1a'}
                  {l.evidence}
                </span>
              )}
            </p>
          ))}
          {info?.brief && (
            <p>
              {T_BRIEF}
              {'\uff1a'}
              {info.brief.brief}
            </p>
          )}
        </div>
      )}

      {info?.manual && (
        <SiteManualBlock manual={info.manual} site={site} onResurveyed={onLimitChanged} />
      )}
    </div>
  )
}

// \u4eba\u5de5\u586b\u5199\u4e0a\u9650\u3002agent \u62ff\u4e0d\u5230\u8fd9\u6761\u4fe1\u606f\u662f\u5e38\u6001\uff08\u5b83\u53ea\u80fd\u987a\u8def\u649e\u89c1\uff0c
// \u800c\u987b\u77e5\u5e38\u5199\u5728\u7533\u8bf7\u9875\u4e0a\uff0c\u9009\u5c97\u9636\u6bb5\u6839\u672c\u4e0d\u4f1a\u53bb\u90a3\u91cc\uff09\u2014\u2014\u53ea\u505a\u5230\u201c\u4e0d\u649e\u8c0e\u201d\u4e0d\u591f\uff0c
// \u4eba\u5f97\u80fd\u628a\u81ea\u5df1\u77e5\u9053\u7684\u586b\u8fdb\u53bb\u3002
// 站点操作手册 + agent 的现场发现。
//
// important_notes 是 agent 唯一的逃生舱：手册字段全是闭集，遇到设计没覆盖的情况
// 只能写进这里。所以它非空时**必须显眼**——那是"系统该补一块了"的信号，
// 混在手册里折叠起来等于没有。手册本身反过来：默认折叠，平时没人需要看。
// 按站点清掉候选池。
//
// 这是"重收一个站"的前提：known_urls 取的是 pending_jobs 的全部 URL、**不看状态**，
// 标记成拒绝的岗位会被下一次 m1 永久跳过，只有真删才收得回来。
//
// **两步确认**：删除不可逆，而这个按钮就在站点标题旁边，误点的代价是一整个站的
// 候选池没了、还得重跑一次 m1。第一下只切状态，绝不发请求。
function ClearSiteButton({ site, onDone }: { site: string; onDone: () => void }) {
  const [armed, setArmed] = useState(false)
  const [busy, setBusy] = useState(false)

  if (!armed) {
    return (
      <button
        type="button"
        onClick={() => setArmed(true)}
        title={T_CLEAR_HINT}
        className="rounded-lg px-2.5 py-1 text-xs text-text-3 transition hover:bg-bg-card2 hover:text-text-1"
      >
        {T_CLEAR_SITE}
      </button>
    )
  }
  return (
    <span className="flex items-center gap-1.5">
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          setBusy(true)
          void API.clearSiteCandidates(site)
            .then(() => onDone())
            .finally(() => {
              setBusy(false)
              setArmed(false)
            })
        }}
        className="rounded-lg px-2.5 py-1 text-xs font-medium transition disabled:opacity-40"
        style={{ background: 'rgba(255,69,58,0.16)', color: '#ff453a' }}
      >
        {T_CLEAR_CONFIRM}
      </button>
      <button
        type="button"
        onClick={() => setArmed(false)}
        className="rounded-lg px-2 py-1 text-xs text-text-3 transition hover:text-text-1"
      >
        {T_CLEAR_CANCEL}
      </button>
    </span>
  )
}

// 作废一个站的操作手册，逼下一次 m1 重新勘察。
//
// **缓存需要失效路径**：手册是 survey_structure 的结论缓存，而 validate_manual
// 只验三条（总数定位符、维度非空、页面结构）——一份手册完全可以在它永远发现不了的
// 地方是错的（比如某个筛选维度到底是多选还是互斥），然后被后续每一次 run 无限期继承。
// 没有这个按钮之前，那种错误在产品里是不可修的。
//
// 同样两步确认：重探要花几十秒和一轮 LLM 调用，不该误点就发生。
function ResurveyButton({ site, onDone }: { site: string; onDone: () => void }) {
  const [armed, setArmed] = useState(false)
  const [busy, setBusy] = useState(false)

  if (!armed) {
    return (
      <button
        type="button"
        onClick={() => setArmed(true)}
        title={T_RESURVEY_HINT}
        className="rounded-lg px-2 py-1 text-xs text-text-3 transition hover:bg-bg-card2 hover:text-text-1"
      >
        {T_RESURVEY}
      </button>
    )
  }
  return (
    <span className="flex items-center gap-1.5">
      <button
        type="button"
        disabled={busy}
        onClick={() => {
          setBusy(true)
          void API.clearSiteManual(site)
            .then(() => onDone())
            .finally(() => {
              setBusy(false)
              setArmed(false)
            })
        }}
        className="rounded-lg px-2 py-1 text-xs font-medium transition disabled:opacity-40"
        style={{ background: 'rgba(255,159,10,0.16)', color: '#ff9f0a' }}
      >
        {T_RESURVEY_CONFIRM}
      </button>
      <button
        type="button"
        onClick={() => setArmed(false)}
        className="rounded-lg px-2 py-1 text-xs text-text-3 transition hover:text-text-1"
      >
        {T_CLEAR_CANCEL}
      </button>
    </span>
  )
}

function SiteManualBlock({ manual, site, onResurveyed }:
                         { manual: SiteManualInfo; site: string; onResurveyed: () => void }) {
  return (
    <div className="px-4 pb-3">
      {manual.important_notes && (
        <div
          className="mb-2 rounded-xl px-3 py-2 text-[12.5px] leading-relaxed"
          style={{ background: 'rgba(255,159,10,0.14)', border: '1px solid rgba(255,159,10,0.35)', color: '#ff9f0a' }}
        >
          <span className="font-semibold">{T_MANUAL_NOTE}</span>
          {'\uff1a'}
          {manual.important_notes}
        </div>
      )}
      <details>
        <summary className="cursor-pointer select-none text-[12.5px] text-text-3 transition hover:text-text-1">
          {T_SITE_MANUAL}
          {'\uff08'}
          {T_MANUAL_SURVEYED}
          {' '}
          {manual.updated_at.slice(0, 16).replace('T', ' ')}
          {'\uff09'}
        </summary>
        <div className="mt-1.5">
          <ResurveyButton site={site} onDone={onResurveyed} />
        </div>
        <dl className="mt-1.5 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-[12.5px] text-text-3">
          {MANUAL_FIELDS.map(([key, label]) => (
            <Fragment key={key}>
              <dt>{label}</dt>
              <dd className="font-mono text-text-2">{String(manual[key] ?? '') || '\u2014'}</dd>
            </Fragment>
          ))}
          {manual.dimensions.length > 0 && (
            <>
              <dt>{T_MANUAL_DIMS}</dt>
              <dd className="text-text-2">
                {manual.dimensions
                  .map((d) => `${d.name}(${d.options.length})`)
                  .join('\u3001')}
              </dd>
            </>
          )}
        </dl>
      </details>
    </div>
  )
}

// 手册里适合平铺展示的闭集字段。dimensions 是列表，单独渲染。
const MANUAL_FIELDS: [keyof SiteManualInfo, string][] = [
  ['job_url_source', '\u53d6 URL'],
  ['row_split', '\u5207\u884c'],
  ['pagination', '\u7ffb\u9875'],
  ['filter_interaction', '\u7b5b\u9009\u5668'],
  ['row_anchor', '\u884c\u951a\u70b9'],
]
const T_MANUAL_DIMS = '\u7b5b\u9009\u7ef4\u5ea6'

function LimitEditor({ site, current, onDone }: { site: string; current: SiteLimitInfo | null; onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [value, setValue] = useState(String(current?.max_applications ?? ''))
  const [saving, setSaving] = useState(false)

  async function save(status: 'no_limit' | 'limited' | 'unknown') {
    setSaving(true)
    try {
      await API.setCheckpoint1SiteLimit(site, {
        // \u4eba\u586b\u7684\u9ed8\u8ba4\u6309\u5168\u7ad9\u7b97\uff1a\u4eba\u8bf4\u5f97\u6e05\u8303\u56f4\uff0c\u8bf4\u4e0d\u6e05\u4e5f\u4e0d\u4f1a\u53bb\u586b\u3002
        scope: 'site',
        status,
        max_applications: status === 'limited' ? Number(value) : undefined,
        evidence: status === 'limited' || status === 'no_limit' ? T_LIMIT_EDIT : undefined,
      })
      setOpen(false)
      onDone()
    } finally {
      setSaving(false)
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="rounded-lg px-2 py-1 text-[12.5px] text-text-3 underline decoration-dotted underline-offset-2 transition hover:text-text-1"
      >
        {current?.status === 'unknown' || !current ? T_LIMIT_EDIT : T_LIMIT_EDIT_SHORT}
      </button>
    )
  }

  return (
    <span className="flex flex-wrap items-center gap-1.5">
      <input
        type="number"
        min={1}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        placeholder={T_LIMIT_PLACEHOLDER}
        className="w-[7.5rem] rounded-lg px-2 py-1 font-mono text-[13px] text-white focus:outline-none"
        style={{ background: 'rgba(0,0,0,0.4)', border: '1px solid rgba(255,255,255,0.18)' }}
      />
      <button
        type="button"
        disabled={saving || !value || Number(value) < 1}
        onClick={() => void save('limited')}
        className="rounded-lg px-2.5 py-1 text-[12.5px] font-semibold text-white disabled:opacity-40"
        style={{ background: '#0071e3' }}
      >
        {T_LIMIT_SAVE}
      </button>
      <button
        type="button"
        disabled={saving}
        onClick={() => void save('no_limit')}
        className="rounded-lg bg-bg-card2 px-2.5 py-1 text-[12.5px] text-text-2"
      >
        {T_LIMIT_NO_LIMIT_BTN}
      </button>
      <button
        type="button"
        disabled={saving}
        onClick={() => void save('unknown')}
        className="rounded-lg px-2 py-1 text-[12.5px] text-text-3 transition hover:text-text-2"
      >
        {T_LIMIT_RESET}
      </button>
      <button
        type="button"
        onClick={() => setOpen(false)}
        className="rounded-lg px-2 py-1 text-[12.5px] text-text-3 transition hover:text-text-2"
      >
        {T_CANCEL}
      </button>
    </span>
  )
}

function CategoryPicker({
  value,
  options,
  disabled,
  onChange,
}: {
  value: string
  options: string[]
  disabled: boolean
  onChange: (v: string) => void
}) {
  const color = categoryColor(value)
  if (disabled) {
    return (
      <span className="rounded-full px-2.5 py-0.5 text-[12.5px] font-semibold" style={{ background: `${color}26`, color }}>
        {value || '\u2014'}
      </span>
    )
  }
  // \u4e0b\u62c9\u91cc\u53ea\u653e profile \u914d\u7f6e\u8fc7\u7684\u7c7b\u522b\uff1a\u7c7b\u522b\u662f\u5c01\u95ed\u96c6\u5408\uff0c\u81ea\u7531\u6587\u672c\u4f1a\u51ed\u7a7a\u9020\u51fa\u540d\u989d\u3002
  const known = options.includes(value) ? options : [value, ...options]
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-full px-2.5 py-0.5 text-[12.5px] font-semibold focus:outline-none"
      style={{ background: `${color}26`, color, border: `1px solid ${color}55` }}
    >
      {known.map((opt) => (
        <option key={opt} value={opt} style={{ background: '#1c1c1e', color: '#fff' }}>
          {opt}
        </option>
      ))}
    </select>
  )
}

function JobRow({
  job,
  categories,
  checked,
  category,
  busy,
  onToggle,
  onCategory,
  onApprove,
  onReject,
  onUndo,
  onGolden,
}: {
  job: PendingJob
  categories: string[]
  checked: boolean
  category: string
  busy: boolean
  onToggle: () => void
  onCategory: (v: string) => void
  onApprove: () => void
  onReject: () => void
  onUndo: () => void
  onGolden: (v: boolean) => void
}) {
  const editable = job.status === 'pending'
  const corrected = job.category_agent && category !== job.category_agent
  return (
    <div
      className="flex items-start gap-3.5 px-4 py-4 transition"
      style={{
        borderTop: '1px solid rgba(255,255,255,0.06)',
        background: checked ? 'rgba(10,132,255,0.09)' : 'transparent',
        boxShadow: checked ? 'inset 3px 0 0 0 #0a84ff' : 'none',
      }}
    >
      {editable && (
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          className="mt-1 h-[17px] w-[17px] shrink-0 accent-[#0a84ff]"
        />
      )}

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2.5">
          <span className="text-[15.5px] font-semibold leading-snug text-text-1">{job.title || job.url}</span>
          <CategoryPicker value={category} options={categories} disabled={!editable} onChange={onCategory} />
          {!editable && <StatusBadge status={job.status} />}
        </div>

        {job.why && (
          <p className="mt-1.5 max-w-[86ch] text-[13.5px] leading-relaxed text-text-2">{job.why}</p>
        )}

        {/* 岗位原文。Checkpoint 1 唯一的人工决策是"这个岗位该不该投"，判断所需的
            信息必须都在这一页上——只给一句 why 的话，人是在替 agent 的一句话背书。
            默认折叠：一屏十几条候选，全展开就没法扫了；字数放在标题上，一眼能看出
            哪条抓回来的其实是空壳。 */}
        {job.jd && (
          <details className="mt-2 max-w-[86ch]">
            <summary className="cursor-pointer select-none text-[12.5px] text-text-3 transition hover:text-text-1">
              {T_C1_JD}
              {'\uff08'}
              {job.jd.length}
              {'\u5b57\uff09'}
            </summary>
            <pre
              className="mt-1.5 max-h-72 overflow-auto whitespace-pre-wrap rounded-xl p-3 text-[12.5px] leading-relaxed text-text-2"
              style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.08)' }}
            >
              {job.jd}
            </pre>
          </details>
        )}

        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[12.5px] text-text-3">
          {job.company && <span>{job.company}</span>}
          <button
            type="button"
            onClick={() => void API.browseUrl(job.url)}
            className="underline decoration-dotted underline-offset-2 transition hover:text-text-1"
          >
            {T_C1_OPEN}
          </button>
          {job.status === 'rejected' && job.reason && (
            <span>
              {T_REASON_LABEL}
              {'\uff1a'}
              {job.reason}
            </span>
          )}
          {!editable && job.decided_at && (
            <span className="font-mono">
              {T_DECIDED_AT}
              {'\uff1a'}
              {job.decided_at.slice(0, 16).replace('T', ' ')}
            </span>
          )}
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2 text-[12.5px]">
          <span className="text-text-3">{T_RESUME_LABEL}</span>
          {job.resume.slug ? (
            <>
              <span
                className={job.resume.matched ? 'text-text-2' : 'font-medium'}
                style={job.resume.matched ? undefined : { color: '#ff9f0a' }}
              >
                {job.resume.name}
              </span>
              {!job.resume.matched && (
                <span
                  className="rounded-full px-2 py-0.5 text-[11.5px] font-semibold"
                  style={{ background: 'rgba(255,159,10,0.16)', color: '#ff9f0a' }}
                  title={job.resume.reason}
                >
                  {T_RESUME_FALLBACK}
                </span>
              )}
              <ResumePdfPill state={job.resume.pdf_state} />
            </>
          ) : (
            <span className="font-semibold" style={{ color: '#ff453a' }}>{T_RESUME_NONE}</span>
          )}
        </div>

        {(corrected || job.is_golden) && (
          <div className="mt-2 flex flex-wrap items-center gap-2">
            {corrected && (
              <span className="text-[12.5px]" style={{ color: '#ff9f0a' }}>
                {T_C1_CORRECTED}
                {'\uff1a'}
                {job.category_agent}
              </span>
            )}
            {job.is_golden ? (
              <span
                className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[12px] font-semibold"
                style={{ background: 'rgba(255,214,10,0.16)', color: '#ffd60a' }}
              >
                {T_C1_IS_GOLDEN}
                <button
                  type="button"
                  onClick={() => onGolden(false)}
                  className="underline decoration-dotted underline-offset-2 opacity-75 transition hover:opacity-100"
                >
                  {T_C1_UNDO_GOLDEN}
                </button>
              </span>
            ) : (
              corrected && (
                <button
                  type="button"
                  title={T_C1_GOLDEN_HINT}
                  onClick={() => onGolden(true)}
                  className="rounded-full px-2.5 py-0.5 text-[12px] font-semibold transition hover:brightness-125"
                  style={{ background: 'rgba(255,214,10,0.12)', color: '#ffd60a', border: '1px solid rgba(255,214,10,0.35)' }}
                >
                  {T_C1_MAKE_GOLDEN}
                </button>
              )
            )}
          </div>
        )}
      </div>

      {editable ? (
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            disabled={busy}
            onClick={onApprove}
            className="rounded-lg px-3 py-1.5 text-[13px] font-medium text-white transition disabled:opacity-40"
            style={{ background: '#30a14e' }}
          >
            {T_APPROVE}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={onReject}
            className="rounded-lg bg-bg-card2 px-3 py-1.5 text-[13px] text-text-2 transition disabled:opacity-40"
          >
            {T_REJECT}
          </button>
        </div>
      ) : (
        // 纠错入口，不是主操作——样式刻意跟批准/驳回拉开，只用文字+虚线下划线。
        <button
          type="button"
          disabled={busy}
          onClick={onUndo}
          title={T_UNDO_DECISION_HINT}
          className="shrink-0 self-start text-[12.5px] text-text-3 underline decoration-dotted underline-offset-2 opacity-75 transition hover:text-text-1 hover:opacity-100 disabled:opacity-40"
        >
          {T_UNDO_DECISION}
        </button>
      )}
    </div>
  )
}

function Checkpoint1() {
  const [jobs, setJobs] = useState<PendingJob[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [sites, setSites] = useState<Record<string, SiteInfo>>({})
  const [filter, setFilter] = useState<Filter>('pending')
  const [checkedIds, setCheckedIds] = useState<number[]>([])
  // \u672c\u5730\u7c7b\u522b\u6539\u52a8\uff0c\u952e\u662f job.id\u3002\u63d0\u4ea4\u65f6\u624d\u843d\u5e93\u2014\u2014\u5148\u6539\u540e\u6279\uff0c\u8ddf\u9010\u6761\u70b9\u6279\u51c6\u7684\u987a\u5e8f\u65e0\u5173\u3002
  const [edited, setEdited] = useState<Record<number, string>>({})
  const [busy, setBusy] = useState(false)
  const [rejecting, setRejecting] = useState<number[] | null>(null)
  const [rejectReason, setRejectReason] = useState('')
  // \u8d85\u540d\u989d\u65f6\u7684\u95f8\u95e8\uff1a\u7b2c\u4e00\u4e0b\u53ea\u628a\u6309\u94ae\u53d8\u6210\u201c\u4ecd\u8981\u6279\u51c6\u201d\uff0c\u7b2c\u4e8c\u4e0b\u624d\u771f\u63d0\u4ea4\u3002
  // \u4e0d\u786c\u62e6\uff08\u4e0a\u9650\u53ef\u80fd\u8fc7\u671f\u3001\u53ef\u80fd agent \u8bfb\u9519\uff09\uff0c\u4f46\u4e5f\u4e0d\u80fd\u4e00\u4e0b\u5c31\u8fc7\u3002
  const [gatedSite, setGatedSite] = useState<string | null>(null)

  const refresh = () => {
    API.getCheckpoint1Jobs(filter === 'all' ? undefined : filter)
      .then((r) => {
        setJobs(r.jobs)
        setCategories(r.categories)
        setSites(r.sites || {})
        setCheckedIds([])
        setEdited({})
        setGatedSite(null)
      })
      .catch(() => setJobs([]))
  }

  useEffect(() => { refresh() }, [filter])

  const categoryOf = (job: PendingJob) => edited[job.id] ?? job.category

  // \u6309\u7ad9\u70b9\u5206\u7ec4\uff1a\u540d\u989d\u662f\u6309\u7ad9\u7b97\u7684\uff0c\u5206\u7ec4\u624d\u80fd\u628a\u9884\u7b97\u548c\u5b83\u7ba1\u7684\u90a3\u6279\u5c97\u4f4d\u653e\u5728\u4e00\u8d77\u3002
  const groups = useMemo(() => {
    const map = new Map<string, PendingJob[]>()
    for (const j of jobs) {
      const key = j.site_name || '\u672a\u77e5\u7ad9\u70b9'
      if (!map.has(key)) map.set(key, [])
      map.get(key)!.push(j)
    }
    return [...map.entries()]
  }, [jobs])

  const byCategory = useMemo(() => {
    const counts = new Map<string, number>()
    for (const j of jobs) {
      const c = categoryOf(j) || '\u672a\u5206\u7c7b'
      counts.set(c, (counts.get(c) || 0) + 1)
    }
    return [...counts.entries()]
  }, [jobs, edited])

  function toggle(id: number) {
    setCheckedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
    setGatedSite(null)
  }

  async function startFill(site: string) {
    // 批准只标记，真正开跑在这里。一次把这个站所有待填表的岗位排进队列——
    // 数量由后端算（差集规则只有一份实现），这里只负责触发和刷新。
    setBusy(true)
    try {
      await API.startSiteFill(site)
      // \u53cd\u9988\u9760\u4e24\u5904\u73b0\u6210\u7684\u4e1c\u897f\uff1a\u6309\u94ae\u4e0a\u7684\u6570\u5b57\u4f1a\u4ece N \u53d8 0\uff0c\u300c\u961f\u5217\u300d\u9875\u51fa\u73b0\u5bf9\u5e94\u6761\u76ee\u3002
      // \u4e0d\u4e3a\u4e00\u53e5\u63d0\u793a\u5f15\u5165\u4e00\u5957\u901a\u77e5\u673a\u5236\u2014\u2014\u8fd9\u4e2a\u7ec4\u4ef6\u672c\u6765\u6ca1\u6709\u3002
      refresh()
    } finally {
      setBusy(false)
    }
  }

  async function markGolden(id: number, golden: boolean) {
    const job = jobs.find((j) => j.id === id)
    if (!job) return
    setBusy(true)
    try {
      // \u786e\u8ba4 golden \u65f6\u628a\u5f53\u524d\u9009\u7684\u7c7b\u522b\u4e00\u5e76\u843d\u5e93\u2014\u2014\u7c7b\u522b\u4fee\u6539\u5728\u672c\u5730 state \u91cc\uff0c
      // \u53ea\u53d1 is_golden \u7684\u8bdd\uff0c\u6837\u4f8b\u5e93\u91cc\u5b58\u7684\u4f1a\u662f agent \u7684\u539f\u503c\uff0c\u6559\u7684\u5c31\u662f\u9519\u7684\u90a3\u4e2a\u3002
      const r = await API.reviewCheckpoint1Job(id, {
        category: golden ? categoryOf(job) : undefined,
        is_golden: golden,
      })
      setJobs((prev) => prev.map((j) => (j.id === id ? r.job : j)))
      setEdited((prev) => {
        const next = { ...prev }
        delete next[id]
        return next
      })
    } finally {
      setBusy(false)
    }
  }

  async function decide(ids: number[], decision: 'approved' | 'rejected', reason?: string) {
    if (ids.length === 0) return
    setBusy(true)
    try {
      const categoriesPayload: Record<string, string> = {}
      for (const id of ids) {
        const job = jobs.find((j) => j.id === id)
        if (job) categoriesPayload[String(id)] = categoryOf(job)
      }
      await API.decideCheckpoint1Batch(decision, ids, { categories: categoriesPayload, reason })
      refresh()
      setRejecting(null)
      setRejectReason('')
    } finally {
      setBusy(false)
    }
  }

  // 撤销不需要区分“填过表没有”——已经填过表的岗位靠 pending_applications.source_job_id
  // 那条回指记录挡住二次入队，撤销/重批不会碰它，细节在后端 undo_pending_job_decision。
  async function undo(id: number) {
    setBusy(true)
    try {
      await API.undoCheckpoint1Job(id)
      refresh()
    } finally {
      setBusy(false)
    }
  }

  function pickedByBucketOf(siteJobs: PendingJob[], pickedIds: number[]): Record<string, number> {
    const out: Record<string, number> = {}
    for (const j of siteJobs) {
      if (pickedIds.includes(j.id)) out[j.bucket] = (out[j.bucket] || 0) + 1
    }
    return out
  }

  function overBudgetOf(site: string, picked: number): number {
    // \u53ea\u5bf9 site \u7ea7\u4e0a\u9650\u7b97\u3002bucket \u7ea7\u7684\u7b97\u4e0d\u4e86\uff08\u4e0d\u77e5\u9053\u6bcf\u4e2a\u5c97\u4f4d\u5c5e\u4e8e\u54ea\u4e2a
    // \u62db\u8058\u9879\u76ee\uff09\uff0c\u7b97\u4e86\u53cd\u800c\u4f1a\u628a\u4eba\u62e6\u5728\u672c\u6765\u53ef\u4ee5\u6295\u7684\u5c97\u4f4d\u5916\u9762\u3002
    const info = sites[site]
    const gate = info?.limits.find((l) => l.scope === 'site' && l.status === 'limited')
    if (!gate || gate.max_applications === null) return 0
    return Math.max(0, info.approved_here + picked - gate.max_applications)
  }

  /** \u4efb\u4f55\u4e00\u4e2a\u62db\u8058\u9879\u76ee\u8d85\u4e86\u90fd\u7b97\u8d85\u2014\u2014\u95f8\u95e8\u53ea\u9700\u8981\u77e5\u9053\u201c\u8981\u4e0d\u8981\u62e6\u4e00\u4e0b\u201d\u3002 */
  function overBudgetByBucket(site: string, siteJobs: PendingJob[], pickedIds: number[]): number {
    const info = sites[site]
    if (!info) return 0
    const pb = pickedByBucketOf(siteJobs, pickedIds)
    let worst = 0
    for (const l of info.limits) {
      if (l.scope !== 'bucket' || l.status !== 'limited' || l.max_applications === null) continue
      const a = info.approved_by_bucket[l.scope_name] || 0
      const p = pb[l.scope_name] || 0
      worst = Math.max(worst, a + p - l.max_applications)
    }
    return Math.max(0, worst)
  }

  function approveSite(site: string, ids: number[], siteJobs: PendingJob[]) {
    const over = overBudgetOf(site, ids.length) + overBudgetByBucket(site, siteJobs, ids)
    if (over > 0 && gatedSite !== site) {
      setGatedSite(site) // \u7b2c\u4e00\u4e0b\uff1a\u53ea\u4e0a\u819b\uff0c\u4e0d\u63d0\u4ea4
      return
    }
    void decide(ids, 'approved')
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3.5">
      <p className="text-[14.5px] leading-relaxed text-text-2">
        <span className="text-text-1">{T_C1_INTRO}</span>
        {T_C1_INTRO_2}
      </p>

      <div className="flex flex-wrap items-center justify-between gap-3">
        <FilterBar value={filter} onChange={setFilter} />
        <div className="flex flex-wrap items-center gap-1.5">
          {byCategory.map(([name, n]) => (
            <span
              key={name}
              className="rounded-full px-2.5 py-1 text-[12.5px] font-medium"
              style={{ background: `${categoryColor(name)}20`, color: categoryColor(name) }}
            >
              {name} {n}
            </span>
          ))}
        </div>
      </div>

      {rejecting && (
        <div className="space-y-2 rounded-xl p-3.5" style={{ background: 'rgba(255,69,58,0.08)', border: '1px solid rgba(255,69,58,0.25)' }}>
          <textarea
            value={rejectReason}
            onChange={(e) => setRejectReason(e.target.value)}
            rows={2}
            placeholder={T_REJECT_REASON_PLACEHOLDER}
            className="w-full rounded-xl px-3 py-2 text-[13.5px] text-white focus:outline-none"
            style={{ background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(255,69,58,0.3)' }}
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => void decide(rejecting, 'rejected', rejectReason.trim() || undefined)}
              className="rounded-lg px-3.5 py-1.5 text-[13.5px] font-semibold text-white disabled:opacity-50"
              style={{ background: '#ff453a' }}
            >
              {busy ? T_SAVING : T_CONFIRM_REJECT}
            </button>
            <button
              type="button"
              onClick={() => { setRejecting(null); setRejectReason('') }}
              className="rounded-lg bg-bg-card2 px-3.5 py-1.5 text-[13.5px] text-text-2"
            >
              {T_CANCEL}
            </button>
          </div>
        </div>
      )}

      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
        {jobs.length === 0 && (
          <div className="rounded-2xl p-8 text-center" style={{ border: '1px dashed rgba(255,255,255,0.12)' }}>
            <p className="text-[15px] font-semibold text-text-1">{T_C1_EMPTY_T}</p>
            <p className="mt-2 font-mono text-[12.5px] leading-relaxed text-text-3">{T_C1_EMPTY_D}</p>
          </div>
        )}

        {groups.map(([site, siteJobs]) => {
          const pendingIds = siteJobs.filter((j) => j.status === 'pending').map((j) => j.id)
          const pickedIds = pendingIds.filter((id) => checkedIds.includes(id))
          return (
            <section key={site} className="overflow-hidden rounded-2xl bg-bg-card shadow-card">
              <SiteBar
                site={site}
                info={sites[site]}
                total={siteJobs.length}
                picked={pickedIds.length}
                busy={busy}
                pickedByBucket={pickedByBucketOf(siteJobs, pickedIds)}
                overBudget={overBudgetOf(site, pickedIds.length) + overBudgetByBucket(site, siteJobs, pickedIds)}
                gateArmed={gatedSite === site}
                onSelectAll={() => setCheckedIds((prev) => [...new Set([...prev, ...pendingIds])])}
                onClear={() => { setCheckedIds((prev) => prev.filter((id) => !pendingIds.includes(id))); setGatedSite(null) }}
                onApprove={() => approveSite(site, pickedIds, siteJobs)}
                onReject={() => setRejecting(pickedIds)}
                onStartFill={() => void startFill(site)}
                fillPending={sites[site]?.fill_pending ?? 0}
                onLimitChanged={refresh}
              />
              {siteJobs.map((job) => (
                <JobRow
                  key={job.id}
                  job={job}
                  categories={categories}
                  checked={checkedIds.includes(job.id)}
                  category={categoryOf(job)}
                  busy={busy}
                  onToggle={() => toggle(job.id)}
                  onCategory={(v) => setEdited((prev) => ({ ...prev, [job.id]: v }))}
                  onApprove={() => void decide([job.id], 'approved')}
                  onReject={() => setRejecting([job.id])}
                  onUndo={() => void undo(job.id)}
                  onGolden={(v) => void markGolden(job.id, v)}
                />
              ))}
            </section>
          )
        })}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Checkpoint 2 -- field value approval (behaviour unchanged)
// ---------------------------------------------------------------------------

// 这个字段机器填不了，必须人来填。
// 证件号：从来不代填。unknown_fact：事实性字段但资料里没有，只有本人知道。
// **判据只写这一份**：列表徽章和批准闸共用它，否则加一档就会漏改其中一处，
// 而那的表现是“能批准一条其实还空着必填项的申请”。
export function needsHumanValue(f: PendingApplicationField): boolean {
  return f.kind === 'government_id' || (f.kind === 'unknown_fact' && f.required !== false)
}

function missingGovId(fields: PendingApplicationField[]): boolean {
  return fields.some((f) => needsHumanValue(f) && !f.candidate_value.trim())
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
        <p className="mt-1.5 text-[12.5px]" style={{ color: '#ff453a' }}>{T_NEEDS_MANUAL}</p>
      )}
    </button>
  )
}

function Checkpoint2() {
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
    return selected.fields.every((f) => !needsHumanValue(f) || (editedFields[f.field_id] ?? '').trim() !== '')
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
    <div className="grid min-h-0 flex-1 grid-cols-[360px_1fr] gap-4">
      <div className="flex min-h-0 flex-col gap-3">
        <p className="text-[14.5px] leading-relaxed text-text-2">
          <span className="text-text-1">{T_INTRO_A}</span>
          {T_INTRO_B}
        </p>

        {justSavedFacts && (
          <div className="rounded-lg px-3 py-1.5 text-[13px]" style={{ background: 'rgba(48,209,88,0.12)', color: '#30d158' }}>
            {'\u5df2\u8bb0\u4f4f\u65b0\u4fe1\u606f\uff1a'}{justSavedFacts.join('\u3001')}
          </div>
        )}

        <FilterBar value={filter} onChange={setFilter} />

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
                  <div key={f.field_id} className="rounded-xl p-3" style={{ background: 'rgba(255,255,255,0.03)', border: `1px solid ${needsHumanValue(f) && isEmpty && editable ? 'rgba(255,69,58,0.4)' : 'rgba(255,255,255,0.07)'}` }}>
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
                        placeholder={needsHumanValue(f) ? T_NEEDS_MANUAL : ''}
                        className="w-full rounded-lg px-3 py-1.5 text-[14px] text-white focus:outline-none"
                        style={{ background: 'rgba(0,0,0,0.35)', border: `1px solid ${needsHumanValue(f) && isEmpty ? 'rgba(255,69,58,0.4)' : 'rgba(255,255,255,0.1)'}` }}
                      />
                    ) : (
                      <p className="text-[14px] text-text-2">{value || '\u2014'}</p>
                    )}
                    {editable && (f.candidates?.length ?? 0) > 1 && (
                      <div className="mt-2">
                        <p className="text-[12px] text-text-3">{T_CANDIDATES}</p>
                        <div className="mt-1 flex flex-wrap gap-1.5">
                          {f.candidates!.map((c: FieldCandidate) => {
                            const on = value === c.value
                            return (
                              <button
                                key={c.value}
                                type="button"
                                onClick={() => setEditedFields((prev) => ({ ...prev, [f.field_id]: c.value }))}
                                className="rounded-lg px-2.5 py-1 text-left text-[12.5px] transition"
                                style={on
                                  ? { background: 'rgba(10,132,255,0.20)', color: '#fff', border: '1px solid rgba(10,132,255,0.5)' }
                                  : { background: 'rgba(255,255,255,0.05)', color: '#adadb8', border: '1px solid rgba(255,255,255,0.12)' }}
                              >
                                <span className="font-medium">{c.value}</span>
                                {c.context && <span className="ml-1.5 text-text-3">{c.context}</span>}
                              </button>
                            )
                          })}
                        </div>
                      </div>
                    )}
                  </div>
                )
              })}
            </div>

            {selected.screenshot && (
              <div className="space-y-1.5 border-t border-border-subtle pt-3.5">
                <p className="text-[13px] font-semibold text-text-1">{T_SCREENSHOT}</p>
                <p className="text-[12.5px] leading-relaxed text-text-3">{T_SCREENSHOT_HINT}</p>
                <a
                  href={`/api/pending-applications/screenshot/${selected.screenshot}`}
                  target="_blank"
                  rel="noreferrer"
                  className="block overflow-hidden rounded-xl"
                  style={{ border: '1px solid rgba(255,255,255,0.12)' }}
                >
                  <img
                    src={`/api/pending-applications/screenshot/${selected.screenshot}`}
                    alt={T_SCREENSHOT}
                    className="w-full"
                  />
                </a>
              </div>
            )}

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

// ---------------------------------------------------------------------------

type Tab = 'c1' | 'c2'

const TABS: { id: Tab; label: string; sub: string }[] = [
  { id: 'c1', label: T_TAB_1, sub: T_TAB_1_SUB },
  { id: 'c2', label: T_TAB_2, sub: T_TAB_2_SUB },
]

export default function CrossSiteApplications() {
  const [tab, setTab] = useState<Tab>('c1')

  return (
    <div className="relative flex h-full flex-col gap-4">
      <DevLabel name="CrossSiteApplications" float />

      <div className="flex shrink-0 items-center gap-1.5">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => setTab(t.id)}
            className={`flex items-baseline gap-1.5 rounded-lg px-3.5 py-1.5 text-[14px] font-medium transition ${tab === t.id ? 'text-text-1' : 'text-text-3 hover:text-text-2'}`}
            style={tab === t.id
              ? { background: 'rgba(10,132,255,0.18)', boxShadow: 'inset 0 0 0 1px rgba(10,132,255,0.35)' }
              : { border: '1px solid rgba(255,255,255,0.08)' }}
          >
            <span>{t.label}</span>
            <span className="font-mono text-[11.5px] text-text-3">{t.sub}</span>
          </button>
        ))}
      </div>

      {tab === 'c1' ? <Checkpoint1 /> : <Checkpoint2 />}
    </div>
  )
}
