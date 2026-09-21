import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import Landing from './Landing'
import { QUOTES, THEMES } from './data'

const html = () => renderToStaticMarkup(<MemoryRouter><Landing /></MemoryRouter>)

describe('Landing', () => {
  it('has one h1 and the sign-up and sign-in links', () => {
    const h = html()
    expect(h.match(/<h1/g)).toHaveLength(1)
    expect(h).toContain('href="/sign-up"')
    expect(h).toContain('href="/sign-in"')
  })
  it('prints every theme with its number in the legend', () => {
    const h = html()
    for (const t of THEMES) expect(h).toContain(`${t.pct}%`)
  })
  it('shows no record counts and no exact totals', () => {
    expect(html()).not.toMatch(/\b\d{2,3},\d{3}\b|\b\d{4,6} (responses|answers|rows)/i)
  })
  it('example data is consistent', () => {
    expect(THEMES.reduce((s, t) => s + t.pct, 0)).toBe(100)
    for (const q of QUOTES) expect(THEMES[q.theme]).toBeDefined()
    for (const t of THEMES) if (t.subs.length) expect(Math.round(t.subs.reduce((s, x) => s + x.pct, 0))).toBe(t.pct)
    for (const t of THEMES) expect(t.tone.reduce((a, b) => a + b, 0)).toBe(100)
  })
})
