import type { ReactNode } from 'react'

/**
 * Standard card surface (rounded-2xl + bg-card + shadow). The most-repeated
 * container pattern across the app, lifted into a primitive (frontend doctrine
 * layer 5). pad: 'sm'=p-5, 'md'=p-6, 'none'= caller supplies padding.
 */
export function Card({
  className = '',
  pad = 'md',
  children,
}: {
  className?: string
  pad?: 'sm' | 'md' | 'none'
  children: ReactNode
}) {
  const p = pad === 'sm' ? 'p-5' : pad === 'md' ? 'p-6' : ''
  return <div className={`rounded-2xl bg-bg-card shadow-card ${p} ${className}`.trim()}>{children}</div>
}
