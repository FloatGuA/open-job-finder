// Coverage for the pure predicate/filter functions in Chat.tsx -- the layer that
// decides what a conversation looks like / which tab it belongs to. Two real bugs
// have already shipped from this exact layer (2026-07-28: tab list not updating
// live; 2026-08-09: bulk-reject-all button showing a stale count) because the raw
// fetched array and the live-filtered view can silently diverge. These functions
// are cheap to test in isolation (no API/DOM mocking needed) and are exactly where
// that class of bug lives, so they get tested directly rather than via handlers.
import { describe, expect, it } from 'vitest'
import type { Conversation, ConversationMessage } from '@/api'
import {
  PENDING_FILTER,
  SEND_FILTER,
  STALE_FILTER,
  WECHAT_CARD_PREFIX,
  WECHAT_CARD_SUBSTR,
  WECHAT_FILTER,
  WECHAT_NUMBER_MARKER,
  convMatchesQuery,
  daysSinceContact,
  isQueuedForSend,
  isReplyApprovalVisible,
  isWechatCard,
  matchesTabFilter,
  stageMeta,
} from './Chat'

function conv(overrides: Partial<Conversation> = {}): Conversation {
  return {
    conv_id: 'c1',
    hr_name: 'hr_zhang',
    company: 'TestCo',
    last_msg_preview: '',
    last_msg_from: 'hr',
    last_synced: '2026-08-01T00:00:00Z',
    stage: 'general',
    status: 'CHATTING',
    ...overrides,
  }
}

function msg(overrides: Partial<ConversationMessage> = {}): ConversationMessage {
  return { sender: 'hr', text: '', time: '09:00', ...overrides }
}

describe('stageMeta', () => {
  it('returns a colored badge for known stages', () => {
    expect(stageMeta('interview')).toMatchObject({ color: '#ff9f0a' })
    expect(stageMeta('resume_sent')).toMatchObject({ color: '#30d158' })
    expect(stageMeta('closed')).toMatchObject({ color: '#84848c' })
  })

  it('returns null for stages with no badge (e.g. general)', () => {
    expect(stageMeta('general')).toBeNull()
    expect(stageMeta('unknown_stage')).toBeNull()
  })
})

describe('daysSinceContact', () => {
  it('returns null when no timestamp is given', () => {
    expect(daysSinceContact(undefined)).toBeNull()
  })

  it('returns null for an unparsable timestamp', () => {
    expect(daysSinceContact('not-a-date')).toBeNull()
  })

  it('computes whole days elapsed', () => {
    const threeDaysAgo = new Date(Date.now() - 3 * 86400000 - 1000).toISOString()
    expect(daysSinceContact(threeDaysAgo)).toBe(3)
  })

  it('clamps a future timestamp to 0 rather than going negative', () => {
    const tomorrow = new Date(Date.now() + 86400000).toISOString()
    expect(daysSinceContact(tomorrow)).toBe(0)
  })
})

describe('convMatchesQuery', () => {
  it('matches everything when the query is empty', () => {
    expect(convMatchesQuery(conv(), '')).toBe(true)
  })

  it('matches by company, case-insensitively', () => {
    expect(convMatchesQuery(conv({ company: 'AcmeCorp' }), 'acme')).toBe(true)
  })

  it('matches by hr_name', () => {
    expect(convMatchesQuery(conv({ hr_name: 'zhang_hr' }), 'zhang')).toBe(true)
  })

  it('matches by hr_title', () => {
    expect(convMatchesQuery(conv({ hr_title: 'Recruiter' }), 'recruiter')).toBe(true)
  })

  it('matches by last_msg_preview', () => {
    expect(convMatchesQuery(conv({ last_msg_preview: 'see you tomorrow' }), 'tomorrow')).toBe(true)
  })

  it('matches by full message text, not just the preview', () => {
    const c = conv({ last_msg_preview: 'short', messages: [msg({ text: 'the full message body' })] })
    expect(convMatchesQuery(c, 'full message')).toBe(true)
  })

  it('returns false when nothing matches', () => {
    expect(convMatchesQuery(conv({ company: 'AcmeCorp' }), 'nomatch')).toBe(false)
  })
})

