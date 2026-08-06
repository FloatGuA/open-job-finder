import type { ProgressEvent } from '@/hooks/useWorkflowStream'

// \u628a\u539f\u59cb\u4e8b\u4ef6\u6d41\uff08step / tool / \u4e1a\u52a1\u4e8b\u4ef6\uff09\u7ffb\u8bd1\u6210\u4eba\u7c7b\u53ef\u8bfb\u7684\u4e00\u53e5\u8bdd\u3002\u5b9e\u65f6 SSE \u4e0e
// JSONL \u56de\u653e\u5171\u7528\u540c\u4e00\u5957\u89e3\u8bfb\uff0c\u4fdd\u8bc1\u4e24\u8fb9\u663e\u793a\u4e00\u81f4\u3002\u4eba\u8bdd\u7684\u300c\u6599\u300d\u4e3b\u8981\u5728 ev.detail \u91cc
// \uff08\u4e1a\u52a1\u4e8b\u4ef6\u5e26 score / intent / stage \u7b49\uff09\uff0c\u6240\u4ee5\u8fd9\u91cc\u8bfb detail \u800c\u4e0d\u662f\u673a\u5668\u5473\u7684 message\u3002

// \u6b65\u9aa4 / \u4e1a\u52a1\u4e8b\u4ef6\u540d -> \u4e2d\u6587\u77ed\u6807\u7b7e\uff08LiveLog \u5fbd\u7ae0\u4e0e\u56de\u9000\u6587\u6848\u7528\uff09
export const STEP_LABELS: Record<string, string> = {
  navigate: '\u5bfc\u822a',
  fetch_jd: '\u83b7\u53d6JD',
  apply: '\u6295\u9012',
  upsert: '\u843d\u5e93',
  read: '\u8bfb\u53d6',
  analyze: '\u5206\u6790',
  reply: '\u56de\u590d',
  resume: '\u53d1\u7b80\u5386',
  scan: '\u626b\u63cf',
  locate: '\u5b9a\u4f4d',
  send: '\u53d1\u9001',
  verify: '\u9a8c\u8bc1',
  finalize: '\u6536\u5c3e',
  start: '\u542f\u52a8',
  done: '\u5b8c\u6210',
  stop: '\u505c\u6b62',
  // \u4e1a\u52a1\u4e8b\u4ef6\uff08step \u540d = \u4e8b\u4ef6\u540d\uff09
  job_scored: '\u8bc4\u5206',
  job_skipped: '\u8df3\u8fc7',
  job_applied: '\u6295\u9012',
  job_apply_failed: '\u6295\u9012\u5931\u8d25',
  w1_rate_limited: '\u89e6\u53d1\u4e0a\u9650',
  w1_quota_warning: '\u63a5\u8fd1\u4e0a\u9650',
  db_write_failed: '\u843d\u5e93\u5931\u8d25',
  intent_analyzed: '\u610f\u56fe',
  llm_degraded: '\u964d\u7ea7',
  resume_sent: '\u53d1\u7b80\u5386',
  resume_already_sent: '\u7b80\u5386\u5df2\u53d1',
  resume_send_failed: '\u53d1\u7b80\u5386\u5931\u8d25',
  resume_locate_gave_up: '\u5b9a\u4f4d\u653e\u5f03',
  send_resume_error: '\u53d1\u7b80\u5386\u51fa\u9519',
  stage_advanced: '\u9636\u6bb5',
  conv_navigate_failed: '\u5b9a\u4f4d\u5931\u8d25',
  conv_timeout_closed: '\u8d85\u65f6\u5173\u95ed',
  job_no_response_rejected: '\u65e0\u56de\u5e94\u5173\u95ed',
  job_purged: '\u5df2\u6e05\u7406',
}

