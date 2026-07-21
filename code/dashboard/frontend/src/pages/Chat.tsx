import { useCallback, useEffect, useRef, useState } from 'react'
import { API, type Conversation, type ConversationMessage } from '@/api'
import { INTENT_COLORS, INTENT_LABELS } from '@/utils/intentMeta'
import { useAppContext } from '@/context/app-context'
import DevLabel from '@/components/dev/DevLabel'

// Sentinel filter values: not real stages \u2014 filter by reply_status client-side.
// \u5f85\u5ba1\u6279 = pending (needs your review); \u5f85\u53d1\u9001 = approved/revision (queued to send).
const PENDING_FILTER = '__pending__'
const SEND_FILTER = '__send__'
// \u5f85\u52a0\u5fae\u4fe1: client-side filter by wechat_pending (HR sent their WeChat, not dismissed).
const WECHAT_FILTER = '__wechat__'
// \u8d85\u65f6\u65e0\u56de\u5e94: stage=closed but NOT an explicit rejection (a 14-day stall soft-marker),
// i.e. the conversation went quiet rather than being turned down. Client-side.
const STALE_FILTER = '__stale__'

const STAGE_TABS: Array<{ label: string; value: string | undefined }> = [
  { label: '\u5168\u90e8', value: undefined },
  { label: '\u5f85\u5ba1\u6279', value: PENDING_FILTER },
  { label: '\u5f85\u53d1\u9001', value: SEND_FILTER },
  { label: '\u5f85\u52a0\u5fae\u4fe1', value: WECHAT_FILTER },
  { label: '\u8d85\u65f6\u65e0\u56de\u5e94', value: STALE_FILTER },
  { label: '\u4e00\u822c', value: 'general' },
  { label: '\u5df2\u53d1\u7b80\u5386', value: 'resume_sent' },
  { label: '\u9762\u8bd5', value: 'interview' },
  { label: '\u5df2\u5173\u95ed', value: 'closed' },
]

// stage \u2192 tinted badge (signal palette)
function stageMeta(stage: string): { label: string; color: string } | null {
  switch (stage) {
    case 'interview':
      return { label: '\u9762\u8bd5', color: '#ff9f0a' }
    case 'resume_sent':
      return { label: '\u5df2\u53d1\u7b80\u5386', color: '#30d158' }
    case 'closed':
      return { label: '\u5df2\u5173\u95ed', color: '#84848c' }
    default:
      return null
  }
}

function TintBadge({ label, color }: { label: string; color: string }) {
  return (
    <span
      className="rounded-md px-1.5 py-0.5 text-[11px] font-medium"
      style={{ background: `${color}28`, color }}
    >
      {label}
    </span>
  )
}

// \u8ddd\u4e0a\u6b21\u6c9f\u901a\u5929\u6570\uff1a\u7528 last_msg_at\uff08\u6700\u540e\u4e00\u6761\u5df2\u8bb0\u5f55\u6d88\u606f\u7684\u5165\u5e93\u65f6\u95f4\uff09\u3002
function daysSinceContact(iso?: string): number | null {
  if (!iso) return null
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return null
  return Math.max(0, Math.floor((Date.now() - t) / 86400000))
}

// \u641c\u7d22\u5339\u914d\uff1a\u516c\u53f8\u540d / HR \u540d / HR \u5934\u8854 / \u6700\u540e\u6d88\u606f\u9884\u89c8 / \u6bcf\u6761\u6d88\u606f\u6b63\u6587\uff08\u5168\u6587\uff09\u3002
// \u7eaf\u5ba2\u6237\u7aef\u5b50\u4e32\u5339\u914d\uff08\u5df2\u52a0\u8f7d\u7684\u4f1a\u8bdd\uff09\uff0c\u4e0d\u533a\u5206\u5927\u5c0f\u5199\u3002q \u5df2 trim+lowercase\u3002
function convMatchesQuery(conv: Conversation, q: string): boolean {
  if (!q) return true
  if ((conv.company ?? '').toLowerCase().includes(q)) return true
  if ((conv.hr_name ?? '').toLowerCase().includes(q)) return true
  if ((conv.hr_title ?? '').toLowerCase().includes(q)) return true
  if ((conv.last_msg_preview ?? '').toLowerCase().includes(q)) return true
  return (conv.messages ?? []).some((m) => m.text.toLowerCase().includes(q))
}

