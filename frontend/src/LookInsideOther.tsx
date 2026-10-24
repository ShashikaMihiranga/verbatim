import type { Job, LookInsideOtherResult } from './jobsApi'
import type { ReportThemeSummary } from './reportApi'
import LookInsideOtherCharts from './LookInsideOtherCharts'
import LookInsideOtherRibbons from './LookInsideOtherRibbons'

// Stage 3 of the "Look inside Other" feature (docs/TODO.md, 2026-10-21, ribbons rebuilt 2026-10-23 -
// mockup: Other-Flow*.dc.html in the separate verbatim-visual-system project). The mockup's own ribbon
// diagram draws one precise path per known/new theme, sized and positioned from a FIXED demo dataset
// baked into its canvas-preview-only script - not something this component can honestly reproduce while
// a real job is running: the backend only reports coarse step names while it works (app/api_themes.py's
// `look_inside_other` route), not a live per-theme split - the real split (`job.result`) is only known
// once the job reaches "done". So `LookInsideOtherRibbons` draws real ribbons (one per known theme, sized
// by that theme's REAL CURRENT share from `allThemes`) with a flowing-dash animation that is a pure
// activity indicator, not a live-updating copy of the mockup's own per-theme reveal; the exact, real
// Known/New/Still-in-Other breakdown is what the "done" state shows, built from `job.result` - the one
// place in this component real numbers appear.

// Must match the job's step labels in app/api_themes.py look_inside_other (renamed 2026-10-24 to describe
// the real work - docs/REPORT_UI_REWORK.md). 'Done' is the finished state, not a server step.
const STEPS = ['Finding patterns in Other', 'Naming new themes', 'Matching answers to themes', 'Updating the report', 'Done']

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
  allThemes,
}: {
  job: Job | null
  onStart: () => void
  // Real current theme shares (`report.all_themes`), used only to size the ribbon diagram's destination
  // widths while a job runs. Optional: a caller with no themes handy still renders a perfectly good
  // running state, just with the ribbons omitted (same optionality pattern used elsewhere in this app).
  allThemes?: ReportThemeSummary[]
}) {
  const isRunning = job !== null && job.status === 'running'
  // This component only ever receives a "look_inside_other" job (Report.tsx's own call site) - the
  // `'known_added' in` check narrows `Job['result']`'s union down to `LookInsideOtherResult` for
  // TypeScript, since the two job kinds' results share no discriminant field of their own.
  const result: LookInsideOtherResult | null =
    job !== null && job.result !== null && 'known_added' in job.result ? job.result : null
  const isDone = job !== null && job.status === 'done' && result !== null
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
          {allThemes && allThemes.length > 0 && (
            <div className="lio-ribbons">
              <LookInsideOtherRibbons allThemes={allThemes} />
            </div>
          )}
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

      {isDone && result && result.failed_classification_count > 0 && (
        <div className="lio-failed" role="alert">
          <p className="err">
            {result.failed_classification_count} answer{result.failed_classification_count === 1 ? '' : 's'} could
            not be classified (a Jev request failed) and stayed in Other. If this number is large, check that
            TYPESAFE_API_KEY is valid, then use "Look inside again."
          </p>
        </div>
      )}

      {isDone && result && (
        <div className="lio-results">
          <ResultColumn
            title="Known themes"
            note="Answers that now match a theme already in the chart"
            accentVar="--t1"
            count={result.known_added}
            unit="answers"
            rows={[]}
          />
          <ResultColumn
            title="New themes found"
            note="Patterns no known theme covered"
            accentVar="--accent"
            count={result.new_themes.reduce((sum, t) => sum + t.count, 0)}
            unit="answers"
            rows={result.new_themes.map((t) => ({ label: t.label, count: t.count }))}
          />
          <ResultColumn
            title="Still in Other"
            note="Varied answers that don't repeat enough to group"
            accentVar="--other"
            count={result.still_other_count}
            unit="answers"
            rows={[]}
          />
        </div>
      )}

      {isDone && result && result.charts && <LookInsideOtherCharts charts={result.charts} />}
    </div>
  )
}
