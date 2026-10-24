import { authFetch } from './authFetch'
import type { BuildStarted } from './jobsApi'

export interface ReportFinding {
  id: number
  theme_id: number | null
  sentence: string
  confidence: 'solid' | 'tentative'
}

export interface ReportBlock {
  // 'context'/'quotes'/'phrases' (chart-block stream, 2026-10-24, wiring batch A): always-on supplements,
  // not competing findings - shown whenever their own data exists, with no Badge/"see answers" (those are
  // finding-only). See Report.tsx's SupplementBlock.
  kind: 'overview' | 'finding' | 'quality' | 'context' | 'quotes' | 'phrases'
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
  chart_variants?: Record<string, ReportThemeChartVariant>
  compact_chart_id?: string
}

// One chip per column this report actually used - the report's own open-text column first (role
// "open-ended text"), then only whichever of score/segment/date columns actually survived suppression and
// produced real chart data (never one merely confirmed but unused). See docs/DECISIONS.md's 2026-09-28
// "honest 'Columns used' chip row" entry, which this fulfils.
export interface ReportColumnUsed {
  name: string
  role: string
}

// Filters feature (SPEC.md section 5: "a global filter (segment, score band, date range)"). Each field is
// `null` when that role never resolved to a real chart-worthy column, exactly mirroring `ReportColumnUsed`'s
// own honesty rule - a dropdown only ever offers values that already survived suppression server-side.
export interface ReportFilterOptions {
  segment: { column: string; groups: string[] } | null
  score_band: { column: string; bands: string[] } | null
  date_range: { column: string; min: string; max: string } | null
}

export interface ReportFiltersApplied {
  segment: string | null
  score_band: string | null
  date_from: string | null
  date_to: string | null
}

// "Other" exploration (docs/TODO.md, 2026-10-21 Phase 1). `null` when there is nothing genuinely folded
// into "Other" to explain - no noise cluster and no real theme ranked 8th+, the common case for most
// datasets - the frontend's callout/breakdown tiles render nothing in that case.
export interface ReportOtherBreakdown {
  noise_count: number
  noise_share: number
  hidden_real_count: number
  hidden_real_share: number
  hidden_real_theme_count: number
  total_real_theme_count: number
}

// One row of the full, UNCAPPED theme list - every real theme, not just the 7 the treemap can give its
// own colour to. Always present (possibly empty), independent of whether other_breakdown is null.
export interface ReportThemeSummary {
  name: string
  share: number
  count: number
  sentiment: number
}

// Chart-type switcher (docs/TODO.md, 2026-10-21 Stage 2): alternate views of the SAME theme data the
// treemap's overview block already shows, rendered server-side from the one already-built report_data.
// Keyed by chart id ("icicle" | "sentsun" | "rank") - deliberately no "arc" or "sankey" key; see
// app/api_report.py's own comment for why those two are excluded from this feature.
export interface ReportThemeChartVariant {
  chart_id?: string
  chart_label?: string
  chart_note?: string
  compact_chart_id?: string
  chart_title: string
  chart_html: string
  chart_width: number
  chart_height: number
}

// What a caller passes to `getReport` - camelCase on this side, translated to the API's own snake_case
// query params inside `getReport` below.
export interface ReportFilters {
  segment?: string
  scoreBand?: string
  dateFrom?: string
  dateTo?: string
}

export interface ReportResponse {
  explorations?: ReportThemeChartVariant[]
  dataset_id: number
  column: string
  question: string
  summary: string
  also_checked_nothing_notable: boolean
  blocks: ReportBlock[]
  columns_used: ReportColumnUsed[]
  filter_options: ReportFilterOptions
  filters_applied: ReportFiltersApplied
  other_breakdown: ReportOtherBreakdown | null
  all_themes: ReportThemeSummary[]
  theme_chart_variants: Record<string, ReportThemeChartVariant>
}

// Export (docs/TODO.md, fixed 2026-10-22). PNG/PPTX/PDF only - see app/export.py's own module docstring
// for why SVG is deliberately not offered (this pipeline's charts are a genuine SVG+HTML hybrid, so
// extracting just the <svg> part would silently drop every HTML label next to it).
export type ExportFormat = 'png' | 'pptx' | 'pdf'

export async function exportReport(id: number, column: string, format: ExportFormat): Promise<Blob> {
  const params = new URLSearchParams({ column, format })
  const r = await authFetch(`/api/datasets/${id}/report/export?${params}`)
  if (!r.ok) throw await asError(r)
  return r.blob()
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

export async function getReport(id: number, column: string, filters?: ReportFilters): Promise<ReportResponse> {
  const params = new URLSearchParams({ column })
  if (filters?.segment) params.set('segment', filters.segment)
  if (filters?.scoreBand) params.set('score_band', filters.scoreBand)
  if (filters?.dateFrom) params.set('date_from', filters.dateFrom)
  if (filters?.dateTo) params.set('date_to', filters.dateTo)
  const r = await authFetch(`/api/datasets/${id}/report?${params}`)
  if (!r.ok) throw await asError(r)
  return r.json()
}
