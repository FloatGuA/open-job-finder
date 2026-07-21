import { useSyncExternalStore } from 'react'

// Global on/off switch for the DevLabel component-name overlays. Module-level
// store (no Provider needed) backed by localStorage so the choice persists across
// reloads. Default ON. Toggle from the Topbar; every <DevLabel> re-renders via
// useSyncExternalStore. Set ON=current behaviour so existing labels stay visible.
const KEY = 'ojf_dev_labels'

let enabled = typeof localStorage !== 'undefined' ? localStorage.getItem(KEY) !== '0' : true
let listeners: Array<() => void> = []

export function toggleDevLabels(): void {
  enabled = !enabled
  localStorage.setItem(KEY, enabled ? '1' : '0')
  listeners.forEach((l) => l())
}

function subscribe(cb: () => void): () => void {
  listeners.push(cb)
  return () => {
    listeners = listeners.filter((l) => l !== cb)
  }
}

export function useDevLabels(): boolean {
  return useSyncExternalStore(subscribe, () => enabled, () => enabled)
}
