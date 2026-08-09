import type { ProgressEvent } from '@/hooks/useWorkflowStream'

export interface WorkflowStatus {
  running: string | null
}

export interface Stats {
  stats: Record<string, unknown>
  onboarding: Record<string, unknown>
}

export interface ArchitectureLive {
  tables: { applications: number; hr_conversations: number; hr_messages: number }
  by_status: Record<string, number>
  by_stage: Record<string, number>
  running: string | null
}

export interface Job {
  job_id: string
  title: string
  company: string
  hr_name?: string
  city: string
  salary: string
  score?: number
  status: string
  applied_at?: string
  url: string
  created_at?: string
}

export interface JobsResponse {
  jobs: Job[]
  total: number
  page: number
  page_size: number
}

export interface ConversationMessage {
  sender: 'me' | 'hr' | 'system'
  text: string
  time: string
}

export interface Conversation {
  conv_id: string
  hr_name: string
  hr_title?: string
  company: string
  wechat_id?: string | null
  wechat_dismissed?: boolean
  wechat_pending?: boolean
  last_msg_preview: string
  last_msg_from: string
  last_synced: string
  last_msg_at?: string
  stage: string
  intent?: string
  // 'ok' = intent \u662f\u6700\u65b0\u4e00\u6b21\u5206\u6790\u7684\u7ed3\u679c\uff1b'pending' = \u4e0a\u6b21\u5206\u6790\u5931\u8d25(intent \u662f\u65e7\u503c)\uff0c\u4e0b\u8f6e\u91cd\u8bd5\uff1b
  // 'stale' = \u8d85\u51fa\u6d3b\u8dc3\u7a97\u53e3\uff0ctoo_old \u4f18\u5148\u4e8e unanalyzed\uff0c\u4e0d\u4f1a\u518d\u88ab\u5206\u6790
  analysis_state?: 'ok' | 'pending' | 'stale'
  suggested_reply?: string
  needs_reply?: boolean
  reply_status?: 'pending' | 'approved' | 'revision' | 'dismissed' | 'sent'
  reply_draft?: string
  resume_status?: 'queued' | null
  matched_resume?: string          // W2 \u6309\u5c97\u4f4d\u9009\u51fa\u7684\u300c\u5efa\u8bae\u53d1\u8fd9\u4e00\u4efd\u300d
  matched_resume_reason?: string
  status: string
  job_id?: string
  job_url?: string
  job_title?: string
  message_count?: number
  messages?: ConversationMessage[]
}

export interface WechatPending {
  conv_id: string
  hr_name: string
  hr_title: string
  company: string
  wechat_id: string
  job_url?: string
}

export interface PendingReply {
  conv_id: string
  hr_name: string
  company: string
  intent: string
  suggested_reply: string
  reply_status: 'pending' | 'approved' | 'revision'
  reply_draft: string
  last_synced: string
  job_url?: string
}

export interface Profile {
  name?: string
  keywords?: string[]
  cities?: string[]
  experience?: string[]
  degree?: string[]
  salary?: string
  scale?: string[]
  job_types?: string[]
  financing?: string[]
  districts?: string[]
  position_types?: string[]
  industries?: string[]
  boss_online?: boolean
  prompt_injection?: {
    global?: string
    score_job?: string
    analyze_intent?: string
    generate_reply?: string
  }
}


export interface PromptTemplate {
  name: string
  content: string
  default: string
  modified: boolean
  placeholders: string[]
}


export interface ScheduleWorkflowConfig {
  enabled: boolean
  times: string[]
  interval_enabled: boolean
  interval_minutes: number
  params: Record<string, unknown>
}

export interface SelfCheckCfg {
  enabled: boolean
  interval_minutes: number
  w1_max: number
  w2_max: number
  with_probes: boolean
}

