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

export type PendingApplicationFieldKind = 'demographic' | 'open_question' | 'government_id'

export interface FieldCandidate {
  value: string
  context: string // 时间 + 首条要点，用来分清本科/硕士这种同名多值
}

export interface PendingApplicationField {
  field_id: string
  label: string
  kind: PendingApplicationFieldKind
  candidate_value: string
  // 池里对应不止一个值时的候选（本科+硕士两段学历对一个「学校名称」框）。
  // **系统刻意不挑**——连本人都得看页面才知道填哪个。空/缺省 = 没有歧义。
  candidates?: FieldCandidate[]
}

export interface PendingApplication {
  id: number
  site_name: string
  job_title: string
  company: string
  job_url: string
  fields: PendingApplicationField[]
  status: 'pending' | 'approved' | 'rejected'
  reason: string | null
  created_at: string
  decided_at: string | null
  // 表单整页截图的文件名（由代码拍，不是 agent——DeepSeek 没有视觉）。
  // 空串 = 没拍（没有需要补的字段）。
  screenshot: string
}

export interface PendingJob {
  id: number
  site_name: string
  url: string
  title: string
  company: string
  // category = 当前值（审批人改过就是人改的）；category_agent = agent 最初自报，
  // 永不覆写。两者不等的行就是一次 agent 归类纠错，别把它们当成同一个字段。
  category: string
  category_agent: string
  why: string
  status: 'pending' | 'approved' | 'rejected'
  reason: string | null
  found_at: string
  decided_at: string | null
  // 审批人确认过"这条纠正拿去教 agent"。确认过的会被渲染进选岗 prompt 当例子；
  // 只是改了类别但没确认的不会——随手一改不见得是标准案例。
  is_golden: boolean
  // 在站点的哪个招聘项目里找到的。投递上限常常按它算，'' = 老数据没记录。
  bucket: string
}

export interface SiteLimitInfo {
  site_name: string
  // 三态：unknown = 没找到相关说明（**不等于**没有限制）；no_limit = 页面明确写了不限；
  // limited = 看到了具体数字。把 unknown 显示成"无限制"会让人放心批一堆然后超额。
  status: 'unknown' | 'no_limit' | 'limited'
  // 这条上限管多大范围，agent 自己判断。bucket = 只管某个招聘项目（拓竹的真实情况
  // 就是「在"27届秋招（研发类）"招聘项目中最多投递 2 次」）；unclear = 它说不清。
  // 只有 site 级的才能拿全站已批准数去比——别的算出来是错的。
  scope: 'site' | 'bucket' | 'unclear'
  scope_name: string
  max_applications: number | null
  applied_count: number // -1 = 页面上没看到
  evidence: string // 页面原文，不是 agent 的转述
  seen_at: string
}

export interface SiteBriefInfo {
  site_name: string
  brief: string // agent 写的现场笔记，不是事实源
  updated_at: string
}

export interface SiteInfo {
  site_name: string
  approved_here: number // 这个站已批准了几个（后端统计全量，不受列表过滤影响）
  // 按招聘项目分别统计的已批准数。key='' 是没记录 bucket 的老数据，
  // 它们算不进任何项目的名额。
  approved_by_bucket: Record<string, number>
  buckets: string[] // 这个站出现过的招聘项目
  limits: SiteLimitInfo[] // 可能有好几条（按招聘项目分），空数组 = 什么都没记到
  brief: SiteBriefInfo | null
}

// ── 信息池变更提案 ──
// 机器改池（上传解析 / AI 整理）不再直接落盘，先出一份 diff 让人勾选。
// 池是求职者全部信息的唯一主库，而 build_pool 让 LLM 整体重写 sections、会丢内容；
// 原先只有"写前快照 + 事后回滚"，那是内容已被覆盖之后的补救。

export interface PoolDiffLine {
  op: ' ' | '-' | '+'
  text: string
}

export interface PoolDiffField {
  field: string
  old: string
  new: string
}

export interface PoolDiffBlock {
  key: string
  kind: 'added' | 'changed' | 'removed'
  title: string
  fields: PoolDiffField[]
  bullets: PoolDiffLine[]
  // added 默认勾上（新信息通常想要）；changed/removed 默认不勾——
  // 前者会覆盖已有内容，后者是删除，都得人看一眼。
  accept_default: boolean
}

export interface PoolDiffSection {
  name: string
  kind: 'added' | 'existing'
  blocks: PoolDiffBlock[]
}

export interface PoolDiffBasic {
  key: string
  kind: 'added' | 'changed'
  old: string
  new: string
  accept_default: boolean
}

export interface PoolDiff {
  basic_info: PoolDiffBasic[]
  sections: PoolDiffSection[]
  has_changes: boolean
}

export interface PoolPending {
  pending: boolean
  source?: string
  created_at?: string
  diff?: PoolDiff
}

export interface PersonalInfo {
  // 姓名/电话/邮箱的唯一真源是简历系统的信息池（info_pool.basic_info），这里只读展示，
  // 编辑入口在「简历」页——不重复建第二个写入口。
  basic: { name: string; phone: string; email: string }
  // 性别/出生日期/证件类型等身份事实，以及审批时自动记住的新字段；开放式字典，可增删。
  identity: Record<string, string>
}

