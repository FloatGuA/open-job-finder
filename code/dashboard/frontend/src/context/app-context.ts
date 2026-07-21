import { createContext, useContext } from 'react'
import type { ProgressEvent } from '@/hooks/useWorkflowStream'

export type Page = 'dashboard' | 'jobs' | 'chat' | 'logs' | 'automation' | 'resume' | 'lifecycle' | 'settings'

export interface AppContextValue {
  page: Page
  setPage: (page: Page) => void
  workflowRunning: string | null
  setWorkflowRunning: (value: string | null) => void
  progressEvents: ProgressEvent[]
  isPaused: boolean
  refreshControlStatus: () => Promise<void>
}

export const AppContext = createContext<AppContextValue>({} as AppContextValue)

export function useAppContext() {
  return useContext(AppContext)
}
