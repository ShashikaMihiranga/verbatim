import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { ReportBlock, ReportThemeChartVariant } from './reportApi'
import ThemeChartTabs from './ThemeChartTabs'

// Static-markup only (node environment, no jsdom - same precedent as other-exploration.test.tsx). Covers
// the initial render (useState's default `active = 'treemap'`) - switching tabs via a real click needs
// jsdom and is covered by this feature's browser verification pass instead, not here.

const OVERVIEW: ReportBlock = {
  kind: 'overview', chart_id: 'treemap', chart_title: 'Themes',
  chart_html: '<div data-theme="Reliability">Reliability treemap cell</div>',
  chart_width: 800, chart_height: 400, priority: 0, finding_id: null, finding: null,
}

const VARIANTS: Record<string, ReportThemeChartVariant> = {
  icicle: { chart_title: 'Icicle', chart_html: '<div>Reliability icicle</div>', chart_width: 800, chart_height: 400 },
  sentsun: { chart_title: 'Sentiment sun', chart_html: '<div>Reliability sun</div>', chart_width: 800, chart_height: 400 },
  rank: { chart_title: 'Rank', chart_html: '<div>Reliability rank</div>', chart_width: 800, chart_height: 400 },
}

describe('ThemeChartTabs', () => {
  it('renders just the treemap, no tab bar, when there are no variants (older cached report)', () => {
    const html = renderToStaticMarkup(<ThemeChartTabs overview={OVERVIEW} variants={{}} />)
    expect(html).toContain('Reliability treemap cell')
    expect(html).not.toContain('Icicle')
  })

  it('renders a tab for the treemap plus each available variant, defaulting to the treemap', () => {
    const html = renderToStaticMarkup(<ThemeChartTabs overview={OVERVIEW} variants={VARIANTS} />)
    expect(html).toContain('Known themes')
    expect(html).toContain('Icicle')
    expect(html).toContain('Sentiment sun')
    expect(html).toContain('Rank')
    expect(html).not.toContain('Arc')
    expect(html).not.toContain('Sankey')
    expect(html).toContain('Reliability treemap cell') // the default active tab's content
  })

  it('only lists tabs for variants actually present, even if some are missing', () => {
    const html = renderToStaticMarkup(<ThemeChartTabs overview={OVERVIEW} variants={{ rank: VARIANTS.rank }} />)
    expect(html).toContain('Rank')
    expect(html).not.toContain('Icicle')
    expect(html).not.toContain('Sentiment sun')
  })

  it('lists diverge/sunburst tabs when present (2026-10-24: reused as real variant tabs, see api_report.py)', () => {
    const html = renderToStaticMarkup(
      <ThemeChartTabs
        overview={OVERVIEW}
        variants={{
          diverge: { chart_title: 'Diverging sentiment', chart_html: '<div>Reliability diverge</div>', chart_width: 800, chart_height: 400 },
          sunburst: { chart_title: 'Themes, sunburst', chart_html: '<div>Reliability sunburst</div>', chart_width: 800, chart_height: 400 },
        }}
      />,
    )
    expect(html).toContain('Tone split')
    expect(html).toContain('Sunburst')
  })
})
