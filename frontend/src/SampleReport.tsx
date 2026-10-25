import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import ReportView from './Report'
import type { ReportResponse } from './reportApi'
import { Arrow, Logo } from './home/homeArt'
import { loadSampleReport } from './home/sampleReport'
import './home/home-d.css'

// "See a sample report" (home page): the frozen 10k workplace-survey report (dataset 13, user's choice),
// shown read-only like a share link, inside the home page's frame: no sign-in, no filters, no answer
// drill-down, no analyst explorations.
export default function SampleReport() {
  const [report, setReport] = useState<ReportResponse | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    document.title = 'Sample report - Verbatim'
    let live = true
    loadSampleReport().then((r) => { if (live) setReport(r) }).catch((e: Error) => { if (live) setError(e.message) })
    return () => { live = false }
  }, [])

  return (
    <div className="hd">
      <header className="hd-nav">
        <div className="hd-wrap hd-x hd-nav-in">
          <Link to="/home" className="hd-brand" aria-label="Verbatim home"><Logo size={40} /><span>Verbatim</span></Link>
          <nav className="hd-links" aria-label="Main">
            <Link className="hd-hide-s" to="/home#how-it-works">How it works</Link>
            <Link className="hd-signin" to="/sign-in">Sign in</Link>
            <Link className="hd-outline" to="/sign-up">Get started</Link>
          </nav>
        </div>
      </header>

      <main className="hd-wrap hd-x">
        <section className="sp-head" aria-labelledby="sp-h1">
          <div className="hd-eye">Sample report</div>
          <h1 id="sp-h1" className="sp-h1">What people said about their workplace.</h1>
          <p className="hd-lead">
            Verbatim read the written comments from a workplace survey and built this report. It is read-only.
            Names, emails and numbers were masked before anything was analysed.
          </p>
          {report && <p className="sp-summary">{report.summary}</p>}
          <div className="hd-btns" style={{ marginTop: 28 }}>
            <Link className="hd-btn main" to="/sign-up">Make one from your own sheet<Arrow /></Link>
            <Link className="hd-btn ghost" to="/home">How it works</Link>
          </div>
        </section>

        <div className="sp-report">
          {error && <p className="err" role="alert">{error}</p>}
          {!error && !report && <p className="sp-loading">Loading the sample report...</p>}
          {report && <ReportView report={report} datasetId={0} publicView bare />}
        </div>

        <section style={{ marginTop: 80, marginBottom: 80 }} aria-labelledby="sp-cta-h">
          <div className="hd-cta">
            <div>
              <h2 id="sp-cta-h" className="hd-cta-h">Turn your next survey into a clear report.</h2>
              <p className="hd-cta-s">Upload a sheet. Check the columns. Read the story.</p>
            </div>
            <div className="hd-cta-btns">
              <Link className="hd-cta-btn white" to="/sign-up">Get started</Link>
              <Link className="hd-cta-btn line" to="/home">Back to the home page</Link>
            </div>
          </div>
        </section>
      </main>
    </div>
  )
}
