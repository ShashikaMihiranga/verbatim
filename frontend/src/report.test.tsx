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

const OVERVIEW: ReportBlock = {
  kind: 'overview', chart_id: 'overview', chart_title: 'Overview',
  chart_html: '<!doctype html><body>OVERVIEW-MARK</body>', priority: 1, finding_id: null, finding: null,
}
const QUALITY: ReportBlock = {
  kind: 'quality', chart_id: 'quality', chart_title: 'Answer quality',
  chart_html: '<!doctype html><body>QUALITY-MARK</body>', priority: 9, finding_id: null, finding: null,
}
const FINDING: ReportBlock = {
  kind: 'finding', chart_id: 'rank', chart_title: 'Rank themes',
  chart_html: '<!doctype html><body>RELIABILITY-CHART-MARK</body>', priority: 3, finding_id: 11,
  finding: { id: 11, theme_id: 5, sentence: 'Reliability carries the most negative wording.', confidence: 'solid' },
}

function makeReport(overrides: Partial<ReportResponse> = {}): ReportResponse {
  return {
    dataset_id: 1,
    column: 'Why',
    question: "Why haven't you bought an electric vehicle yet?",
    summary: '2 themes found, overall tone negative (-0.15).',
    also_checked_nothing_notable: false,
    blocks: [OVERVIEW, FINDING, QUALITY],
    ...overrides,
  }
}

describe('ReportView', () => {
  it('shows the question, the computed summary, and each block in priority order', () => {
    const html = renderToStaticMarkup(<ReportView report={makeReport()} datasetId={1} />)
    expect(html).toContain('bought an electric vehicle yet?')
    expect(html).toContain('2 themes found, overall tone negative')
    expect(html).toContain('Reliability carries the most negative wording.')
    expect(html.indexOf('OVERVIEW-MARK')).toBeLessThan(html.indexOf('RELIABILITY-CHART-MARK'))
    expect(html.indexOf('RELIABILITY-CHART-MARK')).toBeLessThan(html.indexOf('QUALITY-MARK'))
  })

  it('shows a Solid or Tentative badge on a finding, never both at once', () => {
    const solid = renderToStaticMarkup(<ReportView report={makeReport()} datasetId={1} />)
    expect(solid).toContain('Solid')
    expect(solid).not.toContain('Tentative')

    const tentativeFinding: ReportBlock = { ...FINDING, finding: { ...FINDING.finding!, confidence: 'tentative' } }
    const tentative = renderToStaticMarkup(
      <ReportView report={makeReport({ blocks: [OVERVIEW, tentativeFinding, QUALITY] })} datasetId={1} />,
    )
    expect(tentative).toContain('Tentative')
    expect(tentative).not.toContain('>Solid<')
  })

  it('renders each chart through a sandboxed iframe, never dangerouslySetInnerHTML', () => {
    const html = renderToStaticMarkup(<ReportView report={makeReport()} datasetId={1} />)
    expect(html).toContain('sandbox=""')
    expect(html.match(/<iframe/g)).toHaveLength(3)
    // the raw chart markup only ever appears inside an iframe's srcdoc, never inlined into the page itself
    expect(html).not.toMatch(/<body>OVERVIEW-MARK<\/body>(?!")/)
  })

  it('shows "Also checked, nothing notable" instead of forcing empty finding blocks', () => {
    const report = makeReport({ also_checked_nothing_notable: true, blocks: [OVERVIEW, QUALITY] })
    const html = renderToStaticMarkup(<ReportView report={report} datasetId={1} />)
    expect(html).toContain('Also checked, nothing notable')
    expect(html).not.toContain('rp-sentence')
  })

  it('shows no exact record counts anywhere in the summary line', () => {
    const html = renderToStaticMarkup(<ReportView report={makeReport()} datasetId={1} />)
    expect(html).not.toMatch(/\b\d{2,3},\d{3}\b|\b\d{4,6} (responses|answers|rows)\b/i)
  })
})
