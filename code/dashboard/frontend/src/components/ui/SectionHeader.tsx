import type { ReactNode } from 'react'

/**
 * Uppercase section label (OVERVIEW / SESSION / ...). Lifted from the repeated
 * `text-[10px] tracking-widest uppercase` pattern. `adapted` appends a small,
 * easily-removable\u300c\uff08\u5df2\u9002\u914d\u65b0\u524d\u7aef\uff09\u300dmarker used to track navigator-by-navigator
 * migration progress to the new frontend.
 */
export function SectionHeader({
  children,
  adapted = false,
}: {
  children: ReactNode
  adapted?: boolean
}) {
  return (
    <p className="mb-2 text-[10px] font-medium tracking-widest text-text-3 uppercase select-none">
      {children}
      {adapted && (
        <span className="ml-1.5 normal-case tracking-normal text-emerald-400/70">{'\uff08\u5df2\u9002\u914d\u65b0\u524d\u7aef\uff09'}</span>
      )}
    </p>
  )
}