export interface Profile {
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

// 「这份简历能不能真的发出去」——多站点投递只能用**已导出的 PDF**（后端不渲染，
// A4 排版的唯一实现在前端 resumeHtml.ts）。ready=有且不旧于简历内容；
// stale=有但简历改过之后没重新导出；missing=从没导出过。
export type ResumePdfState = 'ready' | 'stale' | 'missing'

export interface ResumeMeta {
  slug: string
  name: string
  target: string
  updated_at: string
  pdf_state?: ResumePdfState
  pdf_exported_at?: string
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

// w1/w2/w3 = Boss 直聘那条线；m1/m2 = 多站点 Layer 1（选岗 / 填表）。
// 后端 VALID_WORKFLOWS 早就包含 m1/m2，而这里漏了——队列页的 WF_META 是按
// 这个类型建的 Record，漏一个就是运行时 undefined → 整个 SPA 白屏。
export type WorkflowId = 'w1' | 'w2' | 'w3' | 'm1' | 'm2'

// Which workflows have parameters worth remembering between runs. The backend
// keeps the same list (server._DEFAULTABLE_WORKFLOWS); w3 and m2 have none --
// w3 sends whatever is approved, m2's job differs every time.
export type DefaultableWorkflow = 'w1' | 'w2' | 'm1'

export type WorkflowDefaults = Record<DefaultableWorkflow, Record<string, unknown>>

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
  getPoolPending: (): Promise<PoolPending> => requestJson('/api/pool/pending'),
  applyPoolPending: (accepted: string[]): Promise<{ ok: boolean; applied: number }> =>
    requestJson('/api/pool/pending/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ accepted }),
    }),
  discardPoolPending: (): Promise<{ ok: boolean }> =>
    requestJson('/api/pool/pending', { method: 'DELETE' }),
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
  getWorkflowDefaults: (): Promise<WorkflowDefaults> => requestJson('/api/workflow/defaults'),
  saveWorkflowDefault: (
    workflow: DefaultableWorkflow,
    updates: Record<string, unknown>,
  ): Promise<WorkflowDefaults> =>
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
  getPendingApplications: (status?: string): Promise<{ applications: PendingApplication[]; total: number }> => {
    const query = buildQuery({ status })
    return requestJson(`/api/pending-applications${query}`)
  },
  approvePendingApplication: (id: number, fields: PendingApplicationField[]): Promise<{ ok: boolean; saved_new_facts: string[] }> =>
    requestJson(`/api/pending-applications/${id}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ fields }),
    }),
  getPersonalInfo: (): Promise<PersonalInfo> => requestJson('/api/personal-info'),
  savePersonalInfo: (identity: Record<string, string>): Promise<{ ok: boolean; identity: Record<string, string> }> =>
    requestJson('/api/personal-info', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ identity }),
    }),
  rejectPendingApplication: (id: number, reason?: string): Promise<{ ok: boolean }> =>
    requestJson(`/api/pending-applications/${id}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    }),
  // ── Checkpoint 1：选岗审批 ──
  // categories 跟列表一起返回：前端渲染类别下拉必须有它，分两次请求只会多出一种
  // “下拉是空的”的中间状态。
  getCheckpoint1Jobs: (status?: string): Promise<{ jobs: PendingJob[]; total: number; categories: string[]; sites: Record<string, SiteInfo> }> => {
    const query = buildQuery({ status })
    return requestJson(`/api/checkpoint1/jobs${query}`)
  },
  // 人工填/改本站投递上限。不能假设 agent 一定拿得到这条信息，所以人得有入口。
  setCheckpoint1SiteLimit: (
    site: string,
    patch: { status: 'unknown' | 'no_limit' | 'limited'; max_applications?: number; evidence?: string; scope?: 'site' | 'bucket'; scope_name?: string },
  ): Promise<{ ok: boolean }> =>
    requestJson(`/api/checkpoint1/site-limit/${encodeURIComponent(site)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),
  // 纠正类别 / 标记 golden。不改审批状态——写的列跟 approve 不同，刻意分开端点。
  reviewCheckpoint1Job: (
    id: number,
    patch: { category?: string; is_golden?: boolean },
  ): Promise<{ ok: boolean; job: PendingJob }> =>
    requestJson(`/api/checkpoint1/jobs/${id}/review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    }),
  approveCheckpoint1Job: (id: number, category?: string): Promise<{ ok: boolean }> =>
    requestJson(`/api/checkpoint1/jobs/${id}/approve`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ category }),
    }),
  rejectCheckpoint1Job: (id: number, reason?: string): Promise<{ ok: boolean }> =>
    requestJson(`/api/checkpoint1/jobs/${id}/reject`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason }),
    }),
  decideCheckpoint1Batch: (
    decision: 'approved' | 'rejected',
    ids: number[],
    opts?: { categories?: Record<string, string>; reason?: string },
  ): Promise<{ ok: boolean; decided: number[]; skipped: number[] }> =>
    requestJson('/api/checkpoint1/batch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ decision, ids, ...opts }),
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
