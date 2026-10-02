import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import ReportFilters from './ReportFilters'
import type { ReportFilterOptions, ReportFilters as ReportFiltersValue } from './reportApi'

// Static-markup only (this repo's existing vitest config runs with `environment: 'node'`, no jsdom/
// testing-library anywhere yet - see report.test.tsx's own precedent), so these tests cover rendering
// (which controls appear, with which values) rather than simulated clicks/onChange firing. The actual
// "selecting a value calls onChange and Themes.tsx refetches" behaviour is exercised live in the
// Filters feature's browser verification pass (see docs/DECISIONS.md), not here.

const NO_OPTIONS: ReportFilterOptions = { segment: null, score_band: null, date_range: null }
const ALL_OPTIONS: ReportFilterOptions = {
  segment: { column: 'Region', groups: ['North', 'South'] },
  score_band: { column: 'Rating', bands: ['Low (0-6)', 'Middle (7-8)', 'High (9-10)'] },
  date_range: { column: 'Survey date', min: '2026-01-01', max: '2026-03-31' },
}
const EMPTY_VALUE: ReportFiltersValue = {}

describe('ReportFilters', () => {
  it('renders nothing when every option is null', () => {
    const html = renderToStaticMarkup(
      <ReportFilters options={NO_OPTIONS} value={EMPTY_VALUE} onChange={() => {}} />,
    )
    expect(html).toBe('')
  })

  it('renders only the controls whose options are non-null', () => {
    const segmentOnly: ReportFilterOptions = { ...NO_OPTIONS, segment: ALL_OPTIONS.segment }
    const html = renderToStaticMarkup(
      <ReportFilters options={segmentOnly} value={EMPTY_VALUE} onChange={() => {}} />,
    )
    expect(html).toContain('Region')
    expect(html).toContain('North')
    expect(html).toContain('South')
    expect(html).not.toContain('<input') // no date inputs
    expect(html.match(/<select/g)).toHaveLength(1) // only the segment select, not score_band too
  })

  it('renders a select/date-input per non-null option when all three are present', () => {
    const html = renderToStaticMarkup(
      <ReportFilters options={ALL_OPTIONS} value={EMPTY_VALUE} onChange={() => {}} />,
    )
    expect(html.match(/<select/g)).toHaveLength(2) // segment + score_band
    expect(html.match(/type="date"/g)).toHaveLength(2) // date_from + date_to
    expect(html).toContain('Low (0-6)')
    expect(html).toContain('High (9-10)')
  })

  it('hides "Clear filters" when no filter is active', () => {
    const html = renderToStaticMarkup(
      <ReportFilters options={ALL_OPTIONS} value={EMPTY_VALUE} onChange={() => {}} />,
    )
    expect(html).not.toContain('Clear filters')
  })

  it('shows "Clear filters" and the selected value once a filter is active', () => {
    const html = renderToStaticMarkup(
      <ReportFilters options={ALL_OPTIONS} value={{ segment: 'North' }} onChange={() => {}} />,
    )
    expect(html).toContain('Clear filters')
    expect(html).toContain('value="North" selected')
  })
})
