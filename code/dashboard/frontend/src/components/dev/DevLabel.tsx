import { useDevLabels } from '@/hooks/useDevLabels'

// Component-name tag. Helps non-frontend users point at a specific UI region
// when giving feedback ("the InstanceDetail block does X").
//
//   <DevLabel name="X" />            inline pill — drop next to a block's header
//   <DevLabel name="X" float />      floating overlay top-right of a `relative`
//                                    parent (for blocks with no header text)
//
// Globally toggled via the Topbar switch (useDevLabels); renders nothing when off.
// pointer-events-none so it never intercepts clicks on the underlying controls.
export default function DevLabel({ name, float = false }: { name: string; float?: boolean }) {
  const show = useDevLabels()
  if (!show) return null
  const pill =
    'pointer-events-none rounded bg-signal-blue/25 px-1.5 py-0.5 font-mono text-[9.5px] font-semibold leading-none text-signal-bright'
  const border = { border: '1px solid rgba(10,132,255,0.4)' }
  if (float) {
    return (
      <span data-dev-label className={`absolute right-1 top-1 z-30 ${pill}`} style={border}>
        {name}
      </span>
    )
  }
  return (
    <span data-dev-label className={`inline-block align-middle ${pill}`} style={border}>
      {name}
    </span>
  )
}
