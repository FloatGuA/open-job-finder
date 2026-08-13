import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { API } from './api'
import { useWorkflowStream, type ProgressEvent } from './hooks/useWorkflowStream'
import Sidebar from './components/layout/Sidebar'
import Topbar from './components/layout/Topbar'
import Dashboard from './pages/Dashboard'
import Jobs from './pages/Jobs'
import Chat from './pages/Chat'
import Logs from './pages/Logs'
import Automation from './pages/Automation'
import Resume from './pages/Resume'
import StateMachine from './pages/StateMachine'
import InterviewPrep from './pages/InterviewPrep'
import CrossSiteApplications from './pages/CrossSiteApplications'
import PersonalInfo from './pages/PersonalInfo'
import Settings from './pages/Settings'
import { AppContext, type AppContextValue, type Page } from './context/app-context'

const PAGE_COMPONENTS: Record<Page, JSX.Element> = {
  dashboard: <Dashboard />,
  jobs: <Jobs />,
  chat: <Chat />,
  logs: <Logs />,
  automation: <Automation />,
  resume: <Resume />,
  lifecycle: <StateMachine />,
  interview: <InterviewPrep />,
  crosssite: <CrossSiteApplications />,
  personalinfo: <PersonalInfo />,
  settings: <Settings />,
}

const PAGE_STORAGE_KEY = 'ojf.page'

export default function App() {
  // Persist the active page so a refresh stays where you were instead of snapping
  // back to the dashboard. Validated against known pages so a stale/garbage value
  // can never render a blank shell.
  const [page, setPage] = useState<Page>(() => {
    const saved = typeof localStorage !== 'undefined' ? localStorage.getItem(PAGE_STORAGE_KEY) : null
    return saved && saved in PAGE_COMPONENTS ? (saved as Page) : 'dashboard'
  })
  useEffect(() => {
    try { localStorage.setItem(PAGE_STORAGE_KEY, page) } catch { /* storage unavailable — non-fatal */ }
  }, [page])
  const [workflowRunning, setWorkflowRunning] = useState<string | null>(null)
  const [progressEvents, setProgressEvents] = useState<ProgressEvent[]>([])
  const [isPaused, setIsPaused] = useState(false)
  const [captchaToast, setCaptchaToast] = useState<string | null>(null)

  const refreshWorkflowStatus = useCallback(async () => {
    const data = await API.getWorkflowStatus()
    setWorkflowRunning(data.running)
  }, [])

  const refreshControlStatus = useCallback(async () => {
    const data = await API.getControlStatus()
    setIsPaused(Boolean((data as { paused?: boolean }).paused))
  }, [])

  // SSE events can arrive in floods (debug mode emits a tool-level event per
  // registry.call). Writing state per-event re-renders the whole tree + LiveLog
  // thousands of times over a long run, ballooning the tab to multiple GB. So we
  // buffer events in a ref and flush to state at ~5 Hz; the cheap per-event
  // side-effects (captcha toast, status sync) stay immediate.
  const pendingEventsRef = useRef<ProgressEvent[]>([])

  useWorkflowStream((event) => {
    pendingEventsRef.current.push(event)

    if (event.status === 'blocked') {
      setCaptchaToast(event.message)
    } else if (captchaToast !== null && (event.status === 'running' || event.status === 'done' || event.status === 'error')) {
      setCaptchaToast(null)
    }

    if (event.step === 'done' || event.step === 'start') {
      void refreshWorkflowStatus().catch(() => {
        // Ignore transient sync failures; polling will reconcile shortly.
      })
    }
  })

  useEffect(() => {
    const id = window.setInterval(() => {
      if (pendingEventsRef.current.length === 0) return
      const batch = pendingEventsRef.current
      pendingEventsRef.current = []
      setProgressEvents((previous) => [...previous, ...batch].slice(-200))
    }, 200)
    return () => window.clearInterval(id)
  }, [])

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      void refreshWorkflowStatus().catch(() => {
        // Polling should be resilient to temporary backend unavailability.
      })
      void refreshControlStatus().catch(() => {
        // Polling should be resilient to temporary backend unavailability.
      })
    }, 10_000)

    return () => window.clearInterval(intervalId)
  }, [refreshControlStatus, refreshWorkflowStatus])

  useEffect(() => {
    void refreshWorkflowStatus().catch(() => {
      // Initial load should not block the shell layout.
    })
    void refreshControlStatus().catch(() => {
      // Initial load should not block the shell layout.
    })
  }, [refreshControlStatus, refreshWorkflowStatus])

  const contextValue = useMemo<AppContextValue>(
    () => ({
      page,
      setPage,
      workflowRunning,
      setWorkflowRunning,
      progressEvents,
      isPaused,
      refreshControlStatus,
    }),
    [isPaused, page, progressEvents, refreshControlStatus, workflowRunning],
  )

  return (
    <AppContext.Provider value={contextValue}>
      <div className="relative flex h-screen overflow-hidden bg-bg-page text-white">
        <div aria-hidden className="atmosphere pointer-events-none absolute inset-0 -z-10" />
        <Sidebar />
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <Topbar />
          <main className="flex-1 overflow-y-auto p-6">{PAGE_COMPONENTS[page]}</main>
        </div>
      </div>

      {captchaToast !== null && (
        <div
          className="fixed bottom-6 right-6 z-50 flex max-w-sm items-start gap-3 rounded-2xl px-5 py-4 shadow-card"
          style={{
            background: 'rgba(28,28,30,0.95)',
            border: '1px solid rgba(251,191,36,0.35)',
            backdropFilter: 'blur(20px)',
          }}
        >
          <span className="mt-0.5 text-base leading-none text-amber-400">{'\u26a0'}</span>
          <div className="flex-1">
            <p className="mb-1 text-sm font-semibold text-amber-400" style={{ letterSpacing: '-0.12px' }}>
              {'\u53cd\u722c\u9a8c\u8bc1'}
            </p>
            <p className="text-xs leading-relaxed text-text-2" style={{ letterSpacing: '-0.224px' }}>
              {captchaToast}
            </p>
          </div>
          <button
            type="button"
            onClick={() => setCaptchaToast(null)}
            className="ml-1 shrink-0 text-text-3 transition hover:text-text-1"
            aria-label={'\u5173\u95ed'}
          >
            {'\u2715'}
          </button>
        </div>
      )}
    </AppContext.Provider>
  )
}
