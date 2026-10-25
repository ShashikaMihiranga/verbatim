// The theme editor's rules, as pure functions so the components only draw them (theme editor hand-off).
import type { ThemeCard } from './themesApi'

export const OTHER = 'Other'
export const SMALL_SHARE = 3 // the "Small" chip: under 3% of answers
export const SHARE_BAR_FULL = 12 // a 12% share fills the bar
export const NAME_BOLD_SHARE = 5 // names of themes with 5%+ of answers are set heavier

export type Chip = 'all' | 'small' | 'edited'
export type ColorToken = 't1' | 't2' | 't3' | 't4' | 't5' | 't6' | 't7' | 'other'

export const isOther = (t: ThemeCard) => t.label === OTHER

// Largest first; Other always last. Re-sorted after every edit, since the list is rebuilt from the server.
export function sortThemes(themes: ThemeCard[]): ThemeCard[] {
  return [...themes].sort((a, b) => Number(isOther(a)) - Number(isOther(b)) || b.size - a.size || a.label.localeCompare(b.label))
}

// Same rule as the charts (app/findings.py `_theme_color`): the 7 largest real themes get t1..t7.
export function colorTokens(themes: ThemeCard[]): Map<number, ColorToken> {
  const out = new Map<number, ColorToken>()
  sortThemes(themes).forEach((t) => out.set(t.id, 'other'))
  sortThemes(themes).filter((t) => !isOther(t)).slice(0, 7).forEach((t, i) => out.set(t.id, `t${i + 1}` as ColorToken))
  return out
}

export function visibleThemes(themes: ThemeCard[], query: string, chip: Chip, edited: Set<number>): ThemeCard[] {
  const q = query.trim().toLowerCase()
  return sortThemes(themes).filter((t) =>
    (!q || t.label.toLowerCase().includes(q))
    && (chip !== 'small' || t.size_pct < SMALL_SHARE)
    && (chip !== 'edited' || edited.has(t.id)))
}

export const shareBarWidth = (share: number) => Math.min(100, (share / SHARE_BAR_FULL) * 100)
export const formatTone = (s: number | null) => (s === null ? '–' : `${s >= 0 ? '+' : '-'}${Math.abs(s).toFixed(2)}`)
export const fmt = (n: number) => n.toLocaleString('en-US')

export interface Combined {
  answers: number
  share: number // % of all answers, one decimal
  tone: number | null // size-weighted, as the server's merge computes it
}

export function combine(themes: ThemeCard[], totalAnswers: number): Combined {
  const answers = themes.reduce((n, t) => n + t.size, 0)
  const scored = themes.filter((t) => t.sentiment !== null)
  const weight = scored.reduce((n, t) => n + t.size, 0)
  return {
    answers,
    share: totalAnswers ? Math.round((answers / totalAnswers) * 1000) / 10 : 0,
    tone: weight ? scored.reduce((n, t) => n + (t.sentiment as number) * t.size, 0) / weight : null,
  }
}

// The sticky selection bar's two lines (hand-off: 0, 1, 2+ selected).
export function selectionText(selected: ThemeCard[], totalAnswers: number): { title: string; detail: string; ready: boolean } {
  if (selected.length === 0) return { title: 'Nothing selected', detail: 'Tick two or more themes to merge them.', ready: false }
  if (selected.length === 1) return { title: '1 selected', detail: 'Pick at least one more to merge. Or use Split on a row.', ready: false }
  const c = combine(selected, totalAnswers)
  return { title: `${selected.length} selected`, detail: `${fmt(c.answers)} answers, ${c.share}% of all, would become one theme.`, ready: true }
}

// The merged theme's default name: the largest selected theme's.
export const largestName = (themes: ThemeCard[]) => [...themes].sort((a, b) => b.size - a.size)[0]?.label ?? ''