export interface ScheduleConfig {
  apply: ScheduleWorkflowConfig
  check: ScheduleWorkflowConfig
  selfcheck?: SelfCheckCfg
  daily_limit?: number
  _next_runs?: Record<string, string | null>
  _next_interval_runs?: Record<string, string | null>
  _scheduler_running?: boolean
}

export type SchedulePayload = {
  apply?: Partial<ScheduleWorkflowConfig>
  check?: Partial<ScheduleWorkflowConfig>
  selfcheck?: Partial<SelfCheckCfg>
  daily_limit?: number
}

export interface SelfCheckStage {
  stage: string
  label: string
  ok: boolean
  duration_ms: number
  detail: string
}
export interface SelfCheckHistoryEntry {
  trigger_type: string
  started_at: string
  finished_at?: string
  ok?: boolean
  skipped_reason?: string
  params?: { w1_max: number; w2_max: number; with_probes: boolean }
  stages: SelfCheckStage[]
}

export interface ScheduleLogEntry {
  workflow: string
  trigger_type: string
  triggered_at: string
  result: 'success' | 'skipped' | 'error'
  skipped_reason: string | null
  summary: string | null
  duration_seconds: number
}

export interface RunSummaryItem {
  run_id: string
  pipeline: string
  filename: string
  started_at: string
  status: 'done' | 'failed' | 'running'
  duration_ms: number | null
  summary: Record<string, number> | null
}

export interface RunsResponse {
  runs: RunSummaryItem[]
  total: number
}

export interface FailedRunLogItem {
  run_id: string
  pipeline: string
  filename: string
  started_at: string
  status: string
  duration_ms: number | null
  summary: Record<string, unknown> | null
  size_bytes: number
}

export interface ApplyFailureScreenshotItem {
  filename: string
  label: string
  size_bytes: number
  mtime: string
}

export interface OpsArtifactsResponse {
  run_logs: FailedRunLogItem[]
  screenshots: ApplyFailureScreenshotItem[]
}

export interface DeleteOpsArtifactsResponse {
  run_logs: Record<string, boolean>
  screenshots: Record<string, boolean>
  deleted_count: number
}

export interface ToolEntry {
  tool: string
  scope: Record<string, string>
  status: string
  duration_ms: number | null
  data: Record<string, unknown>
  error: string | null
  ts: string
}

export interface StepEntry {
  step: string
  scope: Record<string, string>
  status: string
  duration_ms: number | null
  data: Record<string, unknown>
  error: string | null
  ts: string
  tools: ToolEntry[]
}

export interface BusinessEvent {
  event: string
  scope: Record<string, string>
  data: Record<string, unknown>
  ts: string
}

export interface RunDetail {
  run_id: string
  pipeline: string
  status: string
  started_at: string
  duration_ms: number | null
  summary: Record<string, number> | null
  steps: StepEntry[]
  business_events: BusinessEvent[]
}

// Legacy aliases kept for backward compat (remove when all consumers updated)
export type RunSummary = RunSummaryItem

export interface RunEvent {
  ts: string
  run_id: string
  workflow: string
  event_type: string
  visible: boolean
  data: Record<string, unknown>
}

export interface RunDetailResponse {
  run_id: string
  events: RunEvent[]
  total: number
}

// Full persisted event stream of one run, already in the live ProgressEvent shape
// (status mapped, ts epoch). Lets WorkflowTrack replay a finished run completely.
export interface RunEventsResponse {
  events: ProgressEvent[]
}

export interface SelfCheckProbe {
  name: string
  label: string
  ok: boolean
  duration_ms: number
  detail: string
}
export interface SelfCheckReport {
  ran_at: string
  ok: boolean
  probes: SelfCheckProbe[]
}

export interface RegressionFailure {
  name: string
  message: string
}
export interface RegressionFile {
  name: string
  passed: number
  failed: number
  skipped: number
  failures: RegressionFailure[]
}
export interface RegressionReport {
  ran_at: string
  ok: boolean
  total: number
  passed: number
  failed: number
  skipped: number
  duration_s: number
  exit_code: number | null
  files: RegressionFile[]
  collect_error?: string
  parse_error?: string
}

