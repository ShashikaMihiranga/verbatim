import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import ReportView from './Report'
import type { ReportResponse } from './reportApi'
import { loadSampleReport } from './home/sampleReport'

// "See a sample report" (home page): the frozen 10k workplace-survey report, shown read-only the same way
// a share link shows a report (SharedReport.tsx): no sign-in, no filters, no answer drill-down.
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
    <div className="page">
      <p className="muted" style={{ marginTop: 0 }}>
        <Link to="/">Verbatim</Link> · A sample report, built from the written comments in a workplace survey.{' '}
        <Link to="/sign-up">Make one from your own sheet</Link>
      </p>
      {error && <p className="err" role="alert">{error}</p>}
      {!error && !report && <p className="muted">Loading...</p>}
      {report && <ReportView report={report} datasetId={0} />}
    </div>
  )
}
