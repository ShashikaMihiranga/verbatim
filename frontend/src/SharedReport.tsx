import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import ReportView from './Report'
import type { ReportResponse } from './reportApi'

// Sharing/roles (docs/TODO.md, fixed 2026-10-22). Deliberately NOT behind App.tsx's sign-in guard - a
// share link means "no sign-in required" by definition. Uses plain `fetch`, not `authFetch`, so nothing
// here depends on any Clerk session state at all (a signed-out visitor hits this exact same code path as
// a signed-in one). No `onFiltersChange`/`onLookInsideOther` passed to ReportView - both would need an
// authenticated route this visitor was never granted, so this is read-only, same as the share link's own
// "viewer" intent; no verbatim answers either, since the backend route this calls never includes any
// (see app/api_sharing.py's own module docstring for why that's enforced by omission, not a toggle).
export default function SharedReport() {
  const [params] = useSearchParams()
  const token = params.get('token')
  const [report, setReport] = useState<ReportResponse | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!token) {
      setError('This link is missing its token.')
      return
    }
    fetch(`/api/share/${token}/report`)
      .then(async (r) => {
        if (!r.ok) {
          const body = await r.json().catch(() => null)
          throw new Error(typeof body?.detail === 'string' ? body.detail : 'This link is invalid or has expired.')
        }
        return r.json()
      })
      .then(setReport)
      .catch((e: Error) => setError(e.message))
  }, [token])

  if (error) {
    return (
      <div className="page">
        <h1>Shared report</h1>
        <p className="err" role="alert">{error}</p>
      </div>
    )
  }
  if (!report) {
    return (
      <div className="page">
        <p className="muted">Loading...</p>
      </div>
    )
  }
  return (
    <div className="page">
      <ReportView report={report} datasetId={0} publicView />
    </div>
  )
}
