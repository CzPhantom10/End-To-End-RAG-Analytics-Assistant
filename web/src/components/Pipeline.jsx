import { useEffect, useState } from 'react'

/**
 * Shows the four real stages of the request while it is in flight.
 *
 * The backend answers in one round trip, so the timings here are indicative
 * rather than measured — the point is to make the architecture legible: the
 * model plans, pandas computes, and only then does the model write prose.
 */

const STAGES = [
  { key: 'retrieve', label: 'Retrieving context', after: 0 },
  { key: 'plan', label: 'Planning analysis', after: 700 },
  { key: 'compute', label: 'Computing with pandas', after: 2100 },
  { key: 'explain', label: 'Writing the answer', after: 3000 },
]

export default function Pipeline() {
  const [elapsed, setElapsed] = useState(0)

  useEffect(() => {
    const started = Date.now()
    const timer = setInterval(() => setElapsed(Date.now() - started), 120)
    return () => clearInterval(timer)
  }, [])

  const activeIndex = STAGES.reduce(
    (found, stage, index) => (elapsed >= stage.after ? index : found),
    0,
  )

  return (
    <div className="pipeline" role="status" aria-live="polite">
      {STAGES.map((stage, index) => (
        <div key={stage.key} style={{ display: 'contents' }}>
          {index > 0 && <span className="stage-link" />}
          <span
            className="stage"
            data-state={
              index < activeIndex ? 'done' : index === activeIndex ? 'active' : 'pending'
            }
          >
            <span className="stage-dot" />
            {stage.label}
          </span>
        </div>
      ))}
      <span style={{ flex: 1 }} />
      <span className="tiny muted" style={{ fontVariantNumeric: 'tabular-nums' }}>
        {(elapsed / 1000).toFixed(1)}s
      </span>
    </div>
  )
}
