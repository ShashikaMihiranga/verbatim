import { authFetch } from './authFetch'
import type { BuildStarted } from './jobsApi'

export interface ToneSplit {
  neg: number
  neu: number
  pos: number
}

export interface ThemeCard {
  id: number
  label: string
  description: string | null
  size: number
  size_pct: number
  sentiment: number | null
  tone: ToneSplit
  confidence: 'solid' | 'tentative'
}

export interface ThemesResponse {
  dataset_id: number
  column: string
  total_answers: number
  themes: ThemeCard[]
}

// Wire shape shared with app.api_report's report blocks (see reportApi.ts's ReportBlock) - both are
// app.charts.render_parts's own {chart_html, chart_width, chart_height} shape, so the frontend can reuse
// one fragment-rendering component (ThemeChart.tsx) for both the report page and this browse view.
export interface ThemeChartResponse {
  chart_html: string
  chart_width: number
  chart_height: number
}

export interface ThemeAnswer {
  row: number
  text: string
  tone: 'neg' | 'neu' | 'pos'
}

export interface ThemeAnswersResponse {
  theme_id: number
  total: number
  limit: number
  offset: number
  answers: ThemeAnswer[]
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

// Starts a themes build as a background job and returns immediately (202 `{job_id, status: "running"}`) -
// it does NOT wait for themes to exist. Any error thrown here is a cheap, instant check that failed before
// the job even started (ownership, unknown column, a missing embedding/Claude/Jev key, or the build being
// busy) - once a job has started, a failure (e.g. "too few answers") surfaces later as that job's own
// `error` field, polled via `app.jobsApi.pollJob`, not as a rejection of this call.
export async function buildThemes(id: number, column: string, useJevSentiment = false): Promise<BuildStarted> {
  const r = await authFetch(`/api/datasets/${id}/themes/build`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ column, use_jev_sentiment: useJevSentiment }),
  })
  if (!r.ok) throw await asError(r)
  return r.json()
}

export async function getThemes(id: number, column: string): Promise<ThemesResponse> {
  const r = await authFetch(`/api/datasets/${id}/themes?${new URLSearchParams({ column })}`)
  if (!r.ok) throw await asError(r)
  return r.json()
}

// One-chart-at-a-glance treemap fragment for a column's stored themes (app/api_themes.py's
// GET /themes/chart) - the Themes screen's browse view calls this instead of rendering one Card per theme.
export async function getThemesChart(id: number, column: string): Promise<ThemeChartResponse> {
  const r = await authFetch(`/api/datasets/${id}/themes/chart?${new URLSearchParams({ column })}`)
  if (!r.ok) throw await asError(r)
  return r.json()
}

export async function getThemeAnswers(
  id: number,
  themeId: number,
  limit = 20,
  offset = 0,
): Promise<ThemeAnswersResponse> {
  const q = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  const r = await authFetch(`/api/datasets/${id}/themes/${themeId}/answers?${q}`)
  if (!r.ok) throw await asError(r)
  return r.json()
}
