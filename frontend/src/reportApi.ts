import { authFetch } from './authFetch'
import type { BuildStarted } from './jobsApi'

export interface ReportFinding {
  id: number
  theme_id: number | null
  sentence: string
  confidence: 'solid' | 'tentative'
}

export interface ReportBlock {
  kind: 'overview' | 'finding' | 'quality'
  chart_id: string
  chart_title: string
  chart_html: string
  priority: number
  finding_id: number | null
  finding: ReportFinding | null
}

export interface ReportResponse {
  dataset_id: number
  column: string
  question: string
  summary: string
  also_checked_nothing_notable: boolean
  blocks: ReportBlock[]
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

// Starts a report build as a background job and returns immediately (202 `{job_id, status: "running"}`) -
// see app/themesApi.ts's `buildThemes` for why: only cheap/instant checks (ownership, missing Claude key)
// throw here now; "no themes yet" surfaces later as the job's own `error`.
export async function buildReport(id: number, column: string): Promise<BuildStarted> {
  const r = await authFetch(`/api/datasets/${id}/report/build`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ column }),
  })
  if (!r.ok) throw await asError(r)
  return r.json()
}

export async function getReport(id: number, column: string): Promise<ReportResponse> {
  const r = await authFetch(`/api/datasets/${id}/report?${new URLSearchParams({ column })}`)
  if (!r.ok) throw await asError(r)
  return r.json()
}
