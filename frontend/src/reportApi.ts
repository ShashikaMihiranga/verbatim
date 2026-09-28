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
  // Raw body fragment (app.charts.render_parts's shape: no <!doctype html>, no own background/font load) -
  // meant to be embedded straight into this page's own DOM, sized by its own chart_width/chart_height
  // rather than a hardcoded guess. See Report.tsx's ChartFragment for why embedding it is safe here.
  chart_html: string
  chart_width: number
  chart_height: number
  priority: number
  finding_id: number | null
  finding: ReportFinding | null
}

// One chip per column this report actually used - the report's own open-text column first (role
// "open-ended text"), then only whichever of score/segment/date columns actually survived suppression and
// produced real chart data (never one merely confirmed but unused). See docs/DECISIONS.md's 2026-09-28
// "honest 'Columns used' chip row" entry, which this fulfils.
export interface ReportColumnUsed {
  name: string
  role: string
}

export interface ReportResponse {
  dataset_id: number
  column: string
  question: string
  summary: string
  also_checked_nothing_notable: boolean
  blocks: ReportBlock[]
  columns_used: ReportColumnUsed[]
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
