import { useCallback, useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { getProfile } from './api'
import type { ColumnProfile, DatasetView, Kind } from './api'
import { buildThemes, getThemeAnswers, getThemes, getThemesChart, lookInsideOther, mergeThemes, renameTheme, splitTheme } from './themesApi'
import type { ThemeAnswer, ThemeCard, ThemeChartResponse, ThemesResponse } from './themesApi'
import { buildReport, exportReport, getReport } from './reportApi'
import type { ExportFormat, ReportFilters, ReportOtherBreakdown, ReportResponse, ReportThemeSummary } from './reportApi'
import { getLatestJob, pollJob } from './jobsApi'
import type { Job } from './jobsApi'
import InsideOther from './InsideOther'
import { isResult } from './insideOtherModel'
import JobProgress from './JobProgress'
import SharePanel from './SharePanel'
import ReportView from './Report'
import ThemeChart from './ThemeChart'
import ThemeDetail from './ThemeDetail'
import ThemeEditor from './ThemeEditor'
import {
  getGroupPayload, listEdits, mergeBatch, mergePreview, promoteSubTheme, splitPreview, splitSubThemes, startGrouping, undoEdit,
} from './themeEditorApi'
import './upload.css'
import './themes.css'
import './report.css'

const PAGE_SIZE = 20

// How "mostly unique" a column's answered values are - distinct values as a share of answered (non-
// missing) rows. Real free text (genuine survey answers) sits close to 1; a column that LOOKS like open
// text by word count but is actually repeated per-row metadata (product dimensions, category breadcrumbs,
// names, prices - all seen in real datasets, see docs/TODO.md) sits close to 0, often many hundreds of
// rows sharing one identical value.
function uniqueness(c: ColumnProfile, rowCount: number): number {
  const answered = Math.max(1, rowCount - c.missing)
  return c.distinct / answered
}

// Below this, a column reads as repeated metadata, not real answers, regardless of word count - matches
// the backend's own existing cutoff for the same signal (app/profiling/columns.py's open_text confidence:
// `conf = ... else 0.65` below 0.3 uniqueness), reused here rather than inventing a second threshold.
const UNIQUENESS_FLOOR = 0.3

// Picks which confirmed (or, if not yet confirmed, auto-guessed) open_text column the report is built
// from. There is still no UI letting a user choose this directly (docs/TODO.md) - this is the automatic
// fallback every report goes through. It used to be "the first open_text column in upload-column order",
// which reliably picked whichever repeated-metadata column happened to be uploaded first (a dataset's own
// column order has no relationship to which column is actually free text) - confirmed live, more than
// once, on a real dataset.
//
// Two-step pick, both using fields the backend already returns per column (no new endpoint needed):
// 1. Drop any candidate below UNIQUENESS_FLOOR - these are the repeated-metadata columns the fix targets.
// 2. Among what's left, prefer the one with the longest typical answer (`median_words`) - confirmed on a
//    real dataset that uniqueness alone isn't enough to tell two genuinely-free-text columns apart: a
//    review's short title can have a HIGHER uniqueness ratio than its own full-text body (titles are
//    varied short phrases; bodies reuse more boilerplate despite being longer), even though the body is
//    the richer, more meaningful column to actually analyse. If every candidate is below the floor (no
//    genuinely free-text column exists at all), falls back to the most unique one anyway - still better
//    than picking blind.
export function pickOpenTextColumn(profile: {
  columns: ColumnProfile[]
  row_count: number
  confirmed?: {
    columns: Record<string, { kind: Kind; off?: boolean }>
    primary_open_text?: string | null
  }
}): string | null {
  const conf = profile.confirmed
  const candidates = profile.columns.filter(
    (c) => (conf?.columns[c.name]?.kind ?? c.kind) === 'open_text' && !conf?.columns[c.name]?.off,
  )
  if (candidates.length === 0) return null

  // docs/TODO.md (fixed 2026-10-22): an explicit user override wins outright, as long as it's still a
  // real open_text candidate (defends against a confirmed primary that was later re-kinded away from
  // open_text, or switched off, by a later edit this function was never told about).
  if (conf?.primary_open_text && candidates.some((c) => c.name === conf.primary_open_text)) {
    return conf.primary_open_text
  }

  const qualifying = candidates.filter((c) => uniqueness(c, profile.row_count) >= UNIQUENESS_FLOOR)
  const pool = qualifying.length > 0 ? qualifying : candidates
  const rank = qualifying.length > 0 ? (c: ColumnProfile) => c.median_words : (c: ColumnProfile) => uniqueness(c, profile.row_count)
  return pool.reduce((best, c) => (rank(c) > rank(best) ? c : best)).name
}

function Progress() {
  const items = ['Upload', 'Check columns', 'Cleaning review', 'Report']
  return (
    <div className="steps">
      {items.map((t, i) => (
        <span key={t} className={i === 3 ? 'on' : ''}>
          <b>{i + 1}</b>
          {t}
        </span>
      ))}
    </div>
  )
}

export function toneLabel(t: 'neg' | 'neu' | 'pos'): string {
  return t === 'neg' ? 'Negative' : t === 'pos' ? 'Positive' : 'Neutral'
}

export function ToneBar({ tone }: { tone: ThemeCard['tone'] }) {
  return (
    <>
      <div className="th-tonebar" aria-hidden="true">
        {tone.neg > 0 && <div className="neg" style={{ width: `${tone.neg}%` }} />}
        {tone.neu > 0 && <div className="neu" style={{ width: `${tone.neu}%` }} />}
        {tone.pos > 0 && <div className="pos" style={{ width: `${tone.pos}%` }} />}
      </div>
      <div className="th-tonelabels">
        <span className="neg">{Math.round(tone.neg)}% negative</span>
        <span>{Math.round(tone.neu)}% neutral</span>
        <span className="pos">{Math.round(tone.pos)}% positive</span>
      </div>
    </>
  )
}

// `subIndex` given fetches one sub-theme's own answers instead of the parent theme's (see
// themesApi.ts::getThemeAnswers) - same loading/error/offset state machine either way.
export function AnswerList({ id, themeId, subIndex }: { id: number; themeId: number; subIndex?: number }) {
  const [answers, setAnswers] = useState<ThemeAnswer[]>([])
  const [offset, setOffset] = useState(0)
  const [total, setTotal] = useState<number | null>(null)
  const [loading, setLoading] = useState(true)  // the first page starts loading on mount
  const [error, setError] = useState('')

  async function loadMore() {
    setLoading(true)
    setError('')
    try {
      const r = await getThemeAnswers(id, themeId, PAGE_SIZE, offset, subIndex)
      setAnswers((prev) => [...prev, ...r.answers])
      setTotal(r.total)
      setOffset(offset + r.answers.length)
    } catch (e) {
      setError((e as Error).message)
    }
    setLoading(false)
  }

  // First page REPLACES the list. React runs this effect twice in development; appending here loaded
  // page one twice (each answer shown twice, duplicate-key warnings). The cancelled flag drops a
  // superseded run's result.
  useEffect(() => {
    let cancelled = false
    getThemeAnswers(id, themeId, PAGE_SIZE, 0, subIndex)
      .then((r) => {
        if (cancelled) return
        setAnswers(r.answers)
        setTotal(r.total)
        setOffset(r.answers.length)
      })
      .catch((e) => {
        if (!cancelled) setError((e as Error).message)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [id, themeId, subIndex])

  return (
    <div className="th-answers">
      {answers.map((a) => (
        <div key={a.row} className="th-answer">
          <span className={`tag ${a.tone}`}>{toneLabel(a.tone)}</span>
          <div>{a.text ?? <span className="muted">Verbatim text is hidden for your role.</span>}</div>
        </div>
      ))}
      {error && <div className="err" role="alert">{error}</div>}
      {answers.length === 0 && !loading && !error && <div className="muted">No answers to show.</div>}
      {total !== null && offset < total && (
        <button type="button" className="th-more" onClick={() => void loadMore()} disabled={loading}>
          {loading ? 'Loading...' : 'Show more'}
        </button>
      )}
    </div>
  )
}

// The report's theme summary shapes, from the theme rows alone, so Inside Other works before any report.
function summariseThemes(themes: ThemeCard[]): { all: ReportThemeSummary[]; breakdown: ReportOtherBreakdown | null } {
  const answered = themes.reduce((sum, t) => sum + t.size, 0)
  const share = (n: number) => (answered ? Math.round((n / answered) * 1000) / 10 : 0)
  const real = themes.filter((t) => t.label !== 'Other').sort((a, b) => b.size - a.size)
  const other = themes.find((t) => t.label === 'Other')
  return {
    all: real.map((t) => ({ name: t.label, share: share(t.size), count: t.size, sentiment: t.sentiment ?? 0 })),
    breakdown: other && other.size > 0 ? {
      noise_count: other.size, noise_share: share(other.size),
      hidden_real_count: 0, hidden_real_share: 0, hidden_real_theme_count: 0, total_real_theme_count: real.length,
    } : null,
  }
}

export default function Themes() {
  const [params] = useSearchParams()
  const id = Number(params.get('dataset'))
  const [ds, setDs] = useState<DatasetView | null>(null)
  const [column, setColumn] = useState<string | null>(null)
  const [useJev, setUseJev] = useState(false)
  const [themes, setThemes] = useState<ThemeCard[] | null>(null)
  const [themesJob, setThemesJob] = useState<Job | null>(null)
  const [report, setReport] = useState<ReportResponse | null>(null)
  // True until we know whether a report exists (BUG-047: `GET /report` takes ~6 s on a big dataset). While
  // it is true the page shows one loading line, not the theme-editing view with "Build report".
  const [reportLoading, setReportLoading] = useState(true)
  const [reportJob, setReportJob] = useState<Job | null>(null)
  const [lookInsideOtherJob, setLookInsideOtherJob] = useState<Job | null>(null)
  const [autoLookNote, setAutoLookNote] = useState<string | null>(null)
  const [filters, setFilters] = useState<ReportFilters>({})
  const [manageThemes, setManageThemes] = useState(false)
  const [showShare, setShowShare] = useState(false)
  const [exporting, setExporting] = useState<ExportFormat | null>(null)
  const [error, setError] = useState('')
  const [themesChart, setThemesChart] = useState<ThemeChartResponse | null>(null)
  const [selectedThemeId, setSelectedThemeId] = useState<number | null>(null)
  // Theme editing (docs/TODO.md, fixed 2026-10-22): merge checkbox selection, Manage themes mode only.
  // The caller's role (GET /themes): the theme editor's controls are for owners and editors only.
  const [themesRole, setThemesRole] = useState<ThemesResponse['role']>(null)
  const [editedIds, setEditedIds] = useState<Set<number>>(new Set())
  const applyThemes = (resp: ThemesResponse) => {
    setThemes(resp.themes)
    setThemesRole(resp.role ?? null)
    setEditedIds(new Set(resp.edited_ids ?? []))
  }

  // Stable, so the editor's preview panels fetch once per selection, not on every render.
  const loadMergePreview = useCallback(
    (ids: number[]) => mergePreview(id, column as string, ids), [id, column])
  const loadSplitPreview = useCallback(
    (themeId: number, parts?: number) => splitPreview(id, themeId, parts), [id])
  const loadEdits = useCallback(() => listEdits(id, column as string), [id, column])
  const loadGroupPayload = useCallback(() => getGroupPayload(id, column as string), [id, column])
  const [splitThemeJob, setSplitThemeJob] = useState<Job | null>(null)

  // Both builds now run as background jobs (see docs/DECISIONS.md): starting one only creates a `Job` row
  // and returns immediately, so the real "did it work" answer arrives later, from polling. `watch` starts
  // that polling and wires it to whichever `set*Job`/refresh pair the caller is watching; every place that
  // starts or resumes a job (an explicit click, or the page-load resume below) goes through it, so there is
  // exactly one polling implementation for both themes and report jobs, not two near-duplicates.
  function watch(job: Job, setJob: (j: Job | null) => void, refresh: (done: Job) => void): () => void {
    setJob(job)
    if (job.status !== 'running') return () => {}
    return pollJob(id, job.id, (j) => {
      setJob(j)
      if (j.status === 'done') refresh(j)
    })
  }

  // A theme build that leaves Other over 20% of the answers starts Look inside on its own (user decision,
  // 2026-10-25; app/api_themes.py `_queue_auto_look_inside`). Follow that run, or say why it did not start.
  function followAutoLookInside(done: Job, col: string) {
    const auto = done.result && 'auto_look_inside' in done.result ? done.result.auto_look_inside : undefined
    if (auto?.job_id) {
      setAutoLookNote(null)
      watch(
        {
          id: auto.job_id, dataset_id: id, column: col, kind: 'look_inside_other',
          status: 'running', step: 'Waiting to start', error: null, result: null,
        },
        setLookInsideOtherJob,
        () => void refreshAfterLookInsideOther(col),
      )
    } else if (auto?.skipped) {
      setAutoLookNote(`Other holds ${auto.other_share}% of the answers, so Look inside would have started, but: ${auto.skipped}`)
    }
  }

  async function refreshThemes() {
    if (!column) return
    try {
      const existing = await getThemes(id, column)
      applyThemes(existing)
      setThemesJob(null)
      setReport(null) // a rebuilt set of themes needs its report rebuilt too - see build() below
    } catch (e) {
      setError((e as Error).message)
    }
  }

  // Same as refreshThemes, but takes the column explicitly: the page-load effect's closure runs before
  // `column` state is set, so a refresh captured there would see null and do nothing.
  async function reloadAfterThemeRebuild(col: string) {
    try {
      applyThemes(await getThemes(id, col))
      setThemesJob(null)
      setReport(null) // the rebuild invalidated the old report on the server
      setReportLoading(true)
      setReport(await getReport(id, col, filters))
    } catch {
      /* no report after a rebuild is the expected state: the page offers "Build report" */
    } finally {
      setReportLoading(false)
    }
  }

  async function refreshReport() {
    if (!column) return
    setReportLoading(true)
    try {
      setReport(await getReport(id, column, filters))
      setReportJob(null)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setReportLoading(false)
    }
  }

  // "Look inside Other" (docs/TODO.md, 2026-10-21 Stage 3) touches Theme rows (a known theme gains
  // answers, a new theme may appear, Other shrinks) without replacing the whole theme set the way a real
  // rebuild does - unlike refreshThemes/refreshReport above, this does NOT null the job once it resolves:
  // the Known/New/Still-in-Other results panel (LookInsideOther.tsx) stays showing the real final counts
  // from `job.result` until the viewer starts another run, rather than vanishing the moment fresh data
  // arrives.
  // `col` is passed explicitly when this runs from the page-load effect, whose closure predates `column`.
  async function refreshAfterLookInsideOther(col: string | null = column) {
    if (!col) return
    try {
      applyThemes(await getThemes(id, col))
    } catch (e) {
      setError((e as Error).message)
      return
    }
    try {
      setReport(await getReport(id, col, filters)) // still there, now marked stale; Rebuild report updates it
    } catch {
      /* no report yet: the themes screen offers Build report */
    }
  }

  async function startLookInsideOther() {
    setError('')
    setAutoLookNote(null)
    try {
      const started = await lookInsideOther(id, column as string)
      watch(
        {
          id: started.job_id, dataset_id: id, column: column as string, kind: 'look_inside_other',
          status: 'running', step: 'Starting', error: null, result: null,
        },
        setLookInsideOtherJob,
        () => void refreshAfterLookInsideOther(),
      )
    } catch (e) {
      setError((e as Error).message)
    }
  }

  // Filters feature (SPEC.md section 5): changing the filter bar re-fetches the whole report with the new
  // query params - same "control state -> useEffect -> refetch a whole section" idiom as the themesChart
  // effect above. Guarded on `report` already being set so this never double-fetches alongside the
  // initial-load effect below (which does its own first, unfiltered-by-construction `getReport` call).
  useEffect(() => {
    if (!column || !report) return
    let cancelled = false
    getReport(id, column, filters)
      .then((r) => {
        if (!cancelled) setReport(r)
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filters])

  // Fetches the one-chart-at-a-glance treemap fragment for the browse view (Themes.tsx's own reply to the
  // "wall of cards" complaint - see docs/DECISIONS.md) once themes exist, and defaults the selected theme
  // to the largest one (themes[0] - stored themes come back largest-first-by-construction, see
  // app/api_themes.py's `_stored_themes`) so the detail panel below the chart is never empty on first load.
  // Re-runs whenever `themes` changes (including a rebuild), so a stale chart never lingers.
  useEffect(() => {
    if (!column || !themes || themes.length === 0) {
      setThemesChart(null)
      return
    }
    setSelectedThemeId((prev) => (prev != null && themes.some((t) => t.id === prev) ? prev : themes[0].id))
    let cancelled = false
    getThemesChart(id, column)
      .then((c) => {
        if (!cancelled) setThemesChart(c)
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, column, themes])

  useEffect(() => {
    if (!id) return
    let stopThemesPoll = () => {}
    let stopReportPoll = () => {}
    let stopLookInsideOtherPoll = () => {}

    getProfile(id)
      .then(async (d) => {
        setDs(d)
        const col = pickOpenTextColumn(d.profile)
        setColumn(col)
        if (!col) {
          setReportLoading(false)
          return
        }

        // Themes already built (the common case on a normal page view) win outright. Otherwise, before
        // assuming nothing has ever been started, check for a running or just-finished job for this
        // dataset+column - a reload mid-build (or right after one) must resume the progress/error view,
        // never silently fall back to "ready to build" or a stale error.
        let hasThemes = false
        try {
          const existing = await getThemes(id, col)
          if (existing.themes.length > 0) {
            applyThemes(existing)
            hasThemes = true
          }
        } catch {
          /* nothing built yet - fall through to the job lookup below */
        }
        if (!hasThemes) {
          try {
            const job = await getLatestJob(id, col, 'themes')
            if (job) {
              stopThemesPoll = watch(job, setThemesJob, (done) => {
                void reloadAfterThemeRebuild(col)
                followAutoLookInside(done, col)
              })
            }
          } catch {
            /* no job either; show the build trigger */
          }
        } else {
          // Themes exist, but a rebuild may be running (reload, or a second tab). Resume it so the report
          // buttons stay disabled until it finishes: a report built mid-rebuild reads the old themes.
          try {
            const job = await getLatestJob(id, col, 'themes')
            if (job && job.status === 'running') {
              stopThemesPoll = watch(job, setThemesJob, (done) => {
                void reloadAfterThemeRebuild(col)
                followAutoLookInside(done, col)
              })
            }
          } catch {
            /* no theme job */
          }
        }

        let hasReport = false
        try {
          setReport(await getReport(id, col, filters))
          hasReport = true
        } catch {
          /* no report built yet - fall through to the job lookup below */
        }
        if (!hasReport) {
          try {
            const job = await getLatestJob(id, col, 'report')
            if (job) stopReportPoll = watch(job, setReportJob, () => void refreshReport())
          } catch {
            /* no job either; show the build-report trigger once themes exist */
          }
        }
        setReportLoading(false)

        // A reload mid-run (or right after one) must resume this job's own progress/results view too -
        // same reasoning as the themes/report resume above. Unlike those, a `look_inside_other` job that
        // is already "done" is still worth resuming (not just "running"): its `result` is the real
        // Known/New/Still-in-Other panel data, which a fresh `getThemes`/`getReport` call alone cannot
        // reconstruct.
        try {
          const job = await getLatestJob(id, col, 'look_inside_other')
          if (job) stopLookInsideOtherPoll = watch(job, setLookInsideOtherJob, () => void refreshAfterLookInsideOther(col))
        } catch {
          /* nothing run yet */
        }
      })
      .catch((e: Error) => setError(e.message))

    return () => {
      stopThemesPoll()
      stopReportPoll()
      stopLookInsideOtherPoll()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id])

  if (!id) {
    return (
      <>
        <h1>Report</h1>
        <p className="muted">
          Nothing to report yet. <Link to="/upload">Upload a spreadsheet</Link> first.
        </p>
      </>
    )
  }
  if (!ds) {
    return error ? (
      <>
        <h1>Report</h1>
        <p className="err" role="alert">{error}</p>
      </>
    ) : (
      <p className="muted">Looking at your data...</p>
    )
  }
  if (!column) {
    return (
      <>
        <div className="head">
          <h1>Report</h1>
          <Progress />
        </div>
        <p className="muted">
          No open-ended text column was confirmed for this file, so there is nothing to build themes from.{' '}
          <Link to={`/check-columns?dataset=${id}`}>Go back and check columns</Link>.
        </p>
      </>
    )
  }

  async function build() {
    setError('')
    try {
      const started = await buildThemes(id, column as string, useJev)
      setThemes(null)
      setLookInsideOtherJob(null) // the server dropped the old run's result with the old themes
      setAutoLookNote(null)
      watch(
        { id: started.job_id, dataset_id: id, column: column as string, kind: 'themes', status: 'running', step: 'Starting', error: null, result: null },
        setThemesJob,
        (done) => {
          void refreshThemes()
          followAutoLookInside(done, column as string)
        },
      )
    } catch (e) {
      // A cheap/instant check failed before any job started (e.g. a missing key, or busy) - still an
      // immediate error, exactly as before.
      setError((e as Error).message)
    }
  }

  async function buildTheReport() {
    setError('')
    try {
      const started = await buildReport(id, column as string)
      setReport(null)
      setManageThemes(false)
      watch(
        { id: started.job_id, dataset_id: id, column: column as string, kind: 'report', status: 'running', step: 'Starting', error: null, result: null },
        setReportJob,
        () => void refreshReport(),
      )
    } catch (e) {
      setError((e as Error).message)
    }
  }

  // Theme editing (docs/TODO.md, fixed 2026-10-22): both invalidate the server-side report (see
  // app/api_themes.py's own comment), so the local `report` state is cleared too - the user sees the
  // existing "no report built yet" / "Rebuild report" state next time they leave Manage themes, the
  // same state a fresh build-themes run already produces, not a new UI path.
  async function refreshThemesChartAndList() {
    if (!column) return
    const existing = await getThemes(id, column)
    applyThemes(existing)
    setSelectedThemeId((prev) => (prev != null && existing.themes.some((t) => t.id === prev) ? prev : existing.themes[0]?.id ?? null))
    setThemesChart(await getThemesChart(id, column))
  }

  // Theme editor callbacks: they throw on failure, and ThemeEditor shows the message in its own panel.
  // Each edit resolves to the token that undoes it.
  async function afterEdit<T extends { undo_token: number }>(edit: Promise<T>): Promise<number> {
    const { undo_token } = await edit
    setReport(null)
    await refreshThemesChartAndList()
    return undo_token
  }
  const handleRename = (themeId: number, label: string) => afterEdit(renameTheme(id, themeId, label))
  const handleMerge = (themeIds: number[], label: string) => afterEdit(mergeThemes(id, column as string, themeIds, label))
  const handleSplitParts = (themeId: number, parts: number) => afterEdit(splitSubThemes(id, themeId, parts))
  const handlePromote = (themeId: number, index: number) => afterEdit(promoteSubTheme(id, themeId, index))
  const grouping = {
    loadPayload: loadGroupPayload,
    start: () => startGrouping(id, column as string),
    poll: (jobId: number, onUpdate: (job: Job) => void) => pollJob(id, jobId, onUpdate),
    applyBatch: (groups: Array<{ name: string; theme_ids: number[] }>) => afterEdit(mergeBatch(id, column as string, groups)),
  }

  async function handleUndo(token: number) {
    await undoEdit(id, column as string, token)
    setReport(null)
    await refreshThemesChartAndList()
  }

  async function startSplitTheme(themeId: number) {
    const started = await splitTheme(id, themeId)
    watch(
      {
        id: started.job_id, dataset_id: id, column: column as string, kind: 'split_theme',
        status: 'running', step: 'Starting', error: null, result: null,
      },
      setSplitThemeJob,
      () => {
        setReport(null)
        void refreshThemesChartAndList()
      },
    )
  }

  async function handleExport(format: ExportFormat) {
    if (!column) return
    setError('')
    setExporting(format)
    try {
      const blob = await exportReport(id, column, format)
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `report-${id}-${column}.${format}`.replace(/\s+/g, '_')
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
    } catch (e) {
      setError((e as Error).message)
    }
    setExporting(null)
  }

  const themesRunning = themesJob !== null && themesJob.status === 'running'
  const themesFailed = themesJob !== null && themesJob.status === 'failed'
  const reportRunning = reportJob !== null && reportJob.status === 'running'
  const reportFailed = reportJob !== null && reportJob.status === 'failed'
  const lookRunning = lookInsideOtherJob !== null && lookInsideOtherJob.status === 'running'
  // Look inside on the themes screen (user decision, 2026-10-25): the first build's chart, the flow, then
  // the updated themes under it, then Build report.
  const lookResult = lookInsideOtherJob?.status === 'done' && isResult(lookInsideOtherJob.result) ? lookInsideOtherJob.result : null
  const beforeChart = lookResult?.before_chart ?? null
  const themeSummaries = themes ? summariseThemes(themes) : null
  // A report may exist and is still being fetched: show only a loading line (BUG-047). Manage themes
  // opens the editing view regardless.
  const reportPending = reportLoading && !report && !manageThemes

  return (
    <>
      <div className="head">
        <h1>Report</h1>
        <Progress />
      </div>
      {/* Introduces the theme cards; the report has its own title and summary. */}
      {!report && !reportPending && (
        <div className="th-summary">
          Themes for <b>{column}</b>. Every theme links back to real answers - use "See answers" on any card.
        </div>
      )}

      {error && <div className="err" role="alert">{error}</div>}

      {themesRunning && themesJob && <JobProgress job={themesJob} />}

      {reportPending && !themesRunning && <p className="muted" role="status">Loading the report...</p>}

      {themesFailed && themesJob && (
        <div className="jp-failed">
          <div className="big">Building themes didn't work</div>
          <p className="err" role="alert">{themesJob.error}</p>
          <button type="button" className="btn" onClick={() => void build()}>
            Try again
          </button>
        </div>
      )}

      {!themesJob && themes === null && !reportPending && (
        <div className="th-build">
          <div className="big">Ready to find themes</div>
          <p className="small">
            We will group similar answers into themes, label them and score their tone. This can take a minute or two
            for a large file.
          </p>
          <label className="jev">
            <input type="checkbox" checked={useJev} onChange={(e) => setUseJev(e.target.checked)} />
            Use Jev for sentiment (optional, needs a TypeSafe key)
          </label>
          <div>
            <button type="button" className="btn" onClick={() => void build()}>
              Build themes
            </button>
          </div>
        </div>
      )}

      {themes !== null && report && !manageThemes && (
        <>
          {report.stale && (
            <div className="report-stale" role="status">
              <span>
                {report.stale_reason === 'question_kind'
                  ? 'You changed what the question asks for, so the findings are out of date.'
                  : 'The themes changed after this report was built, so its findings are out of date.'}
              </span>
              <button type="button" className="btn" onClick={() => void buildTheReport()} disabled={reportRunning || themesRunning || lookRunning}>
                {reportRunning ? 'Rebuilding report...' : 'Rebuild report'}
              </button>
            </div>
          )}
          <ReportView
            report={report}
            datasetId={id}
            themes={themes ?? undefined}
            filters={filters}
            onFiltersChange={setFilters}
            lookInsideOtherJob={lookInsideOtherJob}
            onQuestionKindChange={() => {
              if (column) getReport(id, column, filters).then(setReport).catch(() => { /* keeps the current view */ })
            }}
          />
          <div className="foot report-foot">
            <div className="report-foot-group">
              <button type="button" className="btn quiet" onClick={() => void buildTheReport()} disabled={reportRunning || themesRunning || lookRunning}>
                {reportRunning ? 'Rebuilding report...' : 'Rebuild report'}
              </button>
              <button type="button" className="btn quiet" onClick={() => setManageThemes(true)}>
                Manage themes
              </button>
              <button type="button" className="btn quiet" onClick={() => setShowShare(!showShare)}>
                {showShare ? 'Hide sharing' : 'Share'}
              </button>
            </div>
            <div className="report-foot-group">
              {/* Export (docs/TODO.md, fixed 2026-10-22): no SVG option here - see app/export.py's own
                  module docstring for why that format is deliberately not offered. */}
              {(['png', 'pptx', 'pdf'] as const).map((fmt) => (
                <button
                  key={fmt}
                  type="button"
                  className="btn quiet"
                  disabled={exporting !== null}
                  onClick={() => void handleExport(fmt)}
                >
                  {exporting === fmt ? 'Exporting...' : `Export ${fmt.toUpperCase()}`}
                </button>
              ))}
            </div>
          </div>
          {showShare && column && <SharePanel datasetId={id} column={column} />}
        </>
      )}

      {themes !== null && (!report || manageThemes) && !reportPending && (
        <>
          {/* One chart showing every theme at a glance, replacing the old wall-of-cards grid (see
              docs/DECISIONS.md). Clicking or hovering a theme in the chart is handled by ThemeChart
              itself (see its own comment); the selected theme's full detail renders once, below. */}
          {themesChart ? (
            <>
              {(() => {
                const current = (
                  <ThemeChart
                    fragment={themesChart}
                    title={beforeChart ? 'Updated themes' : 'Themes'}
                    onThemeSelect={(name) => {
                      const t = themes.find((x) => x.label === name)
                      if (t) setSelectedThemeId(t.id)
                    }}
                    selectedTheme={themes.find((t) => t.id === selectedThemeId)?.label ?? null}
                    highlightOtherRunning={lookRunning}
                  />
                )
                const showInside = themeSummaries?.breakdown != null || lookInsideOtherJob !== null
                return (
                  <>
                    {beforeChart ? (
                      <section className="th-stage">
                        <p className="th-stage-label">First build</p>
                        <ThemeChart fragment={beforeChart} title="First build" />
                      </section>
                    ) : current}
                    {showInside && themeSummaries && (
                      <InsideOther
                        job={lookInsideOtherJob} onStart={() => void startLookInsideOther()} context="themes"
                        allThemes={themeSummaries.all} breakdown={themeSummaries.breakdown} note={autoLookNote}
                      />
                    )}
                    {beforeChart && (
                      <section className="th-stage">
                        <p className="th-stage-label">Updated themes</p>
                        {current}
                      </section>
                    )}
                  </>
                )
              })()}
              {(() => {
                const selected = themes.find((t) => t.id === selectedThemeId)
                return selected ? <ThemeDetail id={id} theme={selected} /> : null
              })()}
              <ThemeEditor
                themes={themes} totalAnswers={themes.reduce((n, t) => n + t.size, 0)}
                canEdit={themesRole === 'owner' || themesRole === 'editor'} splitJob={splitThemeJob} edited={editedIds}
                onRename={handleRename} onMerge={handleMerge} onSplit={startSplitTheme} onSplitParts={handleSplitParts}
                onPromote={handlePromote} onUndo={handleUndo} loadEdits={loadEdits} grouping={grouping}
                loadMergePreview={loadMergePreview} loadSplitPreview={loadSplitPreview}
              />
            </>
          ) : (
            <p className="muted">Loading the themes chart...</p>
          )}
          <div className="foot">
            <button type="button" className="btn quiet" onClick={() => void build()}>
              Rebuild themes
            </button>
            {report && (
              <button type="button" className="btn quiet" onClick={() => setManageThemes(false)}>
                Back to report
              </button>
            )}
          </div>

          {!report && (
            <div className="rp-build">
              {reportRunning && reportJob ? (
                <JobProgress job={reportJob} />
              ) : reportFailed && reportJob ? (
                <div className="jp-failed">
                  <div className="big">Building the report didn't work</div>
                  <p className="err" role="alert">{reportJob.error}</p>
                  <button type="button" className="btn" onClick={() => void buildTheReport()} disabled={themesRunning || lookRunning}>
                    Try again
                  </button>
                </div>
              ) : (
                <div className="th-build">
                  <div className="big">Ready to build the report</div>
                  <p className="small">
                    We will pick the strongest, best-supported findings from these themes, write one plain
                    sentence for each, and choose the chart that shows it best.
                  </p>
                  <button type="button" className="btn" onClick={() => void buildTheReport()} disabled={themesRunning || lookRunning}>
                    Build report
                  </button>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </>
  )
}
