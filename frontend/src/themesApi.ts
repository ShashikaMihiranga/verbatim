import { authFetch } from './authFetch'
import type { BuildStarted } from './jobsApi'

export interface ToneSplit {
  neg: number
  neu: number
  pos: number
}

// One of a theme's up to 3 largest sub-clusters (app/api_themes.py::_theme_dict's `sub_themes` field) - a
// second, nested clustering pass within that theme's own answers. Never carries `answer_refs`; those are
// drill-down only, via getThemeAnswers's `subIndex` param. No `color` field - sub-theme colors aren't a
// concept this API exposes (see ThemeCard's own comment).
export interface SubThemeCard {
  index: number
  label: string
  description: string | null
  size: number
  size_pct: number
  sentiment: number | null
  tone: ToneSplit
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
  // 0-3 entries, largest first, `[]` for most themes (needs >=100 answers, top 7 by size, and to pass
  // coverage/count gates - see app/text_pipeline/subthemes.py). No `color` field - see SubThemeCard above.
  sub_themes: SubThemeCard[]
}

export interface ThemesResponse {
  dataset_id: number
  column: string
  total_answers: number
  themes: ThemeCard[]
  // The caller's role on this dataset: the theme editor shows edit controls to owners and editors only.
  role?: 'owner' | 'editor' | 'viewer' | null
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
  // Sharing/roles (docs/TODO.md, fixed 2026-10-22): `null` for a "viewer"-role collaborator - the real
  // text is deliberately withheld server-side (app/api_themes.py's own `_answers_page`), not redacted.
  text: string | null
  tone: 'neg' | 'neu' | 'pos'
}

export interface ThemeAnswersResponse {
  theme_id: number
  total: number
  limit: number
  offset: number
  answers: ThemeAnswer[]
  // Only set when these answers came from the sub-theme answers route (GET .../sub-themes/{index}/answers) -
  // see getThemeAnswers's `subIndex` param below.
  sub_theme_index?: number
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

// "Look inside Other" (docs/TODO.md, 2026-10-21 Stage 1+3): same shape as buildThemes above - a 202
// `{job_id, status: "running"}` returned immediately, any real failure surfacing later as that job's own
// `error` via pollJob, never as a rejection here (except the cheap, instant checks: ownership, unknown
// column, no "Other" theme to look inside, or an empty one - see app/api_themes.py's own route).
export async function lookInsideOther(id: number, column: string): Promise<BuildStarted> {
  const r = await authFetch(`/api/datasets/${id}/themes/look-inside-other`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ column }),
  })
  if (!r.ok) throw await asError(r)
  return r.json()
}

// Theme editing (docs/TODO.md, fixed 2026-10-22): rename is synchronous (no background job - nothing
// here re-embeds or re-clusters anything), returns the updated ThemeCard directly. Also invalidates any
// already-built report for this column server-side (see app/api_themes.py's own comment) - a caller
// should re-fetch/rebuild the report after this, not assume it is still valid.
export async function renameTheme(id: number, themeId: number, label: string, description?: string | null): Promise<ThemeCard> {
  const r = await authFetch(`/api/datasets/${id}/themes/${themeId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ label, description: description ?? null }),
  })
  if (!r.ok) throw await asError(r)
  return r.json()
}

// Theme editing: merges 2+ themes into the largest one (the survivor), returning its updated ThemeCard.
// `label` overrides the survivor's own label when given; omitted/undefined keeps it. Also invalidates
// any already-built report for this column, same as renameTheme above.
export async function mergeThemes(id: number, column: string, themeIds: number[], label?: string): Promise<ThemeCard> {
  const r = await authFetch(`/api/datasets/${id}/themes/merge`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ column, theme_ids: themeIds, label: label ?? null }),
  })
  if (!r.ok) throw await asError(r)
  return r.json()
}

// Theme editing: re-embeds and re-clusters one theme's own answers in a background job (same 202
// `{job_id, status: "running"}` shape as buildThemes/lookInsideOther above) - the real resulting pieces
// land in that job's own `result` (SplitThemeResult), polled via pollJob, never a rejection here except
// the cheap/instant checks (ownership, unknown theme, too few answers to split meaningfully).
export async function splitTheme(id: number, themeId: number): Promise<BuildStarted> {
  const r = await authFetch(`/api/datasets/${id}/themes/${themeId}/split`, { method: 'POST' })
  if (!r.ok) throw await asError(r)
  return r.json()
}

export async function getThemes(id: number, column: string): Promise<ThemesResponse> {
  const r = await authFetch(`/api/datasets/${id}/themes?${new URLSearchParams({ column })}`)
  if (!r.ok) throw await asError(r)
  return r.json()
}

// Every theme's answers on one map (app/api_themes.py GET /themes/answer-map): a sample of positions
// stored at theme build, each dot's group is the theme its answer is in now. x/y in 0..1, y down.
export interface AnswerMapResponse {
  answers: number
  // "umap": laid out by meaning. "pca": an older build, every theme overlapping. null: no positions stored.
  layout: 'umap' | 'pca' | null
  groups: Array<{ label: string; other: boolean }>
  points: Array<[number, number, number]>
}

export async function getAnswerMap(id: number, column: string): Promise<AnswerMapResponse> {
  const r = await authFetch(`/api/datasets/${id}/themes/answer-map?${new URLSearchParams({ column })}`)
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

// `subIndex` given hits the sub-theme answers route instead of the theme's own (app/api_themes.py's
// GET .../sub-themes/{index}/answers) - same shape as the theme's own route, plus `sub_theme_index`.
export async function getThemeAnswers(
  id: number,
  themeId: number,
  limit = 20,
  offset = 0,
  subIndex?: number,
): Promise<ThemeAnswersResponse> {
  const q = new URLSearchParams({ limit: String(limit), offset: String(offset) })
  const path =
    subIndex === undefined
      ? `/api/datasets/${id}/themes/${themeId}/answers?${q}`
      : `/api/datasets/${id}/themes/${themeId}/sub-themes/${subIndex}/answers?${q}`
  const r = await authFetch(path)
  if (!r.ok) throw await asError(r)
  return r.json()
}
