import { startTransition, useEffect, useState } from 'react'
import { API } from '@/api'
import { useAppContext } from '@/context/app-context'
import DevLabel from '@/components/dev/DevLabel'
import { useDevLabels, toggleDevLabels } from '@/hooks/useDevLabels'

const PAGE_TITLES = {
  dashboard: '\u63a7\u5236\u53f0',
  jobs: '\u804c\u4f4d',
  chat: '\u4f1a\u8bdd',
  logs: '\u65e5\u5fd7',
  automation: '\u81ea\u52a8\u5316',
  resume: '\u7b80\u5386',
  lifecycle: '\u67b6\u6784',
  interview: '\u9762\u8bd5\u51c6\u5907',
  crosssite: '\u8de8\u7ad9\u70b9\u6295\u9012',
  personalinfo: '\u4e2a\u4eba\u4fe1\u606f',
  settings: '\u8bbe\u7f6e',
} as const

export default function Topbar() {
  const { page, refreshControlStatus } = useAppContext()
  const [pending, setPending] = useState<'pause' | 'resume' | null>(null)
  const [restarting, setRestarting] = useState(false)
  const [online, setOnline] = useState(true)
  const devLabels = useDevLabels()

  useEffect(() => {
    const check = async () => {
      try {
        await fetch('/api/workflow/status')
        setOnline(true)
      } catch {
        setOnline(false)
      }
    }
    void check()
    const id = window.setInterval(() => void check(), 10_000)
    return () => window.clearInterval(id)
  }, [])

  const runAction = async (action: 'pause' | 'resume') => {
    setPending(action)
    try {
      if (action === 'pause') {
        await API.pause()
      } else {
        await API.resume()
      }
      startTransition(() => {
        void refreshControlStatus()
      })
    } finally {
      setPending(null)
    }
  }

  const restartBackend = async () => {
    setRestarting(true)
    try {
      await API.restartBackend()
      // Give uvicorn ~2 s to reload, then hard-refresh so the browser reconnects.
      setTimeout(() => window.location.reload(), 2000)
    } catch {
      setRestarting(false)
    }
  }

  return (
    <header
      className="flex h-12 items-center justify-between px-6"
      style={{
        background: 'rgba(0, 0, 0, 0.8)',
        backdropFilter: 'saturate(180%) blur(20px)',
        WebkitBackdropFilter: 'saturate(180%) blur(20px)',
        borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}
    >
      <span className="flex items-center gap-2">
        <h1
          className="text-sm font-semibold text-white"
          style={{ letterSpacing: '-0.374px' }}
        >
          {PAGE_TITLES[page]}
        </h1>
        <DevLabel name="Topbar" />
      </span>

      <div className="flex items-center gap-2">
        {/* Server connection indicator */}
        <span
          className="flex items-center gap-1.5 text-xs"
          style={{ color: online ? '#34d399' : '#f87171' }}
          title={online ? '\u670d\u52a1\u5668\u5728\u7ebf' : '\u670d\u52a1\u5668\u79bb\u7ebf\uff0c\u8bf7\u91cd\u542f\u540e\u7aef'}
        >
          <span
            className="h-1.5 w-1.5 rounded-full"
            style={{ background: online ? '#34d399' : '#f87171' }}
          />
          {online ? '\u5728\u7ebf' : '\u79bb\u7ebf'}
        </span>
        {/* Component-name label overlay toggle (dev aid) */}
        <button
          type="button"
          onClick={toggleDevLabels}
          className={`rounded-lg px-3 py-1.5 text-xs transition ${
            devLabels
              ? 'bg-signal-blue/15 text-signal-bright'
              : 'bg-bg-card2 text-text-3 hover:bg-bg-hover hover:text-text-1'
          }`}
          style={{ letterSpacing: '-0.174px' }}
          title={'\u663e\u793a/\u9690\u85cf\u7ec4\u4ef6\u540d\u6807\u7b7e\uff08\u8c03\u8bd5\u8f85\u52a9\uff09'}
        >
          {devLabels ? '\u6807\u7b7e ON' : '\u6807\u7b7e OFF'}
        </button>
        {/* Restart utilities */}
        <button
          type="button"
          onClick={() => window.location.reload()}
          className="rounded-lg bg-bg-card2 px-3 py-1.5 text-xs text-text-3 transition hover:bg-bg-hover hover:text-text-1"
          style={{ letterSpacing: '-0.174px' }}
          title={'\u5f3a\u5236\u5237\u65b0\u6d4f\u89c8\u5668\u9875\u9762'}
        >
          {'\u91cd\u542f\u524d\u7aef'}
        </button>
        <button
          type="button"
          onClick={() => void restartBackend()}
          disabled={restarting}
          className="rounded-lg bg-bg-card2 px-3 py-1.5 text-xs text-text-3 transition hover:bg-bg-hover hover:text-text-1 disabled:cursor-not-allowed disabled:opacity-50"
          style={{ letterSpacing: '-0.174px' }}
          title={'\u89e6\u53d1 uvicorn --reload \u70ed\u91cd\u542f\uff0c\u7ea6 2 \u79d2\u540e\u81ea\u52a8\u5237\u65b0'}
        >
          {restarting ? '\u91cd\u542f\u4e2d\u2026' : '\u91cd\u542f\u540e\u7aef'}
        </button>

        {/* Divider */}
        <div style={{ width: 1, height: 18, background: 'rgba(255,255,255,0.1)', margin: '0 2px' }} />

        {/* Pause / Resume */}
        <button
          type="button"
          onClick={() => void runAction('pause')}
          disabled={pending !== null}
          className="rounded-lg bg-bg-card2 px-3.5 py-1.5 text-sm text-text-1 transition hover:bg-bg-hover disabled:cursor-not-allowed disabled:opacity-50"
          style={{ letterSpacing: '-0.224px' }}
        >
          {pending === 'pause' ? '\u6682\u505c\u4e2d\u2026' : 'Pause'}
        </button>
        <button
          type="button"
          onClick={() => void runAction('resume')}
          disabled={pending !== null}
          className="rounded-lg bg-brand px-3.5 py-1.5 text-sm text-white transition hover:bg-brand-hover disabled:cursor-not-allowed disabled:opacity-50"
          style={{ letterSpacing: '-0.224px' }}
        >
          {pending === 'resume' ? '\u6062\u590d\u4e2d\u2026' : 'Resume'}
        </button>
      </div>
    </header>
  )
}
