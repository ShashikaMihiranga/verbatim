// The theme editor's own endpoints (app/api_themes.py, "theme editor previews"). Previews commit nothing.
import { authFetch } from './authFetch'
import { asError, type ThemeCard, type ToneSplit } from './themesApi'

export interface MergePreview {
  answers: number
  share: number
  tone: ToneSplit
  sentiment: number | null
  sub_themes: number // sub-themes the merged theme keeps
  label: string // the largest theme's name, the default
  themes: Array<{ id: number; label: string; size: number; samples: string[] }>
}

export interface SplitPart {
  label: string
  answers: number
  share: number
  keeps_theme: boolean // the rest stays as the original theme, with its name
  sample: string | null
}

export interface SplitPreview {
  theme_id: number
  label: string
  size: number
  share: number
  sub_themes: number
  by_wording: boolean // no sub-themes: a background job re-reads the answers; parts unknown in advance
  choices: number[]
  parts_chosen?: number
  parts: SplitPart[]
}

async function post<T>(url: string, body: unknown): Promise<T> {
  const r = await authFetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!r.ok) throw await asError(r)
  return r.json()
}

export const mergePreview = (id: number, column: string, themeIds: number[]) =>
  post<MergePreview>(`/api/datasets/${id}/themes/merge-preview`, { column, theme_ids: themeIds })

export const splitPreview = (id: number, themeId: number, parts?: number) =>
  post<SplitPreview>(`/api/datasets/${id}/themes/${themeId}/split-preview`, parts ? { parts } : {})

export const splitSubThemes = (id: number, themeId: number, parts: number) =>
  post<{ theme: ThemeCard; new_themes: ThemeCard[] }>(`/api/datasets/${id}/themes/${themeId}/split-sub-themes`, { parts })
