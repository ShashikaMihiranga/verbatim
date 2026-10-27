import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { roundedRowCount } from './Projects'
import { getProjects } from './projectsApi'
import type { ProjectSummary } from './projectsApi'
import './projects.css'

// The Reports page with no project picked (the menu's "Reports" link, BUG-062): every project that has a
// report, newest first, and below them the ones that are cleaned but have no report yet. Each opens
// /report?dataset=. Deleting stays on Projects.
function Row({ project, label }: { project: ProjectSummary; label: string }) {
  return (
    <div className="pr-row">
      <Link to={`/report?dataset=${project.id}`} className="pr-link">
        <div className="pr-main">
          <div className="pr-title">{project.question || project.filename}</div>
          <div className="pr-sub muted">
            {roundedRowCount(project.row_count)}{project.question ? <> &middot; {project.filename}</> : null}
          </div>
        </div>
        <span className={`pr-status pr-status-${project.status.replace(/\s+/g, '-')}`}>{label}</span>
      </Link>
    </div>
  )
}

export default function ReportsIndex() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let live = true
    getProjects().then((p) => { if (live) setProjects(p) }).catch((e: Error) => { if (live) setError(e.message) })
    return () => { live = false }
  }, [])

  const ready = (projects ?? []).filter((p) => p.status === 'report ready')
  const waiting = (projects ?? []).filter((p) => p.status === 'cleaned' || p.status === 'themes built')
  return (
    <>
      <h1>Reports</h1>
      {error && <p className="err" role="alert">{error}</p>}
      {!error && projects === null && <p className="muted">Looking at your reports...</p>}
      {projects !== null && ready.length === 0 && waiting.length === 0 && (
        <p className="muted">
          Nothing to report yet. <Link to="/upload">Upload a spreadsheet</Link> first.
        </p>
      )}
      {ready.length > 0 && (
        <div className="pr-list">
          {ready.map((p) => <Row key={p.id} project={p} label="Report ready" />)}
        </div>
      )}
      {waiting.length > 0 && (
        <>
          <h2 className="pr-subhead">No report yet</h2>
          <div className="pr-list">
            {waiting.map((p) => <Row key={p.id} project={p} label={p.status === 'themes built' ? 'Themes built' : 'Cleaned'} />)}
          </div>
        </>
      )}
    </>
  )
}