const TOOL_LABELS: Record<string, string> = {
  navigate_search_url: '\u6253\u5f00\u641c\u7d22\u9875',
  verify_current_url: '\u6821\u9a8c\u5f53\u524d\u9875',
  extract_card_list: '\u6293\u53d6\u804c\u4f4d\u5361\u7247',
  scroll_search_results: '\u6eda\u52a8\u52a0\u8f7d',
  click_card_open_panel: '\u6253\u5f00\u804c\u4f4d\u8be6\u60c5',
  read_panel_jd: '\u8bfb\u53d6 JD',
  decode_job_salary: '\u89e3\u6790\u85aa\u8d44',
  score_job: '\u8bc4\u5206',
  click_apply_button: '\u70b9\u51fb\u6295\u9012',
  handle_apply_dialog: '\u5904\u7406\u6295\u9012\u5f39\u7a97',
  upsert_application: '\u5199\u5165\u6295\u9012\u8bb0\u5f55',
  navigate_to_chat_list: '\u6253\u5f00\u4f1a\u8bdd\u5217\u8868',
  extract_conversation_list: '\u6293\u53d6\u4f1a\u8bdd\u5217\u8868',
  scroll_chat_list: '\u6eda\u52a8\u4f1a\u8bdd\u5217\u8868',
  get_approved_replies: '\u8bfb\u53d6\u5f85\u53d1\u56de\u590d',
  get_conversation_states: '\u8bfb\u53d6\u4f1a\u8bdd\u72b6\u6001',
  navigate_to_conversation: '\u8fdb\u5165\u4f1a\u8bdd',
  read_messages: '\u8bfb\u53d6\u6d88\u606f',
  write_hr_messages: '\u5199\u5165\u6d88\u606f',
  detect_resume_request: '\u68c0\u6d4b\u7b80\u5386\u8bf7\u6c42',
  analyze_hr_intent: '\u5206\u6790 HR \u610f\u56fe',
  update_hr_analysis: '\u66f4\u65b0\u610f\u56fe\u5206\u6790',
  accept_resume_card: '\u63a5\u53d7\u7b80\u5386\u5361\u7247',
  click_toolbar_send_resume: '\u53d1\u9001\u7b80\u5386',
  sync_application_status_from_conversations: '\u540c\u6b65\u5e94\u8058\u72b6\u6001',
  upsert_hr_conversation: '\u5199\u5165\u4f1a\u8bdd\u8bb0\u5f55',
  search_locate_conversation: '\u641c\u7d22\u5b9a\u4f4d\u4f1a\u8bdd',
  send_chat_message: '\u53d1\u9001\u6d88\u606f',
  mark_reply_sent: '\u6807\u8bb0\u5df2\u53d1\u9001',
  invalidate_stale_reply: '\u4f5c\u5e9f\u9648\u65e7\u56de\u590d',
}

const INTENT_LABELS: Record<string, string> = {
  interview_invite: '\u7ea6\u9762\u8bd5',
  offer: '\u53d1 offer',
  rejection: '\u5a49\u62d2',
  resume_request: '\u7d22\u8981\u7b80\u5386',
  general: '\u4e00\u822c\u6c9f\u901a',
  general_inquiry: '\u4e00\u822c\u8be2\u95ee',
  general_notice: '\u4e00\u822c\u901a\u77e5',
  unknown: '\u672a\u8bc6\u522b',
}

const STAGE_LABELS: Record<string, string> = {
  new: '\u65b0',
  active: '\u6c9f\u901a\u4e2d',
  resume_sent: '\u5df2\u53d1\u7b80\u5386',
  interview: '\u9762\u8bd5',
  offer: 'offer',
  closed: '\u5df2\u5173\u95ed',
}

const APPLY_FAIL_LABELS: Record<string, string> = {
  button_not_found: '\u672a\u627e\u5230\u6295\u9012\u6309\u94ae',
  dialog_blocked: '\u70b9\u51fb\u540e\u672a\u786e\u8ba4\uff08\u9a8c\u8bc1\u7801/\u98ce\u63a7/\u8df3\u8f6c\uff1f\uff09',
  error: '\u6280\u672f\u5f02\u5e38',
}

export const SKIP_REASON_LABELS: Record<string, string> = {
  score_below: '\u8bc4\u5206\u672a\u8fbe\u6807',
  llm_error: 'LLM \u8c03\u7528\u5931\u8d25',
}

function statusSuffix(status: string): string {
  switch (status) {
    case 'running':
      return ' \u2026'
    case 'done':
      return ' \u5b8c\u6210'
    case 'error':
      return ' \u5931\u8d25'
    case 'skipped':
      return ' \u8df3\u8fc7'
    case 'blocked':
      return ' \u53d7\u963b'
    case 'stopping':
      return ' \u505c\u6b62\u4e2d'
    default:
      return ''
  }
}

