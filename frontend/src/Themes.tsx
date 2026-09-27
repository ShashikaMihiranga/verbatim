import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { getProfile } from './api'
import type { DatasetView } from './api'
import { buildThemes, getThemeAnswers, getThemes } from './themesApi'
import type { ThemeAnswer, ThemeCard } from './themesApi'
import { buildReport, getReport } from './reportApi'
import type { ReportResponse } from './reportApi'
import ReportView from './Report'
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

function ToneBar({ tone }: { tone: ThemeCard['tone'] }) {
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

export function AnswerList({ id, themeId }: { id: number; themeId: number }) {
  const [answers, setAnswers] = useState<ThemeAnswer[]>([])
  const [offset, setOffset] = useState(0)
  const [total, setTotal] = useState<number | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function loadMore() {
    setLoading(true)
    setError('')
    try {
      const r = await getThemeAnswers(id, themeId, PAGE_SIZE, offset)
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

function Card({ id, theme }: { id: number; theme: ThemeCard }) {
  const [open, setOpen] = useState(false)
  const isOther = theme.label === 'Other'
  return (
    <div className={`th-card${isOther ? ' other' : ''}`}>
      <div className="th-top">
        <div className="th-label">{theme.label}</div>
        <span className={`th-badge ${theme.confidence}`}>{theme.confidence === 'solid' ? 'Solid' : 'Tentative'}</span>
      </div>
      {theme.description && <div className="th-desc">{theme.description}</div>}
      <div className="th-pct">
        {Math.round(theme.size_pct)}%<span>of answers</span>
      </div>
      <ToneBar tone={theme.tone} />
      <button type="button" className="th-see" onClick={() => setOpen(!open)}>
        {open ? 'Hide answers' : 'See answers'}
      </button>
      {open && <AnswerList id={id} themeId={theme.id} />}
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
  const [building, setBuilding] = useState(false)
  const [report, setReport] = useState<ReportResponse | null>(null)
  const [reportBuilding, setReportBuilding] = useState(false)
  const [manageThemes, setManageThemes] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!id) return
    getProfile(id)
      .then(async (d) => {
        setDs(d)
        const conf = d.profile.confirmed
        const col =
          d.profile.columns.find((c) => (conf?.columns[c.name]?.kind ?? c.kind) === 'open_text' && !conf?.columns[c.name]?.off)
            ?.name ?? null
        setColumn(col)
        if (col) {
          try {
            const existing = await getThemes(id, col)
            if (existing.themes.length > 0) setThemes(existing.themes)
          } catch {
            /* nothing built yet; show the build trigger */
          }
          try {
            setReport(await getReport(id, col))
          } catch {
            /* no report built yet; show the build-report trigger once themes exist */
          }
        }
      })
      .catch((e: Error) => setError(e.message))
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
    setBuilding(true)
    setError('')
    try {
      const r = await buildThemes(id, column as string, useJev)
      setThemes(r.themes)
      setReport(null)  // old report (if any) no longer matches the rebuilt themes - build it again below
    } catch (e) {
      setError((e as Error).message)
    }
    setBuilding(false)
  }

  async function buildTheReport() {
    setReportBuilding(true)
    setError('')
    try {
      setReport(await buildReport(id, column as string))
      setManageThemes(false)
    } catch (e) {
      setError((e as Error).message)
    }
    setReportBuilding(false)
  }

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

      {building && (
        <div className="th-progress">
          <div className="big">Finding themes in your answers...</div>
          <div>This can take a minute or two for a large file. Please stay on this page.</div>
        </div>
      )}

      {!building && themes === null && (
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

      {!building && themes !== null && report && !manageThemes && (
        <>
          <ReportView report={report} datasetId={id} />
          <div className="foot">
            <button type="button" className="btn quiet" onClick={() => void buildTheReport()} disabled={reportBuilding}>
              {reportBuilding ? 'Rebuilding report...' : 'Rebuild report'}
            </button>
            <button type="button" className="btn quiet" onClick={() => setManageThemes(true)}>
              Manage themes
            </button>
          </div>
        </>
      )}

      {!building && themes !== null && (!report || manageThemes) && (
        <>
          <div className="th-grid">
            {themes.map((t) => (
              <Card key={t.id} id={id} theme={t} />
            ))}
          </div>
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
              {reportBuilding ? (
                <div className="th-progress">
                  <div className="big">Building your report...</div>
                  <div>This can take a little while for a large file. Please stay on this page.</div>
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
