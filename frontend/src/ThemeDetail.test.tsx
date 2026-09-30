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
    sub_themes: [],
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

  it('renders each sub-theme\'s label and rounded percentage, and the "Sub-themes" heading', () => {
    const html = renderToStaticMarkup(
      <ThemeDetail
        id={1}
        theme={theme({
          // size_pct is "% of all answered" for both a theme and its sub-themes (see app/api_themes.py's
          // _theme_dict) - a sub-theme's share can never exceed its own parent's, so the parent here is
          // bumped above the sub-themes' own sum (38.5 + 15.4) rather than left at the default 26.4.
          size_pct: 60,
          sub_themes: [
            {
              index: 0,
              label: 'Home charger cost',
              description: 'Installing a home charger is too expensive.',
              size: 100,
              size_pct: 38.5,
              sentiment: -0.3,
              tone: { neg: 70, neu: 20, pos: 10 },
            },
            {
              index: 1,
              label: 'Public charger reliability',
              description: null,
              size: 40,
              size_pct: 15.4,
              sentiment: -0.1,
              tone: { neg: 50, neu: 40, pos: 10 },
            },
          ],
        })}
      />,
    )
    expect(html).toContain('Sub-themes')
    expect(html).toContain('Home charger cost')
    expect(html).toContain('39%')
    expect(html).toContain('Installing a home charger is too expensive.')
    expect(html).toContain('Public charger reliability')
    expect(html).toContain('15%')
  })

  it('renders no "Sub-themes" heading or .th-subs markup when sub_themes is empty', () => {
    const html = renderToStaticMarkup(<ThemeDetail id={1} theme={theme({ sub_themes: [] })} />)
    expect(html).not.toContain('Sub-themes')
    expect(html).not.toContain('th-subs')
  })

  it('shows the "N% fit no sub-theme" line when sub-themes leave a real remainder', () => {
    // size_pct is "% of all answered" for both theme and sub-themes (not "% of this theme") - the
    // remainder is theme.size_pct minus the sub-themes' own sum, so the parent here (65) is deliberately
    // set above the sub-themes' sum (40 + 10 = 50), leaving a real remainder of 15.
    const html = renderToStaticMarkup(
      <ThemeDetail
        id={1}
        theme={theme({
          size_pct: 65,
          sub_themes: [
            { index: 0, label: 'A', description: null, size: 50, size_pct: 40, sentiment: 0, tone: { neg: 0, neu: 100, pos: 0 } },
            { index: 1, label: 'B', description: null, size: 12, size_pct: 10, sentiment: 0, tone: { neg: 0, neu: 100, pos: 0 } },
          ],
        })}
      />,
    )
    expect(html).toContain('th-subs-note')
    expect(html).toContain('15%')
    expect(html).toContain('fit no sub-theme')
  })

  it('omits the "N% fit no sub-theme" line when sub-themes cover all of the theme', () => {
    // Parent size_pct equals the sub-themes' own sum (60 + 40 = 100) - zero remainder, not "close to 100
    // in absolute terms" (a sub-theme's share can never exceed its own parent's, so a parent whose
    // size_pct is smaller than its sub-themes' sum can't happen with real data).
    const html = renderToStaticMarkup(
      <ThemeDetail
        id={1}
        theme={theme({
          size_pct: 100,
          sub_themes: [
            { index: 0, label: 'A', description: null, size: 60, size_pct: 60, sentiment: 0, tone: { neg: 0, neu: 100, pos: 0 } },
            { index: 1, label: 'B', description: null, size: 40, size_pct: 40, sentiment: 0, tone: { neg: 0, neu: 100, pos: 0 } },
          ],
        })}
      />,
    )
    expect(html).not.toContain('fit no sub-theme')
  })

  it('shows the correct small remainder for a small theme with a small sub-theme (the common real case)', () => {
    // The realistic shape: a theme is a modest slice of the whole dataset (8%), and its sub-themes are
    // smaller slices still (3%) - furthest from the old, wrong "sums near 100" fixtures above, and
    // exactly the shape that made the old 100-minus-sum formula wrong in production.
    const html = renderToStaticMarkup(
      <ThemeDetail
        id={1}
        theme={theme({
          size_pct: 8,
          sub_themes: [
            { index: 0, label: 'A', description: null, size: 30, size_pct: 3, sentiment: 0, tone: { neg: 0, neu: 100, pos: 0 } },
          ],
        })}
      />,
    )
    expect(html).toContain('5%')
    expect(html).toContain('fit no sub-theme')
  })
})