export interface InvariantCheck {
  name: string
  ok: boolean
  count: number
  detail: string
}
export interface InvariantReport {
  ran_at: string
  ok: boolean
  total_apps: number
  total_convs: number
  checks: InvariantCheck[]
}

export interface SmokeCheck {
  name: string
  ok: boolean
  /** Did this run actually exercise the path? Separate axis from ok: a run with
   *  nothing to apply and nothing to send passes every assertion while verifying
   *  nothing. Use fully_covered, not ok, to decide "verified". */
  covered: boolean
  detail: string
  duration_s: number
  summary: Record<string, unknown>
}
/** Verdict for one run, derived from its JSONL log. See docs/run-log-guide.md. */
export interface RunDiagnosis {
  run_id: string | null
  pipeline?: string
  /** false = legacy/absent log we cannot judge \u2014 NOT the same as "failed". */
  diagnosable?: boolean
  ok?: boolean
  complete?: boolean
  status?: string
  trigger?: string | null
  started_at?: string
  events_total?: number
  outbound?: Record<string, number>
  anomalies?: string[]
  params_ok?: boolean
  param_checks?: { name: string; expected: unknown; actual: unknown; ok: boolean }[]
  /** Pre-rendered text template, ready to display or hand to a model. */
  report?: string
}

export interface SmokeReport {
  ran_at: string
  ok: boolean
  fully_covered?: boolean
  /** Names of checks that ran without exercising their path. */
  uncovered?: string[]
  /** Paths this smoke deliberately never exercises (e.g. W3 sending replies). */
  not_covered_paths?: string[]
  mode?: 'dry' | 'live'
  params?: {
    dry_run: boolean
    w1_max: number
    w2_max: number
    score_threshold?: number | null
    no_response_days?: number | null
    stale_conv_days?: number | null
  }
  diagnostics?: RunDiagnosis[]
  diagnostics_verdict?: {
    judged: number
    total: number
    ok: boolean | null
    params_applied: boolean | null
    anomalies: string[]
  }
  duration_s: number
  checks: SmokeCheck[]
  error?: string
}

export interface FieldMarks {
  bold?: boolean
  italic?: boolean
  underline?: boolean
}
export interface ResumeBlock {
  title: string
  time: string
  bullets: string[]
  summary: string
  // \u5b57\u6bb5\u7ea7\u5bcc\u6587\u672c\uff1b\u7f3a\u7701 = \u7528\u6a21\u677f\u9884\u8bbe\uff08\u6807\u9898\u7c97\u4f53\u3001\u65e5\u671f\u7070\u8272\u2026\uff09
  style?: { title?: FieldMarks; time?: FieldMarks; bullets?: FieldMarks }
}
export interface ResumeBasicInfo {
  name: string
  phone: string
  email: string
  city: string
  degree: string
  target_title: string
}
export interface ResumeSection {
  name: string
  blocks: ResumeBlock[]
}
// v2.16 \u52a8\u6001\u5206\u533a\u5f62\u72b6\uff1a\u4fe1\u606f\u6c60\u4e0e\u6bcf\u4efd\u7b80\u5386\u5171\u7528\uff08sections \u6570\u7ec4\u987a\u5e8f\u5373\u5206\u533a\u987a\u5e8f\uff09
export interface ResumeBlocks {
  basic_info: ResumeBasicInfo
  self_description: string
  sections: ResumeSection[]
}

