import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { deleteProject, getProjects, linkFor } from './projectsApi'
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
  'finding themes': 'Finding themes',
  'themes built': 'Themes built',
  'report ready': 'Report ready',
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

// `onDelete` is a plain callback, not a fetch call made here - Delete is a `<button>` sitting OUTSIDE the
// row's own `<Link>` (a sibling, not nested inside it) so clicking it never also triggers navigation; the
// stateful confirm-then-call-the-API logic lives in the default export below, matching this file's
// existing split (ProjectsList/ProjectRow stay pure/presentational, Projects owns state and effects).
export function ProjectRow({
  project,
  onDelete,
}: {
  project: ProjectSummary
  onDelete: (project: ProjectSummary) => void
}) {
  const title = project.question || project.filename
  return (
    <div className="pr-row">
      <Link to={linkFor(project)} className="pr-link">
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
      <button type="button" className="pr-delete" aria-label={`Delete ${title}`} onClick={() => onDelete(project)}>
        Delete
      </button>
    </div>
  )
}

export function ProjectsList({
  projects,
  onDelete,
}: {
  projects: ProjectSummary[]
  onDelete: (project: ProjectSummary) => void
}) {
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
        <ProjectRow key={p.id} project={p} onDelete={onDelete} />
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

  // Confirms (native dialog - this is a permanent delete, per DELETE /api/datasets/{id}'s own docstring:
  // "deletes one dataset and its Column/Theme/Finding/Report rows"), then removes the row from local state
  // on success rather than a full re-fetch - one fewer round trip, and getProjects() would return the same
  // list minus this row anyway.
  function handleDelete(project: ProjectSummary) {
    const title = project.question || project.filename
    const ok = window.confirm(
      `Delete "${title}"? This permanently removes the upload, its cleaning, themes and report so you can re-upload and try again. This cannot be undone.`,
    )
    if (!ok) return
    deleteProject(project.id)
      .then(() => setProjects((prev) => (prev ?? []).filter((p) => p.id !== project.id)))
      .catch((e: Error) => setError(e.message))
  }

  return (
    <>
      <div className="head">
        <h1>Projects</h1>
        <Link to="/upload" className="btn">
          New project
        </Link>
      </div>
      {error && (
        <div className="err" role="alert">
          {error}
        </div>
      )}
      {!error && projects === null && <p className="muted">Looking at your projects...</p>}
      {projects !== null && <ProjectsList projects={projects} onDelete={handleDelete} />}
    </>
  )
}