// WeChat cards: HR messages captured by read_messages as `[card] ...`.
//  - request card: "<want to exchange WeChat>" -> W2 auto-agrees.
//  - number card:  "<name>'s WeChat: <id>"     -> HR's id, sent right after we agree.
// We render both as distinct green cards (not stray text bubbles) and drive a strong
// "go add on WeChat" banner that surfaces the actual id once it arrives.
const WECHAT_CARD_SUBSTR = '\u6211\u60f3\u8981\u548c\u60a8\u4ea4\u6362\u5fae\u4fe1'
const WECHAT_NUMBER_MARKER = '\u5fae\u4fe1\u53f7'
const WECHAT_CARD_PREFIX = '[\u5361\u7247]'
const WECHAT_ID_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{4,29}$/
function isWechatCard(msg: ConversationMessage): boolean {
  return msg.sender === 'hr'
    && msg.text.startsWith(WECHAT_CARD_PREFIX)
    && (msg.text.includes(WECHAT_CARD_SUBSTR) || msg.text.includes(WECHAT_NUMBER_MARKER))
}

// Pull HR's WeChat id out of the "[\u5361\u7247] <name>\u7684\u5fae\u4fe1\u53f7\n<id>" card; null if none/invalid.
// Only the actual card counts, and the token must look like an id/phone -- a sentence
// merely mentioning \u5fae\u4fe1\u53f7 (e.g. an HR decline) is not one.
function wechatIdFrom(messages: ConversationMessage[]): string | null {
  for (const m of messages) {
    if (m.sender !== 'hr' || !m.text.startsWith(WECHAT_CARD_PREFIX) || !m.text.includes(WECHAT_NUMBER_MARKER)) continue
    const after = (m.text.split(WECHAT_NUMBER_MARKER).pop() ?? '').trim()
    const id = after.split(/\s+/)[0] ?? ''
    if (WECHAT_ID_RE.test(id)) return id
  }
  return null
}

function MessageBubble({ msg }: { msg: ConversationMessage }) {
  // WeChat-exchange request card: centered green card notice, not an HR chat bubble.
  if (isWechatCard(msg)) {
    const text = msg.text.replace(/^\[[^\]]+\]\s*/, '')
    return (
      <div className="flex justify-center py-0.5">
        <span
          className="max-w-[85%] rounded-xl px-3 py-1.5 text-[12px] font-medium"
          style={{ background: 'rgba(48,209,88,0.14)', color: '#30d158', border: '1px solid rgba(48,209,88,0.3)' }}
        >
          {'[\u5fae\u4fe1] '}{text}
        </span>
      </div>
    )
  }
  // System notices (resume-request / attachment card / "\u9644\u4ef6\u7b80\u5386\u8bf7\u6c42\u5df2\u53d1\u9001") are not
  // chat from either side \u2014 render them as a centered muted line, not an HR bubble.
  if (msg.sender === 'system') {
    const text = msg.text.replace(/^\[[^\]]+\]\s*/, '')
    return (
      <div className="flex justify-center py-0.5">
        <span className="max-w-[80%] truncate rounded-full bg-white/[0.04] px-3 py-1 text-[11px] text-text-3" title={msg.text}>
          {text}
        </span>
      </div>
    )
  }
  const isMe = msg.sender === 'me'
  return (
    <div className={`flex ${isMe ? 'justify-end' : 'justify-start'}`}>
      <div className={isMe ? 'ml-auto' : 'mr-auto'}>
        <div
          className={`max-w-[75%] break-words px-4 py-2.5 text-sm ${
            isMe
              ? 'rounded-2xl rounded-tr-sm text-white'
              : 'rounded-2xl rounded-tl-sm bg-bg-card2 text-text-1'
          }`}
          style={isMe ? { letterSpacing: '-0.224px', background: '#0a84ff' } : { letterSpacing: '-0.224px' }}
        >
          {msg.text}
        </div>
        <p
          className={`mt-1 font-mono text-[11px] text-text-3 ${isMe ? 'text-right' : 'text-left'}`}
        >
          {msg.time}
        </p>
      </div>
    </div>
  )
}

function isReplyApprovalVisible(conv: Conversation | null): boolean {
  return !!conv && (
    conv.reply_status === 'pending' ||
    conv.reply_status === 'revision' ||
    conv.reply_status === 'approved'
  )
}

function isQueuedForSend(conv: Conversation): boolean {
  return conv.reply_status === 'approved' || conv.reply_status === 'revision'
}

