import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import OtherExploration from './OtherExploration'
import type { ReportOtherBreakdown, ReportThemeSummary } from './reportApi'

// Static-markup only (this repo's vitest config runs with `environment: 'node'`, no jsdom - same
// precedent as report-filters.test.tsx). `expanded` starts false (useState's initial render), so these
// tests cover the collapsed view and the "see all themes" toggle button appearing - not the expanded
// row list itself, which needs a real click to reveal; that interaction is covered by this feature's
// browser verification pass (docs/DECISIONS.md), not here.

const ABOVE_THRESHOLD: ReportOtherBreakdown = {
  noise_count: 19467, noise_share: 49.0,
  hidden_real_count: 11895, hidden_real_share: 29.9,
  hidden_real_theme_count: 75, total_real_theme_count: 82,
}
const BELOW_THRESHOLD: ReportOtherBreakdown = {
  noise_count: 100, noise_share: 10.0,
  hidden_real_count: 150, hidden_real_share: 15.0,
  hidden_real_theme_count: 3, total_real_theme_count: 10,
}
const THEMES: ReportThemeSummary[] = [
  { name: 'Console/brand loyalty talk', share: 3.9, count: 1975, sentiment: -0.1 },
  { name: 'General love for a game', share: 2.5, count: 1553, sentiment: 0.4 },
]

describe('OtherExploration', () => {
  it('renders nothing when there is no breakdown (nothing folded into Other)', () => {
    const html = renderToStaticMarkup(<OtherExploration breakdown={null} allThemes={[]} />)
    expect(html).toBe('')
  })

  it('renders nothing when Other is below the callout threshold', () => {
    const html = renderToStaticMarkup(<OtherExploration breakdown={BELOW_THRESHOLD} allThemes={THEMES} />)
    expect(html).toBe('')
  })

  it('renders the callout, the honest numbers, and the breakdown tiles once Other crosses the threshold', () => {
    const html = renderToStaticMarkup(<OtherExploration breakdown={ABOVE_THRESHOLD} allThemes={THEMES} />)
    expect(html).toContain("78.9") // 49.0 + 29.9
    expect(html).toContain('82 distinct topics')
    expect(html).toContain('7 theme') // shown = 82 - 75 = 7
    expect(html).toContain('49%')
    expect(html).toContain('Genuinely varied answers')
    expect(html).toContain('29.9%')
    expect(html).toContain('More real themes')
    expect(html).toContain('75 more topics')
  })

  it('shows the "see all themes" toggle with the real count, collapsed by default', () => {
    const html = renderToStaticMarkup(<OtherExploration breakdown={ABOVE_THRESHOLD} allThemes={THEMES} />)
    expect(html).toContain('See all 2 themes')
    expect(html).not.toContain('Console/brand loyalty talk') // the row list itself is not rendered yet
  })

  it('hides the toggle entirely when there are no real themes to list', () => {
    const html = renderToStaticMarkup(<OtherExploration breakdown={ABOVE_THRESHOLD} allThemes={[]} />)
    expect(html).not.toContain('See all')
  })
})
