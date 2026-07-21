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