describe('isWechatCard', () => {
  it('is true for an HR wechat-exchange request card', () => {
    const m = msg({ sender: 'hr', text: `${WECHAT_CARD_PREFIX} ${WECHAT_CARD_SUBSTR}` })
    expect(isWechatCard(m)).toBe(true)
  })

  it('is true for an HR wechat-number card', () => {
    const m = msg({ sender: 'hr', text: `${WECHAT_CARD_PREFIX} ${WECHAT_NUMBER_MARKER}: abc123` })
    expect(isWechatCard(m)).toBe(true)
  })

  it('is false without the card prefix, even with matching content', () => {
    const m = msg({ sender: 'hr', text: WECHAT_CARD_SUBSTR })
    expect(isWechatCard(m)).toBe(false)
  })

  it('is false for a card-prefixed message from someone other than hr', () => {
    const m = msg({ sender: 'me', text: `${WECHAT_CARD_PREFIX} ${WECHAT_CARD_SUBSTR}` })
    expect(isWechatCard(m)).toBe(false)
  })

  it('is false for an unrelated card', () => {
    const m = msg({ sender: 'hr', text: `${WECHAT_CARD_PREFIX} resume attached` })
    expect(isWechatCard(m)).toBe(false)
  })
})

describe('isReplyApprovalVisible', () => {
  it('is false for null', () => {
    expect(isReplyApprovalVisible(null)).toBe(false)
  })

  it.each(['pending', 'revision', 'approved'] as const)('is true for reply_status=%s', (status) => {
    expect(isReplyApprovalVisible(conv({ reply_status: status }))).toBe(true)
  })

  it.each(['dismissed', 'sent', undefined] as const)('is false for reply_status=%s', (status) => {
    expect(isReplyApprovalVisible(conv({ reply_status: status }))).toBe(false)
  })
})

describe('isQueuedForSend', () => {
  it.each(['approved', 'revision'] as const)('is true for reply_status=%s', (status) => {
    expect(isQueuedForSend(conv({ reply_status: status }))).toBe(true)
  })

  it.each(['pending', 'dismissed', 'sent', undefined] as const)('is false for reply_status=%s', (status) => {
    expect(isQueuedForSend(conv({ reply_status: status }))).toBe(false)
  })
})

describe('matchesTabFilter', () => {
  it('matches everything under the "all" tab (activeStage=undefined)', () => {
    expect(matchesTabFilter(conv({ stage: 'anything' }), undefined)).toBe(true)
  })

  it(`${PENDING_FILTER}: only reply_status=pending`, () => {
    expect(matchesTabFilter(conv({ reply_status: 'pending' }), PENDING_FILTER)).toBe(true)
    expect(matchesTabFilter(conv({ reply_status: 'approved' }), PENDING_FILTER)).toBe(false)
  })

  it(`${SEND_FILTER}: queued text reply OR queued resume`, () => {
    expect(matchesTabFilter(conv({ reply_status: 'approved' }), SEND_FILTER)).toBe(true)
    expect(matchesTabFilter(conv({ resume_status: 'queued' }), SEND_FILTER)).toBe(true)
    expect(matchesTabFilter(conv({ reply_status: 'pending' }), SEND_FILTER)).toBe(false)
  })

  it(`${WECHAT_FILTER}: wechat_pending flag`, () => {
    expect(matchesTabFilter(conv({ wechat_pending: true }), WECHAT_FILTER)).toBe(true)
    expect(matchesTabFilter(conv({ wechat_pending: false }), WECHAT_FILTER)).toBe(false)
  })

  it(`${STALE_FILTER}: closed AND not an explicit rejection`, () => {
    expect(matchesTabFilter(conv({ stage: 'closed', intent: 'inquiry' }), STALE_FILTER)).toBe(true)
    expect(matchesTabFilter(conv({ stage: 'closed', intent: 'rejection' }), STALE_FILTER)).toBe(false)
    expect(matchesTabFilter(conv({ stage: 'general' }), STALE_FILTER)).toBe(false)
  })

  it('a real stage name matches conv.stage exactly', () => {
    expect(matchesTabFilter(conv({ stage: 'interview' }), 'interview')).toBe(true)
    expect(matchesTabFilter(conv({ stage: 'general' }), 'interview')).toBe(false)
  })
})
