import { authFetch } from './authFetch'

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

export async function buildReport(id: number, column: string): Promise<ReportResponse> {
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