export function interpretEvent(ev: ProgressEvent): string {
  const d = (ev.detail ?? {}) as Record<string, unknown>
  const num = (v: unknown): number | undefined => (typeof v === 'number' ? v : undefined)
  const str = (v: unknown): string => (typeof v === 'string' ? v : '')

  // \u4e1a\u52a1\u4e8b\u4ef6\uff1astep \u540d\u5373\u4e8b\u4ef6\u540d\uff0cdetail \u5e26\u53ef\u8bfb\u7684\u6599
  switch (ev.step) {
    case 'start':
      return '\u5f00\u59cb\u8fd0\u884c'
    case 'done':
      return '\u8fd0\u884c\u7ed3\u675f'
    case 'stop':
      return ev.message || '\u5df2\u8bf7\u6c42\u505c\u6b62'
    case 'job_scored': {
      const score = num(d.score)
      const above = d.above_threshold
      const reason = str(d.reason)
      const tag = above === false ? '\uff08\u672a\u8fbe\u6807\uff09' : above === true ? '\uff08\u8fbe\u6807\uff09' : ''
      return `\u8bc4\u5206 ${score ?? '?'}${tag}${reason ? ` \u00b7 ${reason}` : ''}`
    }
    case 'job_skipped': {
      const reason = str(d.reason)
      const label = SKIP_REASON_LABELS[reason] ?? reason
      const score = num(d.score)
      const prior = str(d.prior_status)
      return `\u8df3\u8fc7\uff1a${label}${prior ? `\uff08${prior}\uff09` : ''}${score != null ? `\uff08\u8bc4\u5206 ${score}\uff09` : ''}`
    }
    case 'job_applied':
      return d.db_ok === false ? '\u5df2\u6295\u9012\uff08\u843d\u5e93\u5931\u8d25\uff09' : '\u5df2\u6295\u9012'
    case 'job_apply_failed': {
      const reason = str(d.result)
      const label = APPLY_FAIL_LABELS[reason] ?? reason
      return `\u6295\u9012\u5931\u8d25\uff1a${label}`
    }
    case 'w1_rate_limited': {
      const msg = str(d.message)
      // base: triggered Boss daily greeting cap, run stopped
      const base = '\u89e6\u53d1 Boss \u6bcf\u65e5\u6c9f\u901a\u4e0a\u9650\uff0c\u5df2\u505c\u6b62\u672c\u8f6e\u6295\u9012'
      return msg ? `${base}\uff08${msg}\uff09` : base
    }
    case 'w1_quota_warning': {
      const msg = str(d.message)
      // base: nearing Boss daily greeting cap
      const base = '\u63a5\u8fd1 Boss \u6bcf\u65e5\u6c9f\u901a\u4e0a\u9650'
      return msg ? `${base}\uff08${msg}\uff09` : base
    }
    case 'db_write_failed':
      return `\u843d\u5e93\u5931\u8d25\uff1a${str(d.error)}`
    case 'intent_analyzed': {
      const intent = str(d.intent)
      return `HR \u610f\u56fe\uff1a${INTENT_LABELS[intent] ?? intent}`
    }
    case 'llm_degraded':
      return '\u610f\u56fe\u5206\u6790\u5931\u8d25\uff0c\u672a\u5199\u5165\u7ed3\u679c\uff08\u4e0b\u8f6e\u91cd\u8bd5\uff09'
    case 'resume_sent':
      return '\u5df2\u53d1\u9001\u7b80\u5386'
    case 'conv_navigate_failed': {
      const method = str(d.method)
      const m =
        method === 'js_click'
          ? '\u6eda\u52a8\u641c\u7d22\u672a\u547d\u4e2d\uff08\u53ef\u80fd\u6c89\u5e95\uff09'
          : method === 'direct_url'
            ? '\u76f4\u5f00\u5931\u8d25'
            : method
      return `\u4f1a\u8bdd\u5b9a\u4f4d\u5931\u8d25${m ? `\uff1a${m}` : ''}\uff08\u5df2\u622a\u56fe\uff09`
    }
    case 'conv_timeout_closed':
      return '\u4f1a\u8bdd\u8d85\u65f6\uff0c\u81ea\u52a8\u5173\u95ed'
    case 'job_no_response_rejected':
      return '\u957f\u671f\u65e0\u56de\u5e94\uff0c\u81ea\u52a8\u5173\u95ed'
    case 'job_purged':
      return '30\u5929\u65e0\u8fdb\u5c55\uff0c\u5df2\u6e05\u7406\u6570\u636e\uff08\u5c97\u4f4d\u53ef\u91cd\u65b0\u8d70\u6d41\u7a0b\uff09'
    case 'stage_advanced': {
      const o = STAGE_LABELS[str(d.old_stage)] ?? str(d.old_stage)
      const n = STAGE_LABELS[str(d.new_stage)] ?? str(d.new_stage)
      return `\u9636\u6bb5\u63a8\u8fdb\uff1a${o} \u2192 ${n}`
    }
  }

  // \u5de5\u5177\u7ea7\u4e8b\u4ef6
  if (ev.tool) {
    return `${TOOL_LABELS[ev.tool] ?? ev.tool}${statusSuffix(ev.status)}`
  }
  // \u6b65\u9aa4\u7ea7\u4e8b\u4ef6
  return `${STEP_LABELS[ev.step] ?? ev.step}${statusSuffix(ev.status)}`
}
