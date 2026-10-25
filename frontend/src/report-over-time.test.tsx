import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import ReportView from './Report'
import type { ReportResponse } from './reportApi'

const base = {
  dataset_id: 1, column: 'Why', question: 'Q', summary: '', also_checked_nothing_notable: false, blocks: [],
  columns_used: [], filter_options: { segment: null, score_band: null, date_range: null },
  filters_applied: {}, other_breakdown: null, all_themes: [],
} as unknown as ReportResponse

describe('report over time section (T1)', () => {
  it('shows the themes-over-time chart with an outline link when the column has periods', () => {
    const over = { chart_title: 'Themes over time', chart_html: '<div>OVER-TIME-PANELS</div>', chart_width: 1180, chart_height: 540 }
    const html = renderToStaticMarkup(<ReportView datasetId={1} report={{ ...base, theme_chart_variants: { themesOverTime: over } }} />)
    expect(html).toContain('OVER-TIME-PANELS')
    expect(html).toContain('id="report-time"')
    expect(html).toContain('href="#report-time"')
  })

  it('leaves the section out without periods', () => {
    const html = renderToStaticMarkup(<ReportView datasetId={1} report={{ ...base, theme_chart_variants: {} }} />)
    expect(html).not.toContain('report-time')
  })
})
