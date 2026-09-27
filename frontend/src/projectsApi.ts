import { authFetch } from './authFetch'

export type ProjectStatus = 'uploaded' | 'columns confirmed' | 'cleaned' | 'themes built' | 'report ready'

export interface ProjectSummary {
  id: number
  filename: string
  question: string | null
  row_count: number
  created_at: string
  status: ProjectStatus
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

export async function getProjects(): Promise<ProjectSummary[]> {
  const r = await authFetch('/api/projects')
  if (!r.ok) throw await asError(r)
  return r.json()
}

export async function deleteProject(id: number): Promise<void> {
  const r = await authFetch(`/api/datasets/${id}`, { method: 'DELETE' })
  if (!r.ok) throw await asError(r)
}
