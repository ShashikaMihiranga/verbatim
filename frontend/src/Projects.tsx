import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { getProjects } from './projectsApi'
import type { ProjectStatus, ProjectSummary } from './projectsApi'
import './upload.css'
import './projects.css'

// Plain-English status text and where "reopen" sends the user next - matches whichever screen actually
// resolves that stage of work (Themes.tsx/Cleaning.tsx both read the dataset id from the same `?dataset=`
// query param, so links here follow that exact convention rather than inventing a new one).
const STATUS_LABEL: Record<ProjectStatus, string> = {
  uploaded: 'Uploaded',
  'columns confirmed': 'Columns confirmed',
  cleaned: 'Cleaned',
  'themes built': 'Themes built',
  'report ready': 'Report ready',
}

function linkFor(p: ProjectSummary): string {
  if (p.status === 'uploaded') return `/check-columns?dataset=${p.id}`
  if (p.status === 'columns confirmed') return `/cleaning?dataset=${p.id}`
  return `/report?dataset=${p.id}` // cleaned, themes built, or report ready: Themes.tsx owns the rest of the flow
}

// No exact record counts (CLAUDE.md's design rule): rounded to one or two significant figures, same spirit
// as the design reference's "Recent projects" list without repeating its precise numbers.
export function roundedRowCount(n: number): string {
  if (!Number.isFinite(n) || n <= 0) return '0 rows'
  const digits = Math.floor(Math.log10(n)) + 1
  const sig = digits <= 2 ? 1 : 2
  const magnitude = 10 ** Math.max(0, digits - sig)
  const rounded = Math.round(n / magnitude) * magnitude
  return `about ${rounded.toLocaleString()} rows`
}

function whenUploaded(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })
}

export function ProjectRow({ project }: { project: ProjectSummary }) {
  const title = project.question || project.filename
  return (
    <Link to={linkFor(project)} className="pr-row">
      <div className="pr-main">
        <div className="pr-title">{title}</div>
        <div className="pr-sub muted">
          {roundedRowCount(project.row_count)} &middot; uploaded {whenUploaded(project.created_at)}
        </div>
      </div>
      <span className={`pr-status pr-status-${project.status.replace(/\s+/g, '-')}`}>
        {STATUS_LABEL[project.status]}
      </span>
    </Link>
  )
}

export function ProjectsList({ projects }: { projects: ProjectSummary[] }) {
  if (projects.length === 0) {
    return (
      <p className="muted">
        No projects yet - <Link to="/upload">upload a spreadsheet to start</Link>.
      </p>
    )
  }
  return (
    <div className="pr-list">
      {projects.map((p) => (
        <ProjectRow key={p.id} project={p} />
      ))}
    </div>
  )
}

export default function Projects() {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    getProjects()
      .then(setProjects)
      .catch((e: Error) => setError(e.message))
  }, [])

  return (
    <>
      <div className="head">
        <h1>Projects</h1>
        <Link to="/upload" className="btn">
          New project
        </Link>
      </div>
      {error && <div className="err" role="alert">{error}</div>}
      {!error && projects === null && <p className="muted">Looking at your projects...</p>}
      {projects !== null && <ProjectsList projects={projects} />}
    </>
  )
}
