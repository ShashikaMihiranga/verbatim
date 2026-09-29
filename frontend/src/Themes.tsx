import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { getProfile } from './api'
import type { DatasetView } from './api'
import { buildThemes, getThemeAnswers, getThemes, getThemesChart } from './themesApi'
import type { ThemeAnswer, ThemeCard, ThemeChartResponse } from './themesApi'
import { buildReport, getReport } from './reportApi'
import type { ReportResponse } from './reportApi'
import { getLatestJob, pollJob } from './jobsApi'
import type { Job } from './jobsApi'
import JobProgress from './JobProgress'
import ReportView from './Report'
import ThemeChart from './ThemeChart'
import ThemeDetail from './ThemeDetail'
import './upload.css'
import './themes.css'
import './report.css'

const PAGE_SIZE = 20

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
  const [loading, setLoading] = useState(false)
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

  useEffect(() => {
    void loadMore()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="th-answers">
      {answers.map((a) => (
        <div key={a.row} className="th-answer">
          <span className={`tag ${a.tone}`}>{toneLabel(a.tone)}</span>
          <div>{a.text}</div>
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

export default function Themes() {
  const [params] = useSearchParams()
  const id = Number(params.get('dataset'))
  const [ds, setDs] = useState<DatasetView | null>(null)
  const [column, setColumn] = useState<string | null>(null)
  const [useJev, setUseJev] = useState(false)
  const [themes, setThemes] = useState<ThemeCard[] | null>(null)
  const [themesJob, setThemesJob] = useState<Job | null>(null)
  const [report, setReport] = useState<ReportResponse | null>(null)
  const [reportJob, setReportJob] = useState<Job | null>(null)
  const [manageThemes, setManageThemes] = useState(false)
  const [error, setError] = useState('')
  const [themesChart, setThemesChart] = useState<ThemeChartResponse | null>(null)
  const [selectedThemeId, setSelectedThemeId] = useState<number | null>(null)

  // Both builds now run as background jobs (see docs/DECISIONS.md): starting one only creates a `Job` row
  // and returns immediately, so the real "did it work" answer arrives later, from polling. `watch` starts
  // that polling and wires it to whichever `set*Job`/refresh pair the caller is watching; every place that
  // starts or resumes a job (an explicit click, or the page-load resume below) goes through it, so there is
  // exactly one polling implementation for both themes and report jobs, not two near-duplicates.
  function watch(job: Job, setJob: (j: Job | null) => void, refresh: () => void): () => void {
    setJob(job)
    if (job.status !== 'running') return () => {}
    return pollJob(id, job.id, (j) => {
      setJob(j)
      if (j.status === 'done') refresh()
    })
  }

  async function refreshThemes() {
    if (!column) return
    try {
      const existing = await getThemes(id, column)
      setThemes(existing.themes)
      setThemesJob(null)
      setReport(null) // a rebuilt set of themes needs its report rebuilt too - see build() below
    } catch (e) {
      setError((e as Error).message)
    }
  }

  async function refreshReport() {
    if (!column) return
    try {
      setReport(await getReport(id, column))
      setReportJob(null)
    } catch (e) {
      setError((e as Error).message)
    }
  }

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

    getProfile(id)
      .then(async (d) => {
        setDs(d)
        const conf = d.profile.confirmed
        const col =
          d.profile.columns.find((c) => (conf?.columns[c.name]?.kind ?? c.kind) === 'open_text' && !conf?.columns[c.name]?.off)
            ?.name ?? null
        setColumn(col)
        if (!col) return

        // Themes already built (the common case on a normal page view) win outright. Otherwise, before
        // assuming nothing has ever been started, check for a running or just-finished job for this
        // dataset+column - a reload mid-build (or right after one) must resume the progress/error view,
        // never silently fall back to "ready to build" or a stale error.
        let hasThemes = false
        try {
          const existing = await getThemes(id, col)
          if (existing.themes.length > 0) {
            setThemes(existing.themes)
            hasThemes = true
          }
        } catch {
          /* nothing built yet - fall through to the job lookup below */
        }
        if (!hasThemes) {
          try {
            const job = await getLatestJob(id, col, 'themes')
            if (job) stopThemesPoll = watch(job, setThemesJob, () => void refreshThemes())
          } catch {
            /* no job either; show the build trigger */
          }
        }

        let hasReport = false
        try {
          setReport(await getReport(id, col))
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
      })
      .catch((e: Error) => setError(e.message))

    return () => {
      stopThemesPoll()
      stopReportPoll()
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
      watch(
        { id: started.job_id, dataset_id: id, column: column as string, kind: 'themes', status: 'running', step: 'Starting', error: null },
        setThemesJob,
        () => void refreshThemes(),
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
        { id: started.job_id, dataset_id: id, column: column as string, kind: 'report', status: 'running', step: 'Starting', error: null },
        setReportJob,
        () => void refreshReport(),
      )
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const themesRunning = themesJob !== null && themesJob.status === 'running'
  const themesFailed = themesJob !== null && themesJob.status === 'failed'
  const reportRunning = reportJob !== null && reportJob.status === 'running'
  const reportFailed = reportJob !== null && reportJob.status === 'failed'

  return (
    <>
      <div className="head">
        <h1>Report</h1>
        <Progress />
      </div>
      <div className="th-summary">
        Themes for <b>{column}</b>. Every theme links back to real answers - use "See answers" on any card.
      </div>

      {error && <div className="err" role="alert">{error}</div>}

      {themesRunning && themesJob && <JobProgress job={themesJob} />}

      {themesFailed && themesJob && (
        <div className="jp-failed">
          <div className="big">Building themes didn't work</div>
          <p className="err" role="alert">{themesJob.error}</p>
          <button type="button" className="btn" onClick={() => void build()}>
            Try again
          </button>
        </div>
      )}

      {!themesJob && themes === null && (
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
          <ReportView report={report} datasetId={id} themes={themes ?? undefined} />
          <div className="foot">
            <button type="button" className="btn quiet" onClick={() => void buildTheReport()} disabled={reportRunning}>
              {reportRunning ? 'Rebuilding report...' : 'Rebuild report'}
            </button>
            <button type="button" className="btn quiet" onClick={() => setManageThemes(true)}>
              Manage themes
            </button>
          </div>
        </>
      )}

      {themes !== null && (!report || manageThemes) && (
        <>
          {/* One chart showing every theme at a glance, replacing the old wall-of-cards grid (see
              docs/DECISIONS.md). Clicking or hovering a theme in the chart is handled by ThemeChart
              itself (see its own comment); the selected theme's full detail renders once, below. */}
          {themesChart ? (
            <>
              <ThemeChart
                fragment={themesChart}
                title="Themes"
                onThemeSelect={(name) => {
                  const t = themes.find((x) => x.label === name)
                  if (t) setSelectedThemeId(t.id)
                }}
              />
              {(() => {
                const selected = themes.find((t) => t.id === selectedThemeId)
                return selected ? <ThemeDetail id={id} theme={selected} /> : null
              })()}
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
                  <button type="button" className="btn" onClick={() => void buildTheReport()}>
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
                  <button type="button" className="btn" onClick={() => void buildTheReport()}>
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
