import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-brand text-white hover:bg-brand-hover',
  secondary: 'bg-bg-card2 text-text-1 hover:bg-bg-hover',
  danger: 'bg-rose-500/15 text-rose-400 hover:bg-rose-500/25',
  ghost: 'text-text-3 hover:text-text-1',
}

/**
 * Button primitive with the app's standard variants. Consolidates the many
 * inline button styles. Pass-through props (onClick, disabled, type...) win over
 * defaults; className/style are applied last so callers can extend.
 */
export function Button({
  variant = 'secondary',
  className = '',
  children,
  ...rest
}: { variant?: Variant } & ButtonHTMLAttributes<HTMLButtonElement> & { children: ReactNode }) {
  return (
    <button
      type="button"
      {...rest}
      className={`rounded-lg px-4 py-2 text-sm transition disabled:cursor-not-allowed disabled:opacity-40 ${VARIANTS[variant]} ${className}`.trim()}
      style={{ letterSpacing: '-0.224px', ...(rest.style ?? {}) }}
    >
      {children}
    </button>
  )
}
