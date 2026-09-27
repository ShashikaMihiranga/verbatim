import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import ReportView from './Report'
import type { ReportBlock, ReportResponse } from './reportApi'

// `ReportView` is a pure presentational component (report data comes in as a prop, nothing is fetched
// inside it), so it renders safely with `renderToStaticMarkup` - same style as home/home.test.tsx and
// auth/auth.test.tsx, this repo's existing precedent for testing presentational components without a
// jsdom environment. `Themes.tsx` itself (the route this view is wired into) has no test file of its own
// yet and fetches data with hooks, which this style cannot exercise - see docs/DECISIONS.md for why no
// test was added for that data-fetching wrapper.
//
// Charts now arrive as raw body FRAGMENTS (app.charts.render_parts's shape - no `<!doctype html>`, no own
// background/font), embedded straight into the page via `dangerouslySetInnerHTML` rather than iframed as
// a full standalone document - see docs/DECISIONS.md for why that is safe specifically for this content
// (server-generated, esc()-escaped SVG/HTML, never raw user text).

const OVERVIEW: ReportBlock = {
  kind: 'overview', chart_id: 'overview', chart_title: 'Overview',
  chart_html: '<div style="padding:1px">OVERVIEW-MARK</div>', chart_width: 1180, chart_height: 680,
  priority: 1, finding_id: null, finding: null,
}
const QUALITY: ReportBlock = {
  kind: 'quality', chart_id: 'quality', chart_title: 'Answer quality',
  chart_html: '<div style="padding:1px">QUALITY-MARK</div>', chart_width: 1180, chart_height: 880,
  priority: 9, finding_id: null, finding: null,
}
const FINDING_RELIABILITY: ReportBlock = {
  kind: 'finding', chart_id: 'rank', chart_title: 'Rank themes',
  chart_html: '<div style="padding:1px">RELIABILITY-CHART-MARK</div>', chart_width: 1180, chart_height: 860,
  priority: 3, finding_id: 11,
  finding: { id: 11, theme_id: 5, sentence: 'Reliability carries the most negative wording.', confidence: 'solid' },
}
const FINDING_SUPPORT: ReportBlock = {
  kind: 'finding', chart_id: 'sentsun', chart_title: 'Sentiment sunburst',
  chart_html: '<div style="padding:1px">SUPPORT-CHART-MARK</div>', chart_width: 1180, chart_height: 800,
  priority: 4, finding_id: 12,
  finding: { id: 12, theme_id: 6, sentence: 'Support answers sound clearly more positive than average.', confidence: 'tentative' },
}

function makeReport(overrides: Partial<ReportResponse> = {}): ReportResponse {
  return {
    dataset_id: 1,
    column: 'Why',
    question: "Why haven't you bought an electric vehicle yet?",
    summary: '2 themes found, overall tone negative (-0.15).',
    also_checked_nothing_notable: false,
    blocks: [OVERVIEW, FINDING_RELIABILITY, FINDING_SUPPORT, QUALITY],
    ...overrides,
  }
}

describe('ReportView', () => {
  it('shows the question, the computed summary, the columns-used chip, and every block in priority order', () => {
    const html = renderToStaticMarkup(<ReportView report={makeReport()} datasetId={1} />)
    expect(html).toContain('bought an electric vehicle yet?')
    expect(html).toContain('2 themes found, overall tone negative')
    expect(html).toContain('Columns used')
    expect(html).toContain('Why')
    expect(html).toContain('open-ended text')
    expect(html.indexOf('OVERVIEW-MARK')).toBeLessThan(html.indexOf('RELIABILITY-CHART-MARK'))
    expect(html.indexOf('RELIABILITY-CHART-MARK')).toBeLessThan(html.indexOf('SUPPORT-CHART-MARK'))
    expect(html.indexOf('SUPPORT-CHART-MARK')).toBeLessThan(html.indexOf('QUALITY-MARK'))
  })

  it('lists every finding sentence up front in "What stands out", each with its badge', () => {
    const html = renderToStaticMarkup(<ReportView report={makeReport()} datasetId={1} />)
    expect(html).toContain('What stands out')
    const standoutStart = html.indexOf('What stands out')
    const standout = html.slice(standoutStart, standoutStart + 2000)
    expect(standout).toContain('Reliability carries the most negative wording.')
    expect(standout).toContain('Support answers sound clearly more positive than average.')
    expect(standout).toContain('Solid')
    expect(standout).toContain('Tentative')
    // the summary list appears before the detailed story blocks below it
    expect(html.indexOf('What stands out')).toBeLessThan(html.indexOf('RELIABILITY-CHART-MARK'))
  })

  it('shows a Solid or Tentative badge on each finding block', () => {
    const html = renderToStaticMarkup(<ReportView report={makeReport()} datasetId={1} />)
    expect(html).toContain('Solid')
    expect(html).toContain('Tentative')
  })

  it('embeds each chart fragment directly into the page, never as a full standalone document or an iframe', () => {
    const html = renderToStaticMarkup(<ReportView report={makeReport()} datasetId={1} />)
    expect(html).not.toContain('<iframe')
    expect(html).not.toContain('sandbox=')
    expect(html).not.toContain('<!doctype html>')
    expect(html).not.toContain('<!DOCTYPE html>')
    expect(html).toContain('OVERVIEW-MARK')
    expect(html).toContain('RELIABILITY-CHART-MARK')
    expect(html).toContain('QUALITY-MARK')
  })

  it('shows "Also checked, nothing notable" instead of forcing empty finding blocks', () => {
    const report = makeReport({ also_checked_nothing_notable: true, blocks: [OVERVIEW, QUALITY] })
    const html = renderToStaticMarkup(<ReportView report={report} datasetId={1} />)
    expect(html).toContain('Also checked, nothing notable')
    expect(html).not.toContain('rp-standout')
  })

  it('shows no exact record counts anywhere in the summary line', () => {
    const html = renderToStaticMarkup(<ReportView report={makeReport()} datasetId={1} />)
    expect(html).not.toMatch(/\b\d{2,3},\d{3}\b|\b\d{4,6} (responses|answers|rows)\b/i)
  })
})
