// The theme editor's own endpoints (app/api_themes.py, "theme editor previews"). Previews commit nothing.
import { authFetch } from './authFetch'
import { asError, type Edited, type ThemeCard, type ToneSplit } from './themesApi'

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
  post<Edited<{ theme: ThemeCard; new_themes: ThemeCard[] }>>(`/api/datasets/${id}/themes/${themeId}/split-sub-themes`, { parts })

export const promoteSubTheme = (id: number, themeId: number, index: number) =>
  post<Edited<{ theme: ThemeCard; new_theme: ThemeCard }>>(`/api/datasets/${id}/themes/${themeId}/sub-themes/${index}/promote`, {})

export const undoEdit = (id: number, column: string, token: number) =>
  post<{ undone: ThemeEditEntry }>(`/api/datasets/${id}/themes/undo`, { column, undo_token: token })

// "Your edits": the undoable edits, newest first.
export interface ThemeEditEntry {
  id: number
  undo_token: number
  kind: 'rename' | 'merge' | 'merge_batch' | 'split' | 'promote'
  summary: string
  created_at: string | null
}

export async function listEdits(id: number, column: string): Promise<ThemeEditEntry[]> {
  const r = await authFetch(`/api/datasets/${id}/themes/edits?${new URLSearchParams({ column })}`)
  if (!r.ok) throw await asError(r)
  return (await r.json()).edits
}

// ---- Grouping with Claude (ThemeGrouping_UIHandoff.md)
export interface GroupMember {
  id: number
  label: string
  size: number
  share: number
  samples: string[] // masked, as sent to Claude
}

export interface GroupSuggestion {
  id: string
  name: string
  member_ids: number[]
  confidence: number // 0-100, as Claude gave it
  band: 'High' | 'Medium' | 'Low' // High drops to Medium when the themes' answers are not close in meaning
  similarity: number | null // lowest centroid similarity in the group; null when not stored
  reason: string
  share: number
  members: GroupMember[]
}

export interface GroupingResult {
  groups: GroupSuggestion[]
  kept_apart: Array<{ names: string[]; reason: string }>
  dropped: number // proposals that failed validation
  cached: boolean // same themes as last time: no new Claude call
  themes: number
  words: number
}

export interface GroupingPayload {
  payload: { themes: Array<{ id: number; name: string; answers: number; share: number; samples: string[] }> }
  themes: number
  words: number
}

export async function getGroupPayload(id: number, column: string): Promise<GroupingPayload> {
  const r = await authFetch(`/api/datasets/${id}/themes/group-payload?${new URLSearchParams({ column })}`)
  if (!r.ok) throw await asError(r)
  return r.json()
}

export const startGrouping = (id: number, column: string) =>
  post<{ job_id: number }>(`/api/datasets/${id}/themes/group-suggestions`, { column })

export const mergeBatch = (id: number, column: string, groups: Array<{ name: string; theme_ids: number[] }>) =>
  post<Edited<{ themes: ThemeCard[] }>>(`/api/datasets/${id}/themes/merge-batch`, { column, groups })
