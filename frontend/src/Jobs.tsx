import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import type { JobListEntry, JobStatus } from './jobsApi'
import { listJobs } from './jobsApi'
import './report.css'
import './jobs.css'

// Jobs dashboard (docs/TODO.md, 2026-10-23): the one place to watch every background build across every
// dataset at once, instead of polling one dataset+column+kind at a time (which is all the per-screen
// `JobProgress`/`pollJob` pattern was ever built for - see that component's own comment). Polls
// `GET /api/jobs` on a plain interval rather than reusing `pollJob` (that helper stops itself once ONE
// job finishes; this page has many jobs in flight at once and keeps polling regardless of any single
// job's state).
const POLL_MS = 3000

const KIND_LABEL: Record<JobListEntry['kind'], string> = {
  themes: 'Build themes',
  report: 'Build report',
  look_inside_other: 'Look inside Other',
  split_theme: 'Split theme',
  theme_groups: 'Group themes',
}

const STATUS_TABS: Array<{ id: JobStatus | 'all'; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'running', label: 'Running' },
  { id: 'done', label: 'Done' },
  { id: 'failed', label: 'Failed' },
]

function relativeTime(iso: string | undefined, now: number): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const seconds = Math.max(0, Math.round((now - then) / 1000))
  if (seconds < 5) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.round(hours / 24)}d ago`
}

// Pure, props-driven (no fetching of its own - the jobs/filter/error come in as props) so this can be
// tested with `renderToStaticMarkup`, the same split `Projects.tsx`'s own `ProjectsList`/`Projects`
// already use for the identical reason (see that file's own comment on why the stateful wrapper has no
// test of its own).
export function JobsView({
  jobs, filter, onFilterChange, error, now,
}: {
  jobs: JobListEntry[] | null
  filter: JobStatus | 'all'
  onFilterChange: (next: JobStatus | 'all') => void
  error: string
  now: number
}) {
  return (
    <div className="jb">
      <div className="jb-title">Jobs</div>
      <div className="jb-summary">Every background build across your datasets, updated every few seconds.</div>

      <div className="rp-tabs" role="tablist">
        {STATUS_TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={filter === t.id}
            className={`rp-tab ${filter === t.id ? 'active' : ''}`}
            onClick={() => onFilterChange(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      {error && <p className="err">{error}</p>}

      {jobs === null && !error && <p className="muted">Loading...</p>}

      {jobs !== null && jobs.length === 0 && (
        <p className="muted">No {filter === 'all' ? '' : `${filter} `}jobs.</p>
      )}

      {jobs !== null && jobs.length > 0 && (
        <table className="jb-table">
          <thead>
            <tr>
              <th>Dataset</th>
              <th>Column</th>
              <th>Kind</th>
              <th>Status</th>
              <th>Step</th>
              <th>Started</th>
              <th>Updated</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.id}>
                <td className="jb-dataset" data-label="Dataset">
                  <Link to={`/report?dataset=${job.dataset_id}`}>{job.dataset_name}</Link>
                </td>
                <td className="jb-col" data-label="Column">{job.column}</td>
                <td data-label="Kind">{KIND_LABEL[job.kind]}</td>
                <td data-label="Status">
                  <span className={`jb-status jb-status-${job.status}`}>{job.status}</span>
                </td>
                <td className="jb-step" data-label="Step">
                  {job.status === 'failed' ? <span className="err">{job.error}</span> : job.step}
                </td>
                <td className="jb-time" data-label="Started">{relativeTime(job.created_at, now)}</td>
                <td className="jb-time" data-label="Updated">{relativeTime(job.updated_at, now)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}

export default function Jobs() {
  const [filter, setFilter] = useState<JobStatus | 'all'>('all')
  const [jobs, setJobs] = useState<JobListEntry[] | null>(null)
  const [error, setError] = useState('')
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    let cancelled = false
    async function tick() {
      try {
        const rows = await listJobs(filter === 'all' ? undefined : filter)
        if (!cancelled) {
          setJobs(rows)
          setError('')
        }
      } catch (e) {
        if (!cancelled) setError((e as Error).message)
      }
    }
    void tick()
    const id = setInterval(() => void tick(), POLL_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [filter])

  // A second, cheap ticker just for the "Xm ago" labels, independent of the network poll above - so
  // "just now" ages smoothly between actual refetches instead of only updating every POLL_MS.
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  return <JobsView jobs={jobs} filter={filter} onFilterChange={setFilter} error={error} now={now} />
}
