import { authFetch } from './authFetch'

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

export async function buildThemes(id: number, column: string, useJevSentiment = false): Promise<ThemesResponse> {
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
