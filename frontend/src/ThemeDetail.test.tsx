import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import ThemeDetail from './ThemeDetail'
import type { ThemeCard } from './themesApi'

// `ThemeDetail` is a pure presentational component for one already-fetched `ThemeCard` (the "See answers"
// drill-down fetches lazily, only once clicked - not exercised here), so it renders safely with
// `renderToStaticMarkup` - the same style this repo's other component tests use (see report.test.tsx's own
// comment on why, given vitest's `environment: 'node'` default).

function theme(overrides: Partial<ThemeCard> = {}): ThemeCard {
  return {
    id: 42,
    label: 'Charging',
    description: 'No home charger and too few public chargers.',
    size: 260,
    size_pct: 26.4,
    sentiment: -0.2,
    tone: { neg: 60, neu: 30, pos: 10 },
    confidence: 'solid',
    ...overrides,
  }
}

describe('ThemeDetail', () => {
  it('shows the theme label, description, size and confidence badge', () => {
    const html = renderToStaticMarkup(<ThemeDetail id={1} theme={theme()} />)
    expect(html).toContain('Charging')
    expect(html).toContain('No home charger and too few public chargers.')
    expect(html).toContain('26%')
    expect(html).toContain('of answers')
    expect(html).toContain('Solid')
  })

  it('shows a Tentative badge for a tentative theme, not Solid', () => {
    const html = renderToStaticMarkup(<ThemeDetail id={1} theme={theme({ confidence: 'tentative' })} />)
    expect(html).toContain('Tentative')
    expect(html).not.toContain('>Solid<')
  })

  it('renders the tone split as negative/neutral/positive percentages', () => {
    const html = renderToStaticMarkup(<ThemeDetail id={1} theme={theme({ tone: { neg: 60, neu: 30, pos: 10 } })} />)
    expect(html).toContain('60% negative')
    expect(html).toContain('30% neutral')
    expect(html).toContain('10% positive')
  })

  it('shows the "See answers" toggle, not an already-open answer list', () => {
    const html = renderToStaticMarkup(<ThemeDetail id={1} theme={theme()} />)
    expect(html).toContain('See answers')
    expect(html).not.toContain('th-answers')
  })

  it('shows a different theme\'s own content when given a different ThemeCard', () => {
    const html = renderToStaticMarkup(
      <ThemeDetail id={1} theme={theme({ label: 'Range and battery', description: 'Range anxiety.', size_pct: 16 })} />,
    )
    expect(html).toContain('Range and battery')
    expect(html).toContain('Range anxiety.')
    expect(html).toContain('16%')
    expect(html).not.toContain('Charging')
  })

  it('omits the description block entirely when there is none', () => {
    const html = renderToStaticMarkup(<ThemeDetail id={1} theme={theme({ description: null })} />)
    expect(html).not.toContain('th-desc')
  })
})
