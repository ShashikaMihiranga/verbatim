import { describe, expect, it } from 'vitest'
import { colorTokens, combine, formatTone, largestName, selectionText, shareBarWidth, sortThemes, visibleThemes } from './themeEditorModel'
import type { ThemeCard } from './themesApi'

const t = (id: number, label: string, size: number, sentiment: number | null = 0): ThemeCard => ({
  id, label, description: null, size, size_pct: size / 10, sentiment,
  tone: { neg: 0, neu: 100, pos: 0 } as ThemeCard['tone'], confidence: 'solid', sub_themes: [],
})
const THEMES = [t(1, 'Noise', 120, -0.5), t(2, 'Other', 400), t(3, 'Desks', 20, 0.2), t(4, 'Light', 60), t(5, 'Air', 25)]

describe('theme editor model', () => {
  it('sorts by size, Other always last', () => {
    expect(sortThemes(THEMES).map((x) => x.label)).toEqual(['Noise', 'Light', 'Air', 'Desks', 'Other'])
  })

  it('colours the 7 largest real themes t1..t7, the rest and Other "other"', () => {
    const many = Array.from({ length: 9 }, (_, i) => t(i + 1, `T${i}`, 100 - i)).concat(t(99, 'Other', 1000))
    const c = colorTokens(many)
    expect([1, 2, 7].map((id) => c.get(id))).toEqual(['t1', 't2', 't7'])
    expect([8, 9, 99].map((id) => c.get(id))).toEqual(['other', 'other', 'other'])
  })

  it('filters by name and by chip', () => {
    expect(visibleThemes(THEMES, 'IR', 'all', new Set()).map((x) => x.label)).toEqual(['Air'])
    expect(visibleThemes(THEMES, '', 'small', new Set()).map((x) => x.label)).toEqual(['Air', 'Desks']) // under 3%
    expect(visibleThemes(THEMES, '', 'edited', new Set([4])).map((x) => x.label)).toEqual(['Light'])
  })

  it('says what the selection would become', () => {
    expect(selectionText([], 625)).toMatchObject({ title: 'Nothing selected', ready: false })
    expect(selectionText([THEMES[0]], 625)).toMatchObject({ title: '1 selected', ready: false })
    const two = selectionText([THEMES[0], THEMES[2]], 625)
    expect(two).toEqual({ title: '2 selected', detail: '140 answers, 22.4% of all, would become one theme.', ready: true })
  })

  it('combines tone weighted by size, like the server', () => {
    expect(combine([THEMES[0], THEMES[2]], 625).tone).toBeCloseTo((-0.5 * 120 + 0.2 * 20) / 140)
    expect(combine([t(1, 'A', 5, null)], 10).tone).toBeNull()
  })

  it('formats tone, share bars and the default merge name', () => {
    expect(formatTone(-0.341)).toBe('-0.34')
    expect(formatTone(0.2)).toBe('+0.20')
    expect(shareBarWidth(6)).toBe(50)
    expect(shareBarWidth(30)).toBe(100)
    expect(largestName([THEMES[2], THEMES[0]])).toBe('Noise')
  })
})
