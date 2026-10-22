import { authFetch } from './authFetch'

export type JobKind = 'themes' | 'report' | 'look_inside_other' | 'split_theme'
export type JobStatus = 'running' | 'done' | 'failed'

// "Look inside Other" (docs/TODO.md, 2026-10-21 Stage 3): the real Known/New/Still-in-Other counts the
// animated flow's own results panel needs - written by app/api_themes.py's own job route in the same
// commit as the Theme-row changes it summarizes, never reconstructed client-side from a second fetch.
export interface LookInsideOtherResult {
  known_added: number
  new_themes: Array<{ label: string; count: number }>
  still_other_count: number
}

// Theme editing (docs/TODO.md, fixed 2026-10-22): "split theme"'s own job result - the real pieces a
// theme split into, written the same way (app/api_themes.py's own `_apply_theme_split`).
export interface SplitThemeResult {
  new_themes: Array<{ label: string; count: number }>
  remainder_count: number
}

export interface Job {
  id: number
  dataset_id: number
  column: string
  kind: JobKind
  status: JobStatus
  step: string
  error: string | null
  // `null` for every job kind that has nothing to summarize (themes, report) - only "look_inside_other"
  // and "split_theme" ever populate this, once they reach "done".
  result: LookInsideOtherResult | SplitThemeResult | null
}

export interface BuildStarted {
  job_id: number
  status: 'running'
}

async function asError(r: Response): Promise<Error> {
  let msg = `Something went wrong (${r.status}).`
  try {
    const j = await r.json()
    if (typeof j.detail === 'string') msg = j.detail
  } catch {
    /* keep the default message */
  }
  return new Error(msg)
}

export async function getJob(datasetId: number, jobId: number): Promise<Job> {
  const r = await authFetch(`/api/datasets/${datasetId}/jobs/${jobId}`)
  if (!r.ok) throw await asError(r)
  return r.json()
}

// `null` (not a thrown error) when nothing has ever been built yet for this dataset+column+kind - the
// common "nothing to resume" case a page load needs to tell apart from a real error.
export async function getLatestJob(datasetId: number, column: string, kind: JobKind): Promise<Job | null> {
  const r = await authFetch(`/api/datasets/${datasetId}/jobs/latest?${new URLSearchParams({ column, kind })}`)
  if (r.status === 404) return null
  if (!r.ok) throw await asError(r)
  return r.json()
}

// Polls `GET .../jobs/{id}` every `intervalMs` (default 2s - frequent enough that the plain-English step
// feels live, infrequent enough not to hammer the server for a build that can take minutes) until the job
// reaches "done" or "failed", calling `onUpdate` with every observed body (including the first poll) so a
// caller can show the current step as soon as it is known. Returns a cleanup function that stops polling
// early (e.g. on unmount or when the user navigates away) - callers MUST call it, the same way any other
// effect cleanup here is expected to run.
export function pollJob(datasetId: number, jobId: number, onUpdate: (job: Job) => void, intervalMs = 2000): () => void {
  let stopped = false
  let timer: ReturnType<typeof setTimeout> | undefined

  async function tick() {
    if (stopped) return
    try {
      const job = await getJob(datasetId, jobId)
      if (stopped) return
      onUpdate(job)
      if (job.status === 'running') timer = setTimeout(tick, intervalMs)
    } catch {
      // A transient network hiccup while polling should not break the page - just try again next tick.
      // A job that is genuinely stuck is still caught server-side by the build's own watchdog (see
      // docs/DECISIONS.md), so this loop never needs to give up on its own.
      if (!stopped) timer = setTimeout(tick, intervalMs)
    }
  }

  void tick()
  return () => {
    stopped = true
    if (timer) clearTimeout(timer)
  }
}