export default function Chat() {
  const { workflowRunning } = useAppContext()
  const [activeStage, setActiveStage] = useState<string | undefined>(undefined)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [showUnanswered, setShowUnanswered] = useState(false)
  const [editingReply, setEditingReply] = useState(false)
  const [draftText, setDraftText] = useState('')
  const [bulkConfirm, setBulkConfirm] = useState(false)
  const [bulkBusy, setBulkBusy] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const loadConversations = useCallback(() => {
    setLoading(true)
    setError(null)
    // \u5f85\u5ba1\u6279/\u5f85\u53d1\u9001 are reply_status filters, not stages: fetch all then filter client-side.
    const clientFilter = activeStage === SEND_FILTER || activeStage === PENDING_FILTER
      || activeStage === WECHAT_FILTER || activeStage === STALE_FILTER
    API.getConversations(clientFilter ? undefined : activeStage)
      .then((d) => {
        let convs = d.conversations
        if (activeStage === SEND_FILTER) {
          convs = convs.filter((c) => c.reply_status === 'approved' || c.reply_status === 'revision')
        } else if (activeStage === PENDING_FILTER) {
          convs = convs.filter((c) => c.reply_status === 'pending')
        } else if (activeStage === WECHAT_FILTER) {
          convs = convs.filter((c) => c.wechat_pending)
        } else if (activeStage === STALE_FILTER) {
          // Stalled (soft-closed by timeout), not an explicit HR rejection.
          convs = convs.filter((c) => c.stage === 'closed' && c.intent !== 'rejection')
        }
        // \u540e\u7aef\u6309 created_at DESC\uff08\u4f1a\u8bdd\u9996\u6b21\u5165\u5e93\u65f6\u95f4\uff09\u8fd4\u56de\uff0c\u4f1a\u628a\u300c\u6709\u65b0\u6d88\u606f\u7684\u8001\u4f1a\u8bdd\u300d\u57cb\u5728\u4e0b\u9762\u3002
        // \u524d\u7aef\u6309 last_msg_at\uff08\u6700\u540e\u4e00\u6761\u6d88\u606f\u65f6\u95f4\uff09\u964d\u5e8f\u91cd\u6392\uff0c\u8ba9\u6700\u8fd1\u6709\u52a8\u9759\u7684\u4f1a\u8bdd\u6d6e\u5230\u9876\u90e8\u3002
        convs = [...convs].sort((a, b) => {
          const ta = a.last_msg_at ? new Date(a.last_msg_at).getTime() : 0
          const tb = b.last_msg_at ? new Date(b.last_msg_at).getTime() : 0
          return tb - ta
        })
        setConversations(convs)
        setSelectedId((prev) => {
          const ids = convs.map((c) => c.conv_id)
          if (prev && ids.includes(prev)) return prev
          return convs[0]?.conv_id ?? null
        })
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false))
  }, [activeStage])

  useEffect(() => {
    loadConversations()
  }, [loadConversations])

  useEffect(() => {
    setBulkConfirm(false)
  }, [activeStage])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [selectedId, conversations])

  useEffect(() => {
    setEditingReply(false)
    setDraftText('')
  }, [selectedId])

  const selected = conversations.find((c) => c.conv_id === selectedId) ?? null
  const messages = selected?.messages ?? []
  const wechatId = wechatIdFrom(messages)

  // \u641c\u7d22\u662f\u53e0\u52a0\u5728\u5f53\u524d tab \u8fc7\u6ee4\u4e4b\u4e0a\u7684\u5ba2\u6237\u7aef\u5b50\u4e32\u8fc7\u6ee4\uff1b\u7a7a\u67e5\u8be2\u65f6\u5c55\u793a\u5168\u90e8\u3002
  const searchNeedle = searchQuery.trim().toLowerCase()

  // Conversations with zero messages are almost all W1 stubs: every successful
  // apply pre-creates a conversation row (conv_id = job_id) so that when the HR
  // eventually replies, W2 updates THAT row instead of creating a parallel one.
  // Until they reply there is no conversation to speak of, so showing them here
  // just dilutes the threads that do have messages. Hidden by default, counted
  // and toggleable \u2014 the information is not lost, it belongs on the jobs page.
  const unanswered = conversations.filter((c) => (c.messages?.length ?? 0) === 0)
  const base = showUnanswered
    ? conversations
    : conversations.filter((c) => (c.messages?.length ?? 0) > 0)
  const displayed = searchNeedle
    ? base.filter((c) => convMatchesQuery(c, searchNeedle))
    : base

  const updateConversation = (convId: string, updater: (conv: Conversation) => Conversation) => {
    setConversations((prev) => prev.map((conv) => (
      conv.conv_id === convId ? updater(conv) : conv
    )))
  }

  const handleApprove = async () => {
    if (!selected) return
    updateConversation(selected.conv_id, (conv) => ({ ...conv, reply_status: 'approved' }))
    try {
      await API.approveReply(selected.conv_id)
    } catch (e) {
      setError((e as Error).message)
      void loadConversations()
    }
  }

  const handleDismissAllPending = async () => {
    setBulkBusy(true)
    setBulkConfirm(false)
    // Optimistic (mirror single-dismiss): drop all pending from the list now, roll
    // back to the snapshot if the request fails so a failure is visible, not silent.
    const snapshot = conversations
    setConversations((prev) => prev.filter((c) => c.reply_status !== 'pending'))
    try {
      await API.dismissAllPendingReplies()
      loadConversations()
    } catch (e) {
      setError((e as Error).message)
      setConversations(snapshot)
    } finally {
      setBulkBusy(false)
    }
  }

  const handleStartEdit = () => {
    if (!selected) return
    setEditingReply(true)
    setDraftText(selected.reply_status === 'revision' && selected.reply_draft
      ? selected.reply_draft
      : (selected.suggested_reply ?? ''))
  }

  const handleSaveRevision = async () => {
    if (!selected) return
    const draft = draftText.trim()
    if (!draft) return
    updateConversation(selected.conv_id, (conv) => ({
      ...conv,
      reply_status: 'revision',
      reply_draft: draft,
    }))
    setEditingReply(false)
    try {
      await API.reviseReply(selected.conv_id, draft)
    } catch (e) {
      setError((e as Error).message)
      void loadConversations()
    }
  }

  const handleDismiss = async () => {
    if (!selected) return
    updateConversation(selected.conv_id, (conv) => ({ ...conv, reply_status: 'dismissed' }))
    try {
      await API.dismissReply(selected.conv_id)
    } catch (e) {
      setError((e as Error).message)
      void loadConversations()
    }
  }

  const handleReject = async () => {
    if (!selected) return
    if (!window.confirm('\u786e\u5b9a\u62d2\u7edd\u8be5\u5c97\u4f4d\uff1f\u4f1a\u8bdd\u5c06\u5173\u95ed\u3001\u4e0d\u518d\u8d77\u8349\u56de\u590d\u3002')) return
    const convId = selected.conv_id
    setConversations((prev) => prev.filter((c) => c.conv_id !== convId))
    setSelectedId(null)
    try {
      await API.rejectConversation(convId)
    } catch (e) {
      setError((e as Error).message)
      void loadConversations()
    }
  }

  const handleDismissWechat = async () => {
    if (!selected) return
    const convId = selected.conv_id
    // Optimistic: clear the reminder locally (banner hides; drops out of \u5f85\u52a0\u5fae\u4fe1 filter).
    updateConversation(convId, (conv) => ({ ...conv, wechat_dismissed: true, wechat_pending: false }))
    if (activeStage === WECHAT_FILTER) {
      setConversations((prev) => prev.filter((c) => c.conv_id !== convId))
    }
    try {
      await API.dismissWechat(convId)
    } catch (e) {
      setError((e as Error).message)
      void loadConversations()
    }
  }

  const handleCancel = async () => {
    if (!selected) return
    updateConversation(selected.conv_id, (conv) => ({ ...conv, reply_status: 'pending' }))
    try {
      await API.cancelReply(selected.conv_id)
    } catch (e) {
      setError((e as Error).message)
      void loadConversations()
    }
  }

  const handleMarkSent = async () => {
    if (!selected) return
    updateConversation(selected.conv_id, (conv) => ({
      ...conv,
      reply_status: 'sent',
      suggested_reply: '',
      reply_draft: '',
    }))
    try {
      await API.markSent(selected.conv_id)
    } catch (e) {
      setError((e as Error).message)
      void loadConversations()
    }
  }

  const queuedCount = conversations.filter(isQueuedForSend).length

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {queuedCount > 0 && (
        <div
          className="mb-2 flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm"
          style={{ background: 'rgba(255,159,10,0.12)', border: '1px solid rgba(255,159,10,0.3)' }}
        >
          <span style={{ color: '#ff9f0a' }}>{'\u23f3'}</span>
          <DevLabel name="QueuedBar" />
          <span style={{ color: 'rgba(255,255,255,0.75)' }}>
            {'\u6709 '}<span className="font-mono" style={{ color: '#ff9f0a' }}>{queuedCount}</span>{' \u6761\u5df2\u6279\u51c6\u56de\u590d\u5f85\u53d1\u9001\uff0c\u9700\u624b\u52a8\u89e6\u53d1 W3 \u53d1\u9001\u3002'}
          </span>
        </div>
      )}
      <div className="relative flex flex-1 overflow-hidden rounded-2xl bg-bg-card shadow-card">
        <div className="pointer-events-none absolute inset-0 z-10 rounded-2xl" style={{ border: '1px solid rgba(255,255,255,0.08)' }} />
        {/* Left: conversation list */}
        <div className="flex w-96 shrink-0 flex-col" style={{ borderRight: '1px solid rgba(255,255,255,0.06)' }}>
          {/* Stage tabs */}
          <div className="flex flex-wrap items-center gap-1.5 px-3 py-2.5" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <p className="flex w-full items-center gap-2 text-[10px] font-medium tracking-widest text-text-3 uppercase select-none">
              CONVERSATIONS
              <DevLabel name="ConversationList" />
            </p>
            {STAGE_TABS.map((tab) => {
              const active = tab.value === activeStage
              return (
                <button
                  key={tab.label}
                  type="button"
                  onClick={() => setActiveStage(tab.value)}
                  className={
                    active
                      ? 'rounded-full bg-signal-blue px-2.5 py-1 text-xs font-medium text-white'
                      : 'rounded-full bg-bg-card2 px-2.5 py-1 text-xs font-medium text-text-2 transition hover:bg-bg-hover hover:text-text-1'
                  }
                >
                  {tab.label}
                </button>
              )
            })}
          </div>

          {/* Search box: client-side substring filter over company / HR / preview / message text */}
          <div className="px-3 py-2" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
            <div className="relative">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder={'\u641c\u7d22\u516c\u53f8 / HR / \u6d88\u606f\u5185\u5bb9\u2026'}
                className="w-full rounded-lg bg-bg-card2 px-3 py-1.5 pr-7 text-xs text-text-1 placeholder:text-text-3 focus:outline-none"
                style={{ border: '1px solid rgba(255,255,255,0.08)' }}
              />
              {searchQuery && (
                <button
                  type="button"
                  onClick={() => setSearchQuery('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-text-3 transition hover:text-text-1"
                  title={'\u6e05\u7a7a\u641c\u7d22'}
                >
                  {'\u2715'}
                </button>
              )}
            </div>
            <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1">
              {searchNeedle && (
                <p className="text-[10px] text-text-3">
                  {'\u5339\u914d '}<span className="font-mono text-text-2">{displayed.length}</span>{' / '}{base.length}{' \u6761'}
                </p>
              )}
              {unanswered.length > 0 && (
                <button
                  type="button"
                  onClick={() => setShowUnanswered((v) => !v)}
                  className="text-[10px] text-text-3 underline-offset-2 transition hover:text-text-2 hover:underline"
                  title={'\u5df2\u6295\u9012\u4f46 HR \u5c1a\u672a\u56de\u590d\u7684\u4f1a\u8bdd\uff1b\u5b83\u4eec\u5728\u804c\u4f4d\u9875\u6709\u5b8c\u6574\u6295\u9012\u8bb0\u5f55'}
                >
                  {showUnanswered ? '\u9690\u85cf' : '\u663e\u793a'}
                  {'\u672a\u56de\u5e94\u6295\u9012 '}
                  <span className="font-mono">{unanswered.length}</span>
                  {' \u6761'}
                </button>
              )}
            </div>
          </div>

          {activeStage === PENDING_FILTER && conversations.length > 0 && (
            <div className="px-3 py-2" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
              {bulkConfirm ? (
                <div className="rounded-lg p-2" style={{ background: 'rgba(255,69,58,0.1)', border: '1px solid rgba(255,69,58,0.3)' }}>
                  <p className="mb-2 text-[11px] leading-relaxed text-text-2">
                    {'\u786e\u8ba4\u62d2\u7edd\u5f53\u524d\u5168\u90e8 '}{conversations.length}{' \u6761\u5f85\u5ba1\u6279\u56de\u590d\uff1f\u6b64\u64cd\u4f5c\u4e0d\u53d1\u9001\u3001\u4ec5\u6e05\u7406\u540d\u5355\uff08\u5df2\u6279\u51c6\u7684\u4e0d\u53d7\u5f71\u54cd\uff09\u3002'}
                  </p>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={() => void handleDismissAllPending()}
                      disabled={bulkBusy}
                      className="rounded-lg px-3 py-1.5 text-xs font-medium disabled:opacity-50"
                      style={{ background: '#ff453a', color: '#fff' }}
                    >
                      {'\u786e\u8ba4\u62d2\u7edd'}
                    </button>
                    <button
                      type="button"
                      onClick={() => setBulkConfirm(false)}
                      className="rounded-lg px-3 py-1.5 text-xs font-medium text-text-2"
                      style={{ border: '1px solid rgba(255,255,255,0.15)' }}
                    >
                      {'\u53d6\u6d88'}
                    </button>
                  </div>
                </div>
              ) : (
                <button
                  type="button"
                  onClick={() => setBulkConfirm(true)}
                  className="w-full rounded-lg px-3 py-1.5 text-xs font-medium transition"
                  style={{ background: 'rgba(255,69,58,0.14)', color: '#ff453a', boxShadow: 'inset 0 0 0 1px rgba(255,69,58,0.3)' }}
                >
                  {'\u4e00\u952e\u62d2\u7edd\u5168\u90e8\uff08'}{conversations.length}{'\uff09'}
                </button>
              )}
            </div>
          )}

          {/* List */}
          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <p className="px-4 py-6 text-center text-sm text-text-3">{'\u52a0\u8f7d\u4e2d\u2026'}</p>
            ) : error ? (
              <p className="px-4 py-4 text-xs text-signal-red">{error}</p>
            ) : conversations.length === 0 ? (
              <p className="px-4 py-6 text-center text-sm text-text-3">{'\u6682\u65e0\u4f1a\u8bdd\u6570\u636e'}</p>
            ) : displayed.length === 0 ? (
              // Distinguish "nothing matched your search" from "everything here is
              // an unanswered application and they are hidden" \u2014 otherwise the tab
              // looks broken when all its rows happen to be stubs.
              searchNeedle ? (
                <p className="px-4 py-6 text-center text-sm text-text-3">{'\u65e0\u5339\u914d\u7684\u4f1a\u8bdd'}</p>
              ) : unanswered.length > 0 ? (
                <p className="px-4 py-6 text-center text-sm leading-relaxed text-text-3">
                  {'\u8fd9\u91cc\u7684 '}<span className="font-mono">{unanswered.length}</span>
                  {' \u6761\u5747\u4e3a\u5df2\u6295\u9012\u4f46 HR \u672a\u56de\u590d\uff0c\u5df2\u9690\u85cf'}
                </p>
              ) : (
                <p className="px-4 py-6 text-center text-sm text-text-3">{'\u6682\u65e0\u4f1a\u8bdd'}</p>
              )
            ) : (
              displayed.map((conv) => {
                const stage = stageMeta(conv.stage)
                const idle = daysSinceContact(conv.last_msg_at)
                const active = conv.conv_id === selectedId
                return (
                  <div
                    key={conv.conv_id}
                    role="button"
                    tabIndex={0}
                    onClick={() => setSelectedId(conv.conv_id)}
                    onKeyDown={(e) => e.key === 'Enter' && setSelectedId(conv.conv_id)}
                    className={`relative w-full cursor-pointer px-4 py-2.5 text-left transition ${active ? 'bg-signal-blue/[0.1]' : 'hover:bg-bg-hover'}`}
                    style={{ borderBottom: '1px solid rgba(255,255,255,0.04)' }}
                  >
                    {active && <span className="absolute left-0 top-0 bottom-0 w-0.5" style={{ background: '#0a84ff' }} />}
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm font-medium text-text-1" style={{ letterSpacing: '-0.224px' }}>
                        {conv.company}
                      </span>
                      <div className="flex shrink-0 items-center gap-1.5">
                        {stage && <TintBadge label={stage.label} color={stage.color} />}
                        {conv.intent && (
                          <TintBadge label={INTENT_LABELS[conv.intent] ?? conv.intent} color={INTENT_COLORS[conv.intent] ?? '#84848c'} />
                        )}
                      </div>
                    </div>
                    <div className="mt-0.5 flex items-center justify-between gap-2">
                      <span className="truncate text-xs text-text-2">{conv.hr_name}</span>
                      {idle != null && (
                        <span className={`shrink-0 text-[11px] ${idle > 7 ? 'text-signal-amber' : 'text-text-3'}`}>
                          {idle === 0 ? '\u4eca\u5929' : `${idle} \u5929\u524d`}
                        </span>
                      )}
                    </div>
                    <p className="mt-0.5 truncate text-xs text-text-3" style={{ letterSpacing: '-0.12px' }}>
                      {conv.last_msg_preview}
                    </p>
                    {conv.job_url && (
                      <div className="mt-2 flex gap-1.5" onClick={(e) => e.stopPropagation()}>
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); API.browseUrl(conv.job_url!) }}
                          className="rounded px-2 py-0.5 text-[10px] text-text-3 transition hover:text-text-1"
                          style={{ background: 'rgba(255,255,255,0.06)' }}
                        >
                          {'\u2197 \u5c97\u4f4d'}
                        </button>
                      </div>
                    )}
                  </div>
                )
              })
            )}
          </div>
        </div>

        {/* Right: message thread */}
        <div className="flex flex-1 flex-col overflow-hidden">
          {!selected ? (
            <div className="flex flex-1 items-center justify-center text-sm text-text-3">
              {'\u2190 \u9009\u62e9\u5de6\u4fa7\u4f1a\u8bdd\u67e5\u770b\u6d88\u606f'}
            </div>
          ) : (
            <>
              {/* Thread header */}
              <div className="flex items-center justify-between px-5 py-3.5" style={{ borderBottom: '1px solid rgba(255,255,255,0.06)' }}>
                <div className="flex items-center gap-3">
                  <p className="flex items-center gap-2 text-[10px] font-medium tracking-widest text-text-3 uppercase select-none">
                    MESSAGES
                    <DevLabel name="MessageThread" />
                  </p>
                  <div>
                    <span className="text-sm font-medium text-text-1" style={{ letterSpacing: '-0.374px' }}>
                      {selected.company}
                    </span>
                    <span className="mx-2 text-text-3">{'\u00b7'}</span>
                    <span className="text-sm text-text-2" style={{ letterSpacing: '-0.224px' }}>
                      {selected.hr_name}
                    </span>
                    {selected.hr_title && (
                      <>
                        <span className="mx-2 text-text-3">{'\u00b7'}</span>
                        <span className="text-sm text-text-3" style={{ letterSpacing: '-0.224px' }}>
                          {selected.hr_title}
                        </span>
                      </>
                    )}
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setError(null)
                      API.openInBrowser(selected.conv_id)
                        .then((r) => { if (!r?.ok) setError(r.error || r.reason || '\u672a\u80fd\u5728 Boss \u6253\u5f00\u8be5\u4f1a\u8bdd') })
                        .catch((e: Error) => setError(e.message))
                    }}
                    disabled={workflowRunning !== null}
                    className="rounded-lg px-2.5 py-1 text-xs text-signal-bright transition hover:bg-signal-blue/10 disabled:cursor-not-allowed disabled:opacity-40"
                    style={{ background: 'rgba(10,132,255,0.1)' }}
                    title={'\u5728\u81ea\u52a8\u6d4f\u89c8\u5668\u4e2d\u6253\u5f00\u8be5\u4f1a\u8bdd\u7684 Boss \u9875\u9762'}
                  >
                    {'\u2197 \u5728 Boss \u6253\u5f00'}
                  </button>
                  {selected.job_url && (
                    <button
                      type="button"
                      onClick={() => API.browseUrl(selected.job_url!).catch((e: Error) => setError(e.message))}
                      className="rounded-lg px-2.5 py-1 text-xs text-text-2 transition hover:text-text-1"
                      style={{ background: 'rgba(255,255,255,0.07)' }}
                      title={'\u5728\u6d4f\u89c8\u5668\u6253\u5f00\u5bf9\u5e94\u5c97\u4f4d\u9875'}
                    >
                      {'\u2197 \u5c97\u4f4d'}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => void handleReject()}
                    disabled={workflowRunning !== null}
                    className="rounded-lg px-2.5 py-1 text-xs transition disabled:cursor-not-allowed disabled:opacity-40"
                    style={{ background: 'rgba(255,69,58,0.1)', color: '#ff453a' }}
                    title={'\u62d2\u7edd\u8be5\u5c97\u4f4d\uff1a\u5173\u95ed\u4f1a\u8bdd\u3001\u4e0d\u518d\u8d77\u8349\u56de\u590d\uff08HR\u518d\u6765\u6d88\u606f\u4ecd\u4f1a\u91cd\u65b0\u5206\u6790\uff09'}
                  >
                    {'\u2715 \u62d2\u7edd\u5c97\u4f4d'}
                  </button>
                  <span className="font-mono text-xs text-text-3">
                    {selected.message_count ?? messages.length}{' \u6761\u6d88\u606f'}
                  </span>
                </div>
              </div>

              {messages.some(isWechatCard) && !selected.wechat_dismissed && (
                <div
                  className="mx-4 mb-1 mt-3 flex items-center gap-2 rounded-xl px-4 py-2.5 text-sm"
                  style={{ background: 'rgba(48,209,88,0.12)', border: '1px solid rgba(48,209,88,0.35)' }}
                >
                  <span style={{ color: '#30d158' }}>{'\u2705'}</span>
                  <DevLabel name="WechatReminder" />
                  <span style={{ color: 'rgba(255,255,255,0.82)' }}>
                    {(selected.wechat_id || wechatId) ? (
                      <>
                        {'HR \u5fae\u4fe1\u53f7\uff1a'}
                        <span className="font-mono font-semibold" style={{ color: '#30d158' }}>{selected.wechat_id || wechatId}</span>
                        {'\uff0c\u8bf7\u5c3d\u5feb\u6dfb\u52a0'}
                      </>
                    ) : 'HR \u8bf7\u6c42\u4ea4\u6362\u5fae\u4fe1\uff0c\u5df2\u81ea\u52a8\u540c\u610f\uff0c\u8bf7\u5c3d\u5feb\u5728 Boss \u6dfb\u52a0\u5bf9\u65b9\u5fae\u4fe1'}
                  </span>
                  <div className="ml-auto flex shrink-0 items-center gap-2">
                    <button
                      type="button"
                      onClick={() => {
                        setError(null)
                        API.openInBrowser(selected.conv_id)
                          .then((r) => { if (!r?.ok) setError(r.error || r.reason || '\u672a\u80fd\u5728 Boss \u6253\u5f00\u8be5\u4f1a\u8bdd') })
                          .catch((e: Error) => setError(e.message))
                      }}
                      disabled={workflowRunning !== null}
                      className="shrink-0 rounded-lg px-2.5 py-1 text-xs text-signal-bright transition hover:bg-signal-blue/10 disabled:cursor-not-allowed disabled:opacity-40"
                      style={{ background: 'rgba(10,132,255,0.1)' }}
                    >
                      {'\u2197 \u5728 Boss \u6253\u5f00'}
                    </button>
                    <button
                      type="button"
                      onClick={() => void handleDismissWechat()}
                      className="shrink-0 rounded-lg px-2.5 py-1 text-xs text-text-2 transition hover:text-text-1"
                      style={{ background: 'rgba(255,255,255,0.08)' }}
                    >
                      {'\u5df2\u6dfb\u52a0'}
                    </button>
                  </div>
                </div>
              )}

              {isReplyApprovalVisible(selected) && (
                <div className="mx-4 mb-3 mt-3 rounded-xl p-3" style={{ background: 'rgba(10,132,255,0.08)', border: '1px solid rgba(10,132,255,0.22)' }}>
                  <div className="mb-1.5 flex items-center justify-between">
                    <span className="flex items-center gap-2">
                      <p className="text-xs text-text-3">{'\u5efa\u8bae\u56de\u590d'}</p>
                      <DevLabel name="ReplyApproval" />
                    </span>
                    {selected.job_url && (
                      <button
                        type="button"
                        onClick={() => API.browseUrl(selected.job_url!)}
                        className="rounded-lg px-2.5 py-1 text-xs text-text-2 transition hover:text-text-1"
                        style={{ background: 'rgba(255,255,255,0.07)' }}
                        title={'\u5728\u6d4f\u89c8\u5668\u65b0\u6807\u7b7e\u9875\u6253\u5f00\u5c97\u4f4d'}
                      >
                        {'\u2197 \u5c97\u4f4d'}
                      </button>
                    )}
                  </div>
                  {workflowRunning !== null && (
                    <p className="mb-2 text-[11px] text-signal-amber">{'\u8fd0\u884c\u4e2d\uff0c\u5ba1\u6279\u64cd\u4f5c\u6682\u4e0d\u53ef\u7528\uff08\u907f\u514d\u4e0e\u5de5\u4f5c\u6d41\u5199\u5e93\u51b2\u7a81\uff09'}</p>
                  )}
                  <div className={workflowRunning !== null ? 'pointer-events-none select-none opacity-50' : ''}>
                  {editingReply ? (
                    <>
                      <textarea
                        value={draftText}
                        onChange={(e) => setDraftText(e.target.value)}
                        rows={4}
                        className="w-full rounded-xl px-3 py-2 text-sm text-white focus:outline-none"
                        style={{ background: 'rgba(0,0,0,0.35)', border: '1px solid rgba(10,132,255,0.3)' }}
                      />
                      <div className="mt-3 flex items-center gap-2">
                        <button type="button" onClick={() => void handleSaveRevision()} className="rounded-lg px-3 py-1 text-xs text-white" style={{ background: '#0a84ff' }}>
                          {'\u4fdd\u5b58\u4fee\u6539'}
                        </button>
                        <button type="button" onClick={() => setEditingReply(false)} className="rounded-lg bg-bg-card2 px-3 py-1 text-xs text-text-2">
                          {'\u53d6\u6d88'}
                        </button>
                      </div>
                    </>
                  ) : (
                    <>
                      <p className="text-sm text-text-1">
                        {selected?.reply_status === 'revision' ? selected.reply_draft : selected?.suggested_reply}
                      </p>
                      <div className="mt-2 flex items-center gap-2">
                        {selected?.reply_status === 'pending' ? (
                          <>
                            <button type="button" onClick={() => void handleApprove()} className="rounded-lg px-3 py-1 text-xs font-medium text-white" style={{ background: '#30a14e' }}>
                              {'\u6279\u51c6'}
                            </button>
                            <button type="button" onClick={handleStartEdit} className="rounded-lg px-3 py-1 text-xs font-medium text-white" style={{ background: '#0a84ff' }}>
                              {'\u4fee\u6539'}
                            </button>
                            <button type="button" onClick={() => void handleDismiss()} className="rounded-lg bg-bg-card2 px-3 py-1 text-xs text-text-2">
                              {'\u9a73\u56de'}
                            </button>
                          </>
                        ) : (
                          <>
                            <span className="rounded-lg px-3 py-1 text-xs" style={{ background: 'rgba(255,159,10,0.15)', color: '#ff9f0a' }}>
                              {'\u23f3 \u5f85\u53d1\u9001\uff08\u8fd0\u884c W2 \u540e\u53d1\u51fa\uff09'}
                            </span>
                            <button type="button" onClick={handleStartEdit} className="rounded-lg px-3 py-1 text-xs text-white" style={{ background: '#0a84ff' }}>
                              {'\u4fee\u6539'}
                            </button>
                            <button type="button" onClick={() => void handleCancel()} className="rounded-lg bg-bg-card2 px-3 py-1 text-xs text-text-2">
                              {'\u53d6\u6d88'}
                            </button>
                            <button type="button" onClick={() => void handleMarkSent()} className="rounded-lg px-3 py-1 text-xs text-text-3" style={{ background: 'rgba(255,255,255,0.05)' }}>
                              {'\u624b\u52a8\u6807\u8bb0\u53d1\u9001'}
                            </button>
                          </>
                        )}
                      </div>
                    </>
                  )}
                  </div>
                </div>
              )}

              {/* Messages */}
              <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
                {messages.length === 0 ? (
                  <p className="text-center text-sm text-text-3">{'\u6682\u65e0\u6d88\u606f\u8bb0\u5f55'}</p>
                ) : (
                  messages.map((msg, idx) => <MessageBubble key={idx} msg={msg} />)
                )}
                <div ref={messagesEndRef} />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}
