import type { Job } from './jobsApi'
import './themes.css'

// Pure, props-driven (no fetching of its own - the job comes in as a prop, updated by whatever is polling
// it), so this can be tested with `renderToStaticMarkup` the same way `frontend/src/Report.tsx`'s
// `ReportView` already is (see frontend/src/jobProgress.test.tsx).
//
// The spinner is a genuine "real work is happening" indicator, not a fake progress bar: it never claims a
// percentage or count, in keeping with CLAUDE.md's "no exact record counts" spirit extended to not
// inventing false precision about how much of the build is left either - `job.step` is the only concrete
// information shown, in plain English, exactly as the job itself reports it.
const KIND_VERB: Record<Job['kind'], string> = {
  themes: 'Finding themes in your answers',
  report: 'Building your report',
  look_inside_other: 'Looking inside Other',
}

export default function JobProgress({ job }: { job: Job }) {
  return (
    <div className="th-progress">
      <div className="jp-spinner" aria-hidden="true" />
      <div className="big">{KIND_VERB[job.kind]}...</div>
      <div className="jp-step">{job.step}</div>
      <div className="jp-note">This can take a minute or two. Please stay on this page.</div>
    </div>
  )
}
