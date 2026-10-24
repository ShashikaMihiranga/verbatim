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
    // The real backend fixture (tests/test_api_report.py) has no confirmed score/segment/date column yet,
    // so this is the honest single-chip default every other test below implicitly exercises too - see
    // the dedicated multi-chip test for the richer case.
    columns_used: [{ name: 'Why', role: 'open-ended text' }],
    // Filters feature (SPEC.md section 5): the honest "nothing confirmed" default, matching columns_used
    // above - see report-filters.test.tsx for the richer case with real option values.
    filter_options: { segment: null, score_band: null, date_range: null },
    filters_applied: { segment: null, score_band: null, date_from: null, date_to: null },
    // The honest "no Other breakdown" default - see the page-order test below and inside-other.test.tsx
    // for the richer case.
    other_breakdown: null,
    all_themes: [],
    // No overview variants - see the page-order test below and medium-charts.test.tsx for icicle/diverge.
    theme_chart_variants: {},
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

  it('shows a chip per column actually used, each with its own role note', () => {
    const report = makeReport({
      columns_used: [
        { name: 'Why', role: 'open-ended text' },
        { name: 'Likelihood to buy', role: 'score' },
        { name: 'Age group', role: 'segment' },
        { name: 'Survey date', role: 'date' },
      ],
    })
    const html = renderToStaticMarkup(<ReportView report={report} datasetId={1} />)
    const chipsStart = html.indexOf('Columns used')
    const chips = html.slice(chipsStart, chipsStart + 2000)
    expect(chips).toContain('Why')
    expect(chips).toContain('open-ended text')
    expect(chips).toContain('Likelihood to buy')
    expect(chips).toContain('score')
    expect(chips).toContain('Age group')
    expect(chips).toContain('segment')
    expect(chips).toContain('Survey date')
    expect(chips).toContain('date')
    expect((chips.match(/rp-chip/g) ?? []).length).toBeGreaterThanOrEqual(4)
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

  it('places the filter bar after the "Columns used" chips and before "What stands out"', () => {
    const report = makeReport({
      filter_options: { segment: { column: 'Region', groups: ['North', 'South'] }, score_band: null, date_range: null },
    })
    const html = renderToStaticMarkup(
      <ReportView report={report} datasetId={1} filters={{}} onFiltersChange={() => {}} />,
    )
    const chipsIdx = html.indexOf('Columns used')
    const filterIdx = html.indexOf('rp-filters')
    const standoutIdx = html.indexOf('What stands out')
    expect(chipsIdx).toBeLessThan(filterIdx)
    expect(filterIdx).toBeLessThan(standoutIdx)
  })

  it('renders no filter bar when onFiltersChange is not provided (no-filter-state caller)', () => {
    const html = renderToStaticMarkup(<ReportView report={makeReport()} datasetId={1} />)
    expect(html).not.toContain('rp-filters')
  })

  it('page order: chips and filters, treemap, Inside Other, tone split, findings, quality', () => {
    const fragment = (mark: string) => ({ chart_id: mark, chart_title: mark, chart_html: `<div>${mark}</div>`, chart_width: 1180, chart_height: 400 })
    const html = renderToStaticMarkup(
      <ReportView
        report={makeReport({
          other_breakdown: { noise_count: 314, noise_share: 15.7, hidden_real_count: 0, hidden_real_share: 0, hidden_real_theme_count: 0, total_real_theme_count: 2 },
          theme_chart_variants: { diverge: fragment('TONE-MARK'), icicle: fragment('ICICLE-MARK') },
        })}
        datasetId={1} filters={{}} onFiltersChange={() => {}}
        lookInsideOtherJob={{
          id: 9, dataset_id: 1, column: 'Why', kind: 'look_inside_other', status: 'done', step: 'Done', error: null,
          result: { known_added: 0, new_themes: [], still_other_count: 314, failed_classification_count: 0 },
        }}
      />,
    )
    const order = ['rp-toolbar', 'OVERVIEW-MARK', 'Inside Other', 'TONE-MARK', 'RELIABILITY-CHART-MARK', 'QUALITY-MARK']
    const at = order.map((mark) => html.indexOf(mark))
    expect(at.every((i) => i >= 0)).toBe(true)
    expect([...at].sort((a, b) => a - b)).toEqual(at)
    expect(html).toContain('314') // Still in Other after the run
    expect(html).not.toContain('class="io-cta"') // Look inside runs on the themes screen, not in the report
    expect(html).not.toContain('See all') // nothing folded into Other, so the full list would repeat the treemap
  })

  it('removed text stays gone and the overview has no tab row', () => {
    const html = renderToStaticMarkup(
      <ReportView
        report={makeReport({
          other_breakdown: { noise_count: 3000, noise_share: 60, hidden_real_count: 500, hidden_real_share: 10, hidden_real_theme_count: 4, total_real_theme_count: 11 },
          theme_chart_variants: { rank: { chart_id: 'rank', chart_title: 'Rank', chart_html: '<div>RANK-MARK</div>', chart_width: 1180, chart_height: 400 } },
        })}
        datasetId={1}
      />,
    )
    for (const gone of [
      'Other is a catch-all bucket', "aren't in the", 'distinct topic', 'Genuinely varied answers',
      'These views show the broader context', 'The big picture', 'role="tablist"', 'RANK-MARK',
    ]) expect(html).not.toContain(gone)
  })
})

describe('Inside Other in the report', () => {
  it('is not shown until a Look inside run has finished', () => {
    const html = renderToStaticMarkup(
      <ReportView
        report={makeReport({
          other_breakdown: { noise_count: 314, noise_share: 15.7, hidden_real_count: 0, hidden_real_share: 0, hidden_real_theme_count: 0, total_real_theme_count: 2 },
        })}
        datasetId={1}
      />,
    )
    expect(html).not.toContain('Inside Other')
  })
})
