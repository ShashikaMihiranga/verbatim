import type { Job } from './jobsApi'

// Stage 3 of the "Look inside Other" feature (docs/TODO.md, 2026-10-21 - mockup: Other-Flow*.dc.html in
// the separate verbatim-visual-system project). The mockup's own ribbon diagram draws one precise path per
// known/new theme, sized and positioned from a FIXED demo dataset baked into its canvas-preview-only script
// - not something this component can honestly reproduce while a real job is running: the backend only
// reports coarse step names while it works (app/api_themes.py's `look_inside_other` route), not a live
// per-theme split - the real split (`job.result`) is only known once the job reaches "done". So the
// "running" state here is a genuine, animated "real work is happening" indicator (dashed flow + pulsing
// step dots, same class of signal as JobProgress.tsx's own spinner), not a live-updating copy of the
// mockup's per-theme ribbons; the exact, real Known/New/Still-in-Other breakdown is what the "done" state
// shows, built from `job.result` - the one place in this component real numbers appear.

const STEPS = ['Checking known themes', 'Grouping new themes into sub-themes', 'Finalizing', 'Done']

function stepIndex(job: Job): number {
  if (job.status === 'done') return STEPS.length - 1
  const i = STEPS.indexOf(job.step)
  return i === -1 ? 0 : i
}

function ResultColumn({
  title, note, accentVar, count, unit, rows,
}: {
  title: string
  note: string
  accentVar: string
  count: number
  unit: string
  rows: Array<{ label: string; count: number }>
}) {
  const total = rows.reduce((sum, r) => sum + r.count, 0) || 1
  return (
    <div className="lio-col">
      <div className="lio-col-head" style={{ borderTopColor: `var(${accentVar})` }}>
        <div className="lio-col-title">{title}</div>
        <div className="lio-col-note">{note}</div>
        <div className="lio-col-n">
          {count} <span>{unit}</span>
        </div>
      </div>
      {rows.length > 0 && (
        <div className="lio-col-rows">
          {rows.map((r) => (
            <div className="lio-row" key={r.label}>
              <span className="lio-row-name">{r.label}</span>
              <span className="lio-row-bar-wrap">
                <span
                  className="lio-row-bar"
                  style={{ width: `${(r.count / total) * 100}%`, background: `var(${accentVar})` }}
                />
              </span>
              <span className="lio-row-n">{r.count}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default function LookInsideOther({
  job,
  onStart,
}: {
  job: Job | null
  onStart: () => void
}) {
  const isRunning = job !== null && job.status === 'running'
  const isDone = job !== null && job.status === 'done' && job.result !== null
  const isFailed = job !== null && job.status === 'failed'

  return (
    <div className="lio">
      <div className="lio-head">
        <div className="lio-title">Inside Other</div>
        {!isRunning && (
          <button type="button" className="lio-cta" onClick={onStart} disabled={isRunning}>
            {isDone ? 'Look inside again' : 'Look inside'}
            <svg width="16" height="12" viewBox="0 0 18 14" aria-hidden="true">
              <path
                d="M1 7H15M10 2L16 7L10 12"
                style={{ fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round', strokeLinejoin: 'round' }}
              />
            </svg>
          </button>
        )}
      </div>

      {isFailed && (
        <div className="lio-failed">
          <p className="err" role="alert">{job!.error}</p>
        </div>
      )}

      {isRunning && job && (
        <div className="lio-running">
          <div className="lio-status">
            <span className="lio-live-dot" aria-hidden="true" />
            <span>{job.step}</span>
          </div>
          <div className="lio-flow" aria-hidden="true">
            <div className="lio-flow-track">
              <div className="lio-flow-dash" />
            </div>
          </div>
          <div className="lio-steps">
            {STEPS.map((label, i) => {
              const idx = stepIndex(job)
              const state = i < idx ? 'done' : i === idx ? 'active' : 'pending'
              return (
                <div className="lio-step" key={label} data-state={state}>
                  <span className="lio-step-dot" />
                  <span className="lio-step-label">{label}</span>
                  {i < STEPS.length - 1 && <span className="lio-step-bar" data-filled={i < idx} />}
                </div>
              )
            })}
          </div>
        </div>
      )}

      {isDone && job?.result && (
        <div className="lio-results">
          <ResultColumn
            title="Known themes"
            note="Answers that now match a theme already in the chart"
            accentVar="--t1"
            count={job.result.known_added}
            unit="answers"
            rows={[]}
          />
          <ResultColumn
            title="New themes found"
            note="Patterns no known theme covered"
            accentVar="--accent"
            count={job.result.new_themes.reduce((sum, t) => sum + t.count, 0)}
            unit="answers"
            rows={job.result.new_themes.map((t) => ({ label: t.label, count: t.count }))}
          />
          <ResultColumn
            title="Still in Other"
            note="Varied answers that don't repeat enough to group"
            accentVar="--other"
            count={job.result.still_other_count}
            unit="answers"
            rows={[]}
          />
        </div>
      )}
    </div>
  )
}
