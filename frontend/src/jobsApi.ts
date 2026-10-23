import { authFetch } from './authFetch'
import type { ToneSplit } from './themesApi'

export type JobKind = 'themes' | 'report' | 'look_inside_other' | 'split_theme'
export type JobStatus = 'running' | 'done' | 'failed'

// Stage 3a (docs/TODO.md, fixed 2026-10-23): one newly-found theme's real numbers, same shape
// app/api_themes.py::_apply_other_classification's own new_themes_summary entries now carry.
export interface LookInsideOtherNewTheme {
  label: string
  count: number
  sentiment: number
  tone: ToneSplit
}

// Stage 3a: one result-chart tab's ready-to-embed fragment - the SAME shape every other chart fragment
// in this app already uses (see reportApi.ts's own ReportThemeChartVariant). Keyed by chart id
// ("othergrowth" | "rank" | "icicle" | "sentsun") - no "arc" key; see LookInsideOtherCharts.tsx's own
// comment for why that tab is handled client-side instead of from a chart fragment.
export interface LookInsideOtherChart {
  chart_title: string
  chart_html: string
  chart_width: number
  chart_height: number
}

// "Look inside Other" (docs/TODO.md, 2026-10-21 Stage 3, extended 2026-10-23 Stage 3a): the real
// Known/New/Still-in-Other counts the results panel needs, plus (Stage 3a) real per-new-theme
// sentiment/tone/charts - written by app/api_themes.py's own job route in the same commit as the
// Theme-row changes it summarizes, never reconstructed client-side from a second fetch. `charts` is
// `undefined`/absent when no new theme survived this run (nothing to chart).
export interface LookInsideOtherResult {
  known_added: number
  new_themes: LookInsideOtherNewTheme[]
  still_other_count: number
  charts?: Record<string, LookInsideOtherChart>
  // Fixed 2026-10-23: a systemic Jev failure (every row rejected on a bad API key, say) used to look
  // identical to a legitimate "nothing matched" result - known_added/new_themes both zero, with no
  // visible sign anything went wrong. A failed row still stays in Other either way (never lost); this
  // only makes a failure VISIBLE instead of indistinguishable from a real empty result.
  failed_classification_count: number
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
