import { useEffect, useMemo, useState } from 'react'
import { Briefcase, Clock, FileText, GripVertical, LayoutDashboard, MessageSquare, Network, ScrollText, Settings } from 'lucide-react'
import { API } from '@/api'
import { useAppContext, type Page } from '@/context/app-context'
import { APP_VERSION } from '@/version'
import DevLabel from '@/components/dev/DevLabel'

const NAV_ORDER_KEY = 'ojf_nav_order'

const ITEMS: Array<{ page: Page; title: string; icon: typeof LayoutDashboard }> = [
  { page: 'dashboard', title: '\u63a7\u5236\u53f0', icon: LayoutDashboard },
  { page: 'jobs', title: '\u804c\u4f4d', icon: Briefcase },
  { page: 'chat', title: '\u4f1a\u8bdd', icon: MessageSquare },
  { page: 'logs', title: '\u65e5\u5fd7', icon: ScrollText },
  { page: 'automation', title: '\u81ea\u52a8\u5316\u548c\u6d4b\u8bd5', icon: Clock },
  { page: 'resume', title: '\u7b80\u5386', icon: FileText },
  { page: 'lifecycle', title: '\u67b6\u6784', icon: Network },
  { page: 'settings', title: '\u8bbe\u7f6e', icon: Settings },
]

const ALL_PAGES = ITEMS.map((i) => i.page)

// localStorage \u662f\u7528\u6237\u6570\u636e\u8fb9\u754c\uff0c\u89e3\u6790\u5931\u8d25\u56de\u9000\u9ed8\u8ba4\u987a\u5e8f\uff1b\u65b0\u589e/\u5220\u9664\u7684 navigator \u81ea\u52a8\u8865\u4f4d/\u5254\u9664
function loadNavOrder(): Page[] {
  try {
    const saved = JSON.parse(localStorage.getItem(NAV_ORDER_KEY) ?? '[]') as Page[]
    const valid = saved.filter((p) => ALL_PAGES.includes(p))
    const missing = ALL_PAGES.filter((p) => !valid.includes(p))
    return [...valid, ...missing]
  } catch {
    return ALL_PAGES
  }
}

function saveNavOrder(order: Page[]) {
  localStorage.setItem(NAV_ORDER_KEY, JSON.stringify(order))
}

