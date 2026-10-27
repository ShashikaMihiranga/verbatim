// The four steps every file goes through, shown on each of their pages (Uploads_UIHandoff.md: one stepper,
// the same everywhere): earlier steps get a green tick, the current one is filled. On a phone it collapses
// to "Step 2 of 4: Check columns".
const STEPS = ['Upload', 'Check columns', 'Cleaning review', 'Report']

export default function FlowSteps({ current }: { current: 1 | 2 | 3 | 4 }) {
  return (
    <div className="steps" aria-label={`Step ${current} of 4: ${STEPS[current - 1]}`}>
      <span className="steps-compact" aria-hidden="true">Step {current} of 4: {STEPS[current - 1]}</span>
      {STEPS.map((t, i) => {
        const n = i + 1
        const state = n < current ? 'done' : n === current ? 'on' : ''
        return (
          <span key={t} className={state} aria-hidden="true">
            <b>
              {state === 'done' ? (
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3.2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l5 5 9-10" /></svg>
              ) : n}
            </b>
            {t}
          </span>
        )
      })}
    </div>
  )
}