export interface ResumeMeta {
  slug: string
  name: string
  target: string
  updated_at: string
}
export interface ResumeIndex {
  active: string
  items: ResumeMeta[]
}
export interface ResumeExport {
  file: string
  size: number
  mtime: string
}
export interface PoolSnapshot {
  file: string
  saved_at: string
  blocks: number
  sections: number
  daily: boolean       // \u5f53\u5929\u6700\u65e9\u7684\u5b58\u6863\uff1a\u4e0d\u4f1a\u88ab\u540e\u7eed\u4fdd\u5b58\u6324\u6389
  is_current: boolean  // \u5185\u5bb9\u4e0e\u5f53\u524d\u4e00\u81f4 \u2192 \u6253\u7eff\u706f
}
export interface PoolCurrent {
  blocks: number
  sections: number
  saved_at: string
}

export interface ResumeTemplate {
  name: string
  keywords: string[]
  blocks: Array<{ cat: string; idx: number }>
  greeting_style: string
}
export interface ResumePlanSection {
  category: string
  title: string
  time: string
  bullets: string[]
}
export interface ResumePlan {
  job_id?: string
  job_title?: string
  company?: string
  resume?: { template_used: string; sections: ResumePlanSection[]; generated_at: string }
  greeting?: { text: string; generated_at: string }
}

export type WorkflowId = 'w1' | 'w2' | 'w3'

export interface QueueItem {
  id: string
  workflow: WorkflowId
  params: Record<string, unknown>
  source: string
  enqueued_at: string
  status: string
  started_at: string | null
  finished_at: string | null
  error: string | null
}

export interface QueueSnapshot {
  current: QueueItem | null
  pending: QueueItem[]
  recent: QueueItem[]
  paused: boolean
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const query = new URLSearchParams()

  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== '') {
      query.set(key, String(value))
    }
  })

  const text = query.toString()
  return text ? `?${text}` : ''
}

async function requestJson<T>(input: RequestInfo | URL, init?: RequestInit): Promise<T> {
  const response = await fetch(input, init)
  return handleJson<T>(response)
}