export default function Sidebar() {
  const { page, setPage, workflowRunning, isPaused } = useAppContext()
  const [pendingCount, setPendingCount] = useState(0)
  const [order, setOrder] = useState<Page[]>(loadNavOrder)
  const [dragPage, setDragPage] = useState<Page | null>(null)
  const [overPage, setOverPage] = useState<Page | null>(null)

  const orderedItems = useMemo(() => order.map((p) => ITEMS.find((i) => i.page === p)!), [order])

  function handleDrop(target: Page) {
    if (dragPage && dragPage !== target) {
      const from = order.indexOf(dragPage)
      const to = order.indexOf(target)
      const next = order.filter((p) => p !== dragPage)
      const insertAt = from < to ? next.indexOf(target) + 1 : next.indexOf(target)
      next.splice(insertAt, 0, dragPage)
      setOrder(next)
      saveNavOrder(next)
    }
    setDragPage(null)
    setOverPage(null)
  }

  useEffect(() => {
    const load = () =>
      API.getPendingReplies()
        .then((r) => setPendingCount(r.length))
        .catch(() => {})
    void load()
    const id = window.setInterval(load, 15_000)
    return () => window.clearInterval(id)
  }, [])

  const agentState = useMemo(() => {
    if (workflowRunning) {
      return { dotCls: 'bg-signal-green', label: `\u8fd0\u884c\u4e2d\uff1a${workflowRunning}` }
    }
    if (isPaused) {
      return { dotCls: 'bg-signal-amber', label: '\u5df2\u6682\u505c' }
    }
    return { dotCls: 'bg-text-3', label: '\u7a7a\u95f2' }
  }, [isPaused, workflowRunning])

  return (
    <aside
      className="relative z-10 flex w-60 shrink-0 flex-col border-r border-border-subtle"
      style={{ background: 'linear-gradient(180deg,#161618 0%,#000 100%)' }}
    >
      {/* Brand */}
      <div className="px-5 pb-5 pt-6">
        <div className="flex items-center gap-2.5">
          <span
            className="relative h-6 w-6 shrink-0 rounded-[7px]"
            style={{
              background: 'linear-gradient(135deg,#0a84ff,#40c8e0)',
              boxShadow: '0 0 20px rgba(10,132,255,0.4)',
            }}
          >
            <span className="absolute inset-[6px] rounded-[2px]" style={{ border: '1.5px solid rgba(0,0,0,0.85)' }} />
          </span>
          <span className="text-[18px] font-semibold text-white" style={{ letterSpacing: '-0.374px' }}>
            OpenJobFinder
          </span>
        </div>
        <div className="mt-1.5 flex items-center gap-1.5 text-[13px] text-text-3">
          <span>AI {'\u6c42\u804c\u52a9\u624b'}</span>
          <span className="font-mono text-deco">v{APP_VERSION}</span>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3">
        <p className="mb-2 flex items-center gap-2 px-3 text-[11px] font-semibold tracking-[0.16em] text-text-3 select-none">
          NAVIGATOR
          <DevLabel name="Sidebar" />
        </p>
        <div className="space-y-0.5">
          {orderedItems.map((item) => {
            const Icon = item.icon
            const active = item.page === page
            const showBadge = item.page === 'chat' && pendingCount > 0
            const isDragging = dragPage === item.page
            const isOver = overPage === item.page && dragPage !== null && dragPage !== item.page

            return (
              <button
                key={item.page}
                type="button"
                draggable
                onClick={() => setPage(item.page)}
                onDragStart={() => setDragPage(item.page)}
                onDragOver={(e) => {
                  e.preventDefault()
                  setOverPage(item.page)
                }}
                onDragEnd={() => {
                  setDragPage(null)
                  setOverPage(null)
                }}
                onDrop={() => handleDrop(item.page)}
                className={`group relative flex w-full cursor-grab items-center gap-3 rounded-[10px] px-3 py-2.5 text-left text-[16px] transition active:cursor-grabbing ${
                  active ? 'text-[#cfe2ff]' : 'text-text-2 hover:bg-bg-card hover:text-text-1'
                } ${isDragging ? 'opacity-40' : ''} ${isOver ? 'ring-1 ring-inset ring-signal-blue/60' : ''}`}
                style={
                  active
                    ? { background: 'linear-gradient(90deg,rgba(10,132,255,0.16),rgba(10,132,255,0.03))', letterSpacing: '-0.224px' }
                    : { letterSpacing: '-0.224px' }
                }
              >
                {active && (
                  <span
                    className="absolute left-0 top-2.5 bottom-2.5 w-[2.5px] rounded-full bg-signal-blue"
                    style={{ boxShadow: '0 0 9px #0a84ff' }}
                  />
                )}
                <Icon className="h-[18px] w-[18px] shrink-0 opacity-85" />
                <span>{item.title}</span>
                {showBadge && (
                  <span
                    className="ml-auto rounded-full px-2 py-px font-mono text-[12.5px] font-semibold"
                    style={{ background: 'rgba(255,159,10,0.18)', color: '#ff9f0a' }}
                  >
                    {pendingCount}
                  </span>
                )}
                <GripVertical
                  className={`h-[15px] w-[15px] shrink-0 opacity-0 transition group-hover:opacity-30 ${showBadge ? '' : 'ml-auto'}`}
                />
              </button>
            )
          })}
        </div>
      </nav>

      {/* Agent status */}
      <div className="border-t border-border-subtle px-5 py-4">
        <div className="flex items-center gap-2.5 text-[13.5px] text-text-3">
          <span className={`h-2 w-2 shrink-0 rounded-full ${agentState.dotCls} ${workflowRunning ? 'animate-pulse' : ''}`} />
          <span className="truncate">{agentState.label}</span>
        </div>
      </div>
    </aside>
  )
}
