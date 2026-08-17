import { useCallback, useEffect, useRef } from 'react'

export interface ProgressEvent {
  workflow: string
  step: string
  // tool: present on tool-level events; absent/null on step-level events.
  // scope: which loop instance (job_id for W1, conv_id/company for W2; {} run-level).
  tool?: string | null
  status: string
  message: string
  scope?: Record<string, unknown> | null
  detail?: Record<string, unknown> | null
  ts?: number
  // seq: agent 内层循环的轮次序号。非 null = 这是一条 agent 步事件（m1/m2 专有）。
  seq?: number | null
  // duration_ms: 这一步花了多久。只有终态的 step/tool 事件有；agent 步没有
  // 「耗时」这个概念，是 null 而不是 0（0 会被渲染成"花了 0 毫秒"）。
  duration_ms?: number | null
  // error: 失败原因。终态事件才有；成功时是 null。
  error?: string | null
}

export function useWorkflowStream(onEvent: (event: ProgressEvent) => void) {
  const esRef = useRef<EventSource | null>(null)
  const retryRef = useRef<number | null>(null)
  const onEventRef = useRef(onEvent)

  onEventRef.current = onEvent

  const clearRetry = useCallback(() => {
    if (retryRef.current !== null) {
      window.clearTimeout(retryRef.current)
      retryRef.current = null
    }
  }, [])

  const connect = useCallback(() => {
    if (esRef.current) {
      return
    }

    const es = new EventSource('/api/workflow/stream')

    es.addEventListener('message', (event) => {
      try {
        onEventRef.current(JSON.parse(event.data) as ProgressEvent)
      } catch {
        // Ignore malformed SSE payloads from transient backend states.
      }
    })

    es.onerror = () => {
      es.close()
      esRef.current = null
      clearRetry()
      retryRef.current = window.setTimeout(connect, 2000)
    }

    esRef.current = es
  }, [clearRetry])

  useEffect(() => {
    connect()

    return () => {
      clearRetry()
      esRef.current?.close()
      esRef.current = null
    }
  }, [clearRetry, connect])
}