export const API = {
  getStats: (): Promise<Stats> => requestJson('/api/stats'),
  getArchitecture: (): Promise<ArchitectureLive> => requestJson('/api/architecture'),
  getJobs: (status?: string, page = 1, pageSize = 20): Promise<JobsResponse> => {
    const query = buildQuery({ status, page, page_size: pageSize })
    return requestJson(`/api/jobs${query}`)
  },
  getJob: (id: string): Promise<Job> => requestJson(`/api/jobs/${id}`),
  pause: () => requestJson('/api/pause', { method: 'POST' }),
  resume: () => requestJson('/api/resume', { method: 'POST' }),
  runSelfCheck: (): Promise<SelfCheckReport> =>
    requestJson('/api/selfcheck', { method: 'POST' }),
  runRegressionPytest: (): Promise<RegressionReport> =>
    requestJson('/api/regression/pytest', { method: 'POST' }),
  runRegressionInvariants: (): Promise<InvariantReport> =>
    requestJson('/api/regression/invariants', { method: 'POST' }),
  diagnoseRun: (runId: string): Promise<RunDiagnosis> =>
    requestJson(`/api/runs/${encodeURIComponent(runId)}/diagnose`),
  diagnoseRecentRuns: (
    params?: { limit?: number; pipeline?: string; only_problems?: boolean },
  ): Promise<{ runs: RunDiagnosis[]; count: number }> => {
    const q = new URLSearchParams()
    if (params?.limit) q.set('limit', String(params.limit))
    if (params?.pipeline) q.set('pipeline', params.pipeline)
    if (params?.only_problems) q.set('only_problems', 'true')
    const qs = q.toString()
    return requestJson(`/api/runs/diagnose/recent${qs ? `?${qs}` : ''}`)
  },
  triggerRegressionSmoke: (
    body?: {
      mode?: 'dry' | 'live'
      w1_max?: number
      w2_max?: number
      score_threshold?: number | null
      no_response_days?: number | null
      stale_conv_days?: number | null
    },
  ): Promise<{ status: string; mode?: string; w1_max?: number; w2_max?: number }> =>
    requestJson('/api/regression/smoke', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    }),
  getRegressionSmokeLast: (): Promise<{ report: SmokeReport | null }> =>
    requestJson('/api/regression/smoke/last'),
  getOnboarding: () => requestJson('/api/onboarding/status'),
  uploadResume: (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return requestJson('/api/resume/upload', { method: 'POST', body: formData })
  },
  getResumeBlocks: (): Promise<ResumeBlocks> => requestJson('/api/resume/blocks'),
  saveResumeBlocks: (body: ResumeBlocks): Promise<{ ok: boolean }> =>
    requestJson('/api/resume/blocks', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  // \u4fe1\u606f\u6c60\uff08v2.16\uff1a\u6c42\u804c\u8005\u5168\u90e8\u4fe1\u606f\u4e3b\u5e93\uff1b\u4e0a\u4f20\u89e3\u6790\u5165\u6c60\uff0c\u7b80\u5386\u4ece\u6c60\u7ec4\u5408\uff09
  getPool: (): Promise<ResumeBlocks> => requestJson('/api/pool'),
  getInterviewPrep: (): Promise<PrepDoc> => requestJson('/api/interview-prep'),
  savePool: (body: ResumeBlocks): Promise<{ ok: boolean }> =>
    requestJson('/api/pool', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  // \u8fd4\u56de\u4f53\u5e26 _stats\uff08\u6574\u7406\u524d\u540e\u6761\u76ee\u6570\uff09\u4f9b\u524d\u7aef\u63d0\u9192\u662f\u5426\u4e22\u5185\u5bb9
  buildPool: (self_description: string): Promise<ResumeBlocks & { _stats?: { before: number; after: number } }> =>
    requestJson('/api/pool/build', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ self_description }),
    }),
  // \u4fe1\u606f\u6c60\u5feb\u7167\uff08\u6bcf\u6b21\u4fdd\u5b58\u524d\u81ea\u52a8\u7559\u6863\uff0c\u53ef\u56de\u6eda\uff09
  getPoolSnapshots: (): Promise<{ snapshots: PoolSnapshot[]; current: PoolCurrent }> => requestJson('/api/pool/snapshots'),
  restorePoolSnapshot: (fname: string): Promise<ResumeBlocks> =>
    requestJson(`/api/pool/snapshots/${encodeURIComponent(fname)}/restore`, { method: 'POST' }),
  composeResume: (body: { job_title?: string; jd_text?: string; name?: string }): Promise<{ resume: ResumeMeta; sections: string[] }> =>
    requestJson('/api/resume/compose', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  // \u628a\u9884\u89c8\u7528\u7684\u7b80\u5386 HTML \u4ea4\u540e\u7aef Chromium \u6253\u5370\u6210 PDF\uff08\u4e0e\u9884\u89c8\u540c\u6e90\uff09\uff0c\u8fd4\u56de blob \u4f9b\u4e0b\u8f7d\uff1b
  // name \u7528\u4e8e\u670d\u52a1\u7aef\u300c\u6700\u8fd1\u751f\u6210\u300d\u5b58\u6863\u547d\u540d
  printResumePdf: async (html: string, name?: string): Promise<Blob> => {
    const r = await fetch('/api/resume/print-pdf', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ html, name }),
    })
    if (!r.ok) throw new Error(`PDF export failed (${r.status})`)
    return r.blob()
  },
  // \u591a\u4efd\u7b80\u5386\u7ba1\u7406
  getResumes: (): Promise<ResumeIndex> => requestJson('/api/resumes'),
  createResume: (name: string, target: string, copyFromActive = true): Promise<ResumeMeta> =>
    requestJson('/api/resumes', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, target, copy_from_active: copyFromActive }),
    }),
  updateResumeMeta: (slug: string, patch: { name?: string; target?: string }): Promise<ResumeMeta> =>
    requestJson(`/api/resumes/${slug}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),
  // \u8bfb\u67d0\u4efd\u7b80\u5386\u5185\u5bb9\uff08\u4e0d\u6fc0\u6d3b\uff09\u2014\u2014\u5df2\u4fdd\u5b58\u7b80\u5386\u5217\u8868\u7684\u9884\u89c8
  getResumeDoc: (slug: string): Promise<ResumeBlocks> => requestJson(`/api/resumes/${slug}/blocks`),
  activateResume: (slug: string): Promise<ResumeIndex> =>
    requestJson(`/api/resumes/${slug}/activate`, { method: 'POST' }),
  deleteResume: (slug: string): Promise<{ ok: boolean }> =>
    requestJson(`/api/resumes/${slug}`, { method: 'DELETE' }),
  // \u6700\u8fd1\u751f\u6210\uff08\u5bfc\u51fa\u5b58\u6863\uff09
  getResumeExports: (): Promise<{ exports: ResumeExport[] }> => requestJson('/api/resume/exports'),
  deleteResumeExport: (fname: string): Promise<{ ok: boolean }> =>
    requestJson(`/api/resume/exports/${encodeURIComponent(fname)}`, { method: 'DELETE' }),
  getResumeTemplates: (): Promise<ResumeTemplate[]> =>
    requestJson<{ templates: ResumeTemplate[] }>('/api/resume/templates').then((r) => r.templates),
  saveResumeTemplates: (templates: ResumeTemplate[]): Promise<{ ok: boolean }> =>
    requestJson('/api/resume/templates', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ templates }),
    }),
  tailorResume: (body: { job_id: string; job_title?: string; company?: string; jd_text?: string }): Promise<ResumePlan> =>
    requestJson('/api/resume/tailor/resume', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  tailorGreeting: (body: { job_id: string; job_title?: string; company?: string; jd_text?: string }): Promise<ResumePlan> =>
    requestJson('/api/resume/tailor/greeting', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  getResumePlan: (jobId: string): Promise<ResumePlan> => requestJson(`/api/resume/plan/${jobId}`),
  getConversations: (stage?: string): Promise<{ conversations: Conversation[] }> => {
    const query = buildQuery({ stage })
    return requestJson(`/api/conversations${query}`)
  },
  getPendingReplies: (): Promise<PendingReply[]> =>
    requestJson('/api/conversations/pending-replies'),
  approveReply: (conv_id: string): Promise<void> =>
    requestJson(`/api/conversations/${conv_id}/approve-reply`, { method: 'POST' }),
  reviseReply: (conv_id: string, draft: string): Promise<void> =>
    requestJson(`/api/conversations/${conv_id}/revise-reply`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ draft }),
    }),
  cancelReply: (conv_id: string): Promise<void> =>
    requestJson(`/api/conversations/${conv_id}/cancel-reply`, { method: 'POST' }),
  dismissReply: (conv_id: string): Promise<void> =>
    requestJson(`/api/conversations/${conv_id}/dismiss-reply`, { method: 'POST' }),
  dismissAllPendingReplies: (): Promise<{ ok: boolean; dismissed: number }> =>
    requestJson('/api/conversations/dismiss-all-pending-replies', { method: 'POST' }),
  rejectConversation: (conv_id: string): Promise<void> =>
    requestJson(`/api/conversations/${conv_id}/reject`, { method: 'POST' }),
  dismissWechat: (conv_id: string): Promise<void> =>
    requestJson(`/api/conversations/${conv_id}/dismiss-wechat`, { method: 'POST' }),
  getWechatPending: (): Promise<{ conversations: WechatPending[] }> =>
    requestJson('/api/conversations/wechat-pending'),
  markSent: (conv_id: string): Promise<void> =>
    requestJson(`/api/conversations/${conv_id}/mark-sent`, { method: 'POST' }),
  openInBrowser: (conv_id: string): Promise<{ ok: boolean; error?: string; code?: string; reason?: string }> =>
    requestJson(`/api/conversations/${conv_id}/open-in-browser`, { method: 'POST' }),
  queueResume: (conv_id: string): Promise<{ ok: boolean }> =>
    requestJson(`/api/conversations/${conv_id}/queue-resume`, { method: 'POST' }),
  cancelResume: (conv_id: string): Promise<{ ok: boolean }> =>
    requestJson(`/api/conversations/${conv_id}/cancel-resume`, { method: 'POST' }),
  getProfile: (): Promise<Profile> => requestJson('/api/profile'),
  saveProfile: (data: Profile) =>
    requestJson('/api/profile', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  getPrompts: (): Promise<PromptTemplate[]> => requestJson('/api/prompts'),
  savePrompt: (name: string, content: string): Promise<{ ok: boolean; modified: boolean }> =>
    requestJson(`/api/prompts/${encodeURIComponent(name)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    }),
  resetPrompt: (name: string): Promise<{ ok: boolean; modified: boolean }> =>
    requestJson(`/api/prompts/${encodeURIComponent(name)}/reset`, { method: 'POST' }),
  getWorkflowStatus: (): Promise<WorkflowStatus> => requestJson('/api/workflow/status'),
  getWorkflowDefaults: (): Promise<{ w1: Record<string, unknown>; w2: Record<string, unknown> }> =>
    requestJson('/api/workflow/defaults'),
  saveWorkflowDefault: (
    workflow: 'w1' | 'w2',
    updates: Record<string, unknown>,
  ): Promise<{ w1: Record<string, unknown>; w2: Record<string, unknown> }> =>
    requestJson('/api/workflow/defaults', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workflow, updates }),
    }),
  checkSession: () => requestJson('/api/check/session'),
  saveLogin: () => requestJson('/api/session/save-login', { method: 'POST' }),
  openLogin: (): Promise<{ status: string; reason?: string }> =>
    requestJson('/api/session/open-login', { method: 'POST' }),
  openBossBrowser: (): Promise<{ ok: boolean; url: string }> =>
    requestJson('/api/open-boss-browser', { method: 'POST' }),
  confirmLogin: (): Promise<{ status: string; session?: Record<string, unknown>; reason?: string }> =>
    requestJson('/api/session/confirm-login', { method: 'POST' }),
  triggerApplyWorkflow: (data: Record<string, unknown>) =>
    requestJson('/api/workflow/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  triggerReplyWorkflow: (data: Record<string, unknown>) =>
    requestJson('/api/workflow/reply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  triggerCheckWorkflow: (data: Record<string, unknown>) =>
    requestJson('/api/workflow/check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  stopWorkflow: () => requestJson('/api/workflow/stop', { method: 'POST' }),
  getWorkflowQueue: (): Promise<QueueSnapshot> => requestJson('/api/workflow/queue'),
  enqueueWorkflow: (workflow: WorkflowId, params: Record<string, unknown> = {}) =>
    requestJson('/api/workflow/queue', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ workflow, params }),
    }),
  enqueueWorkflowChain: (items: Array<{ workflow: WorkflowId; params?: Record<string, unknown> }>) =>
    requestJson('/api/workflow/queue/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ items }),
    }),
  removeQueueItem: (id: string) =>
    requestJson(`/api/workflow/queue/${id}`, { method: 'DELETE' }),
  clearWorkflowQueue: () => requestJson('/api/workflow/queue/clear', { method: 'POST' }),
  moveQueueItem: (id: string, direction: number) =>
    requestJson('/api/workflow/queue/move', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, direction }),
    }),
  reorderQueue: (ids: string[]) =>
    requestJson('/api/workflow/queue/reorder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ids }),
    }),
  pauseQueue: () => requestJson('/api/workflow/queue/pause', { method: 'POST' }),
  resumeQueue: () => requestJson('/api/workflow/queue/resume', { method: 'POST' }),
  getControlStatus: () => requestJson('/api/control/status'),
  getDistricts: (city?: string) => {
    const query = buildQuery({ city })
    return requestJson(`/api/filters/districts${query}`)
  },
  getPositions: () => requestJson('/api/filters/positions'),
  getIndustries: () => requestJson('/api/filters/industries'),
  previewSearch: (): Promise<{ ok: boolean; url: string }> =>
    requestJson('/api/preview/search', { method: 'POST' }),
  clearPendingJobs: (): Promise<{ deleted: number }> =>
    requestJson('/api/jobs/pending', { method: 'DELETE' }),
  clearErrorJobs: (): Promise<{ deleted: number }> =>
    requestJson('/api/jobs/error', { method: 'DELETE' }),
  browseUrl: (url: string): Promise<{ ok: boolean; reason?: string }> =>
    requestJson('/api/browse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    }),
  restartBackend: () => requestJson('/api/dev/restart', { method: 'POST' }),
  getLlmConfig: (): Promise<{
    capabilities: { fast: string; balanced: string; powerful: string }
    tool_providers: { score_job: string | null; analyze_intent: string | null }
    available_providers: string[]
  }> =>
    requestJson('/api/config/llm'),
  saveLlmConfig: (data: {
    capabilities: { fast: string; balanced: string; powerful: string }
    tool_providers: { score_job: string | null; analyze_intent: string | null }
  }) =>
    requestJson('/api/config/llm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  getSchedule: (): Promise<ScheduleConfig> =>
    requestJson('/api/schedule'),
  updateSchedule: (body: SchedulePayload): Promise<ScheduleConfig> =>
    requestJson<{ ok: boolean; config: ScheduleConfig }>('/api/schedule', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((r) => r.config),
  getScheduleLog: (limit = 20): Promise<ScheduleLogEntry[]> =>
    requestJson<{ log: ScheduleLogEntry[] }>(`/api/schedule/log?limit=${limit}`)
      .then((r) => r.log),
  runSelfCheckCycle: (body: { w1_max?: number; w2_max?: number; with_probes?: boolean } = {}): Promise<{ status: string }> =>
    requestJson('/api/selfcheck/cycle', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
  getSelfCheckHistory: (limit = 20): Promise<SelfCheckHistoryEntry[]> =>
    requestJson<{ history: SelfCheckHistoryEntry[] }>(`/api/selfcheck/history?limit=${limit}`)
      .then((r) => r.history),
  getRuns: (params?: { pipeline?: string }): Promise<RunsResponse> => {
    const query = buildQuery({ pipeline: params?.pipeline })
    return requestJson(`/api/runs${query}`)
  },
  getRunDetail: (runId: string): Promise<RunDetail> =>
    requestJson(`/api/runs/${runId}`),
  getRunEvents: (runId: string): Promise<RunEventsResponse> =>
    requestJson(`/api/runs/${runId}/events`),
  getOpsArtifacts: (): Promise<OpsArtifactsResponse> =>
    requestJson('/api/ops/artifacts'),
  deleteOpsArtifacts: (body: { run_logs: string[]; screenshots: string[] }): Promise<DeleteOpsArtifactsResponse> =>
    requestJson('/api/ops/artifacts/delete', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }),
}

export async function handleJson<T>(res: Response): Promise<T> {
  const isJson = res.headers.get('content-type')?.includes('application/json')
  const payload = isJson ? await res.json() : null

  if (!res.ok) {
    const detail =
      payload && typeof payload === 'object' && 'detail' in payload
        ? payload.detail
        : payload && typeof payload === 'object' && 'error' in payload
          ? payload.error
        : res.statusText
    throw new Error(typeof detail === 'string' && detail ? detail : `HTTP ${res.status}`)
  }

  return payload as T
}

export type PrepKind = 'project' | 'basics'
export interface PrepCard {
  q: string
  kind: PrepKind
  a: string
  evidence: string[]
  avoid: string
}
export interface PrepRole {
  key: string
  name: string
  pitch: string
  hook: string
  cards: PrepCard[]
}
export interface PrepDoc {
  roles: PrepRole[]
}
