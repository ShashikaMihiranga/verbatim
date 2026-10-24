// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import FindingChartTabs from './FindingChartTabs'
import ThemeChartTabs from './ThemeChartTabs'
import ReportView from './Report'
import type { ReportBlock, ReportResponse, ReportThemeChartVariant } from './reportApi'

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} unobserve() {} })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

const fragment = (mark: string): ReportThemeChartVariant => ({ chart_title: mark, chart_html: `<div>${mark}</div>`, chart_width: 800, chart_height: 200 })
const block: ReportBlock = {
  ...fragment('HEATMAP'), kind: 'finding', chart_id: 'heatmap', priority: 5, finding_id: 1,
  finding: { id: 1, theme_id: 2, sentence: 'Saved finding sentence.', confidence: 'solid' },
  chart_variants: { groupMix: { ...fragment('GROUP-MIX'), chart_label: 'Group mix' },
    sankey: { ...fragment('FLOW'), chart_label: 'Theme flow', chart_note: 'Flow uses estimated tone splits.' } },
}

function click(label: string) {
  const button = Array.from(container.querySelectorAll('button')).find((b) => b.textContent === label)
  expect(button).toBeTruthy()
  act(() => button!.click())
}

describe('Stage 5 finding charts', () => {
  it('replaces only the visual and displays the method note on the matching view', () => {
    act(() => root.render(<FindingChartTabs block={block} />))
    expect(container.querySelector('[role="tabpanel"]')?.textContent).toBe('HEATMAP')
    click('Theme flow')
    expect(container.querySelector('[role="tabpanel"]')?.textContent).toContain('estimated tone splits')
    expect(container.querySelector('[role="tabpanel"]')?.textContent).toContain('FLOW')
    expect(container.querySelector('[role="tabpanel"]')?.textContent).not.toContain('HEATMAP')
  })

  it('falls back immediately when filtering removes the selected alternative', () => {
    act(() => root.render(<FindingChartTabs block={block} />))
    click('Group mix')
    act(() => root.render(<FindingChartTabs block={{ ...block, chart_variants: {} }} />))
    expect(container.textContent).toBe('HEATMAP')
    expect(container.textContent).not.toContain('GROUP-MIX')
  })

  it('supports keyboard chart selection', () => {
    act(() => root.render(<FindingChartTabs block={block} />))
    const first = container.querySelector('button')!
    act(() => first.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })))
    expect(container.querySelector('[role="tab"][aria-selected="true"]')?.textContent).toBe('Group mix')
  })

  it('also makes an automatically selected hierarchy finding compact on mobile', () => {
    const hierarchy = { ...block, ...fragment('SUNBURST'), chart_id: 'sunburst', compact_chart_id: 'icicle',
      chart_variants: { icicle: fragment('ICICLE') } }
    act(() => root.render(<FindingChartTabs block={hierarchy} />))
    expect(container.querySelector('.rp-chart-desktop')?.textContent).toBe('SUNBURST')
    expect(container.querySelector('.rp-chart-compact')?.textContent).toBe('ICICLE')
  })

  it('pairs desktop hierarchy with the compact chart, and survives removal of both', () => {
    const overview = { ...block, kind: 'overview' as const, chart_id: 'overview', ...fragment('OVERVIEW') }
    const variants = { sunburst: { ...fragment('SUNBURST'), compact_chart_id: 'icicle' }, icicle: fragment('ICICLE') }
    act(() => root.render(<ThemeChartTabs overview={overview} variants={variants} />))
    click('Sunburst')
    expect(container.querySelector('.rp-chart-desktop')?.textContent).toBe('SUNBURST')
    expect(container.querySelector('.rp-chart-compact')?.textContent).toBe('ICICLE')
    act(() => root.render(<ThemeChartTabs overview={overview} variants={{ rank: fragment('RANK') }} />))
    expect(container.textContent).toContain('OVERVIEW')
    expect(container.querySelector('.rp-chart-compact')).toBeNull()
  })

  it('shows numeric exploration below findings and above the quality footer', () => {
    const report: ReportResponse = {
      dataset_id: 1, column: 'Why', question: 'Why?', summary: '', also_checked_nothing_notable: false,
      blocks: [{ ...block, kind: 'overview', ...fragment('OVERVIEW') }, block,
        { ...block, kind: 'quality', ...fragment('QUALITY') }],
      columns_used: [], filter_options: { segment: null, score_band: null, date_range: null },
      filters_applied: { segment: null, score_band: null, date_from: null, date_to: null },
      other_breakdown: null, all_themes: [], theme_chart_variants: {},
      explorations: [{ ...fragment('GRID'), chart_label: 'Age and Spend', chart_note: 'Estimated from theme averages.' }],
    }
    act(() => root.render(<ReportView report={report} datasetId={1} />))
    expect(container.querySelector('details')?.open).toBe(false)
    expect(container.querySelector('summary')?.textContent).toBe('Explore Age and Spend')
    expect(container.textContent!.indexOf('GRID')).toBeLessThan(container.textContent!.indexOf('QUALITY'))
    expect(container.textContent!.indexOf('Saved finding sentence.')).toBeLessThan(container.textContent!.indexOf('GRID'))
  })
})
