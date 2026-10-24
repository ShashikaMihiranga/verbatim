// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import ThemeChart from './ThemeChart'
import { ResponsiveChart } from './FindingChartTabs'
import ReportView from './Report'
import type { ReportBlock, ReportResponse } from './reportApi'

let host: HTMLDivElement
let root: Root
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} })
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})
afterEach(() => { act(() => root.unmount()); host.remove(); vi.unstubAllGlobals() })

const heatmap = (text: string) => ({ chart_id: 'heatmap', chart_width: 1180, chart_height: 700,
  chart_html: `<div style="padding:56px 48px"><div style="display:grid;grid-template-columns:160px repeat(2,1fr)"><div>Theme</div><div>Long division name</div><div>n=240</div><div>45%</div><div style="position:relative;outline:2px solid black">55%<div style="position:absolute;left:50%;bottom:100%">${text}</div></div></div></div>` })

it('moves selected evidence out of the cells without losing values or keyboard access', () => {
  act(() => root.render(<ThemeChart fragment={heatmap('55% in this group; 40% overall.')} />))
  const grid = host.querySelector('.rp-heatmap-grid')!
  const note = host.querySelector('[role="note"]')!
  expect(grid.contains(note)).toBe(false)
  expect(note.textContent).toBe('55% in this group; 40% overall.')
  expect((note as HTMLElement).style.position).toBe('')
  const cell = grid.querySelector<HTMLElement>('[tabindex="0"]')!
  cell.focus()
  expect(document.activeElement).toBe(cell)
  expect(cell.getAttribute('aria-label')).toContain('40% overall')
  expect(grid.textContent).toContain('n=240')
  expect(grid.textContent).toContain('55%')
  act(() => root.render(<ThemeChart fragment={heatmap('Filtered evidence.')} />))
  expect(host.querySelectorAll('[role="note"]')).toHaveLength(1)
  expect(host.querySelector('[role="note"]')?.textContent).toBe('Filtered evidence.')
})

it.each(['first', 'last'])('keeps a selected %s-edge explanation outside the heatmap', (edge) => {
  const selected = '<div style="position:relative;outline:2px solid black">55%<div style="position:absolute">A long explanation about the actual selected division and its sample.</div></div>'
  const other = '<div>45%</div>'
  const fragment = { ...heatmap(''), chart_html: '<div style="padding:56px 48px"><div style="display:grid;grid-template-columns:160px repeat(2,1fr)"><div></div><div>Long division name</div><div>Another division</div><div>Theme</div>'
    + (edge === 'first' ? selected + other : other + selected) + '</div></div>' }
  act(() => root.render(<ThemeChart fragment={fragment} />))
  const note = host.querySelector('.rp-selected-explanation')!
  expect(note.closest('.rp-heatmap-grid')).toBeNull()
  expect(host.querySelector('.rp-heatmap-grid')?.textContent).toContain('Long division name')
  expect(note.textContent).toContain('actual selected division')
})

it('uses intrinsic plot height rather than a gallery minimum and marks only empty layout spacers', () => {
  const fragment = heatmap('Selected comparison')
  fragment.chart_html = '<div style="padding:56px 48px"><div style="height:64px"></div><svg height="420" aria-label="Real plot"></svg><div style="height:32px">Real content</div></div>'
  act(() => root.render(<ThemeChart fragment={fragment} />))
  expect(host.querySelector<HTMLElement>('.rp-chart')?.style.minHeight).toBe('')
  expect(host.querySelector('.rp-chart-body')).toBeTruthy()
  expect(host.querySelectorAll('.rp-chart-spacer')).toHaveLength(1)
  expect(host.querySelector('svg')?.getAttribute('height')).toBe('420')
  expect(host.textContent).toContain('Real content')
})

it('provides a container query boundary for compact hierarchy and readable heatmap scrolling', () => {
  act(() => root.render(<ResponsiveChart fragment={heatmap('Evidence')} compact={{ ...heatmap('Compact'), chart_id: 'icicle' }} title="Hierarchy" />))
  expect(host.querySelector('.rp-responsive-chart > .rp-chart-compact')).toBeTruthy()
  expect(host.querySelector<HTMLElement>('.rp-heatmap-grid')?.style.getPropertyValue('--rp-group-count')).toBe('2')
  expect(host.querySelector<HTMLElement>('.rp-heatmap-grid')?.style.getPropertyValue('--rp-grid-min')).toBe('360px')
  expect(host.querySelector('[role="region"]')?.getAttribute('tabindex')).toBe('0')
})

const findingBlock: ReportBlock = { ...heatmap('Actual selected evidence'), kind: 'finding', priority: 5,
  chart_title: 'Themes by segment', finding_id: 42,
  finding: { id: 42, theme_id: 5, sentence: 'Different groups raise this theme differently.', confidence: 'solid' } }
function reportFixture(): ReportResponse {
  return { dataset_id: 11, column: 'Question', question: 'What did you think?', summary: '', columns_used: [],
    blocks: [{ ...findingBlock, kind: 'overview', chart_id: 'overview', finding: null, chart_html: '<p>Overall evidence</p>' },
      findingBlock, { ...findingBlock, kind: 'quality', chart_id: 'quality', finding: null, chart_html: '<p>Quality evidence</p>' }],
    also_checked_nothing_notable: false, filter_options: { segment: null, score_band: null, date_range: null },
    filters_applied: { segment: null, score_band: null, date_from: null, date_to: null },
    theme_chart_variants: {}, other_breakdown: null, all_themes: [] }
}

it('places the overview first, shows each headline once, and keeps confidence and answer controls', () => {
  act(() => root.render(<ReportView report={reportFixture()} datasetId={11} />))
  expect(host.querySelector('h1')?.textContent).toBe('What did you think?')
  expect(host.querySelectorAll('h3.rp-sentence')).toHaveLength(1)
  expect(host.textContent?.match(/Different groups raise this theme differently\./g)).toHaveLength(1)
  expect(host.textContent!.indexOf('Overall evidence')).toBeLessThan(host.textContent!.indexOf(findingBlock.finding!.sentence))
  expect(host.querySelector('a[href="#report-findings"]')).toBeTruthy()
  expect(host.querySelector('#report-finding-42 .th-see')?.textContent).toBe('See answers')
  expect(host.querySelector('#report-finding-42 .th-badge')?.textContent).toBe('Solid')
})

it('shows identical broad context once, retains distinct contexts and all findings without mutating data', () => {
  const report = reportFixture()
  const broad = { ...heatmap('Shared context'), chart_label: 'All themes: group mix', chart_title: 'Group mix', chart_note: 'All displayed themes.' }
  report.blocks[1] = { ...findingBlock, chart_variants: { groupMix: broad } }
  report.blocks.splice(2, 0, { ...findingBlock, finding_id: 43,
    finding: { ...findingBlock.finding!, id: 43, sentence: 'A second saved finding.' },
    chart_variants: { groupMix: broad, sankey: { ...broad, chart_html: '<p>A different source context</p>', chart_label: 'All themes: flow' } } })
  const before = JSON.stringify(report)
  act(() => root.render(<ReportView report={report} datasetId={11} />))
  expect(host.querySelectorAll('.rp-context-view')).toHaveLength(2)
  expect(host.querySelectorAll('h3.rp-sentence')).toHaveLength(2)
  expect(host.querySelectorAll('.th-see')).toHaveLength(2)
  expect(host.querySelectorAll('[role="tab"]')).toHaveLength(0)
  expect(host.querySelector<HTMLDetailsElement>('#report-explore > details')?.open).toBe(false)
  expect(host.textContent!.match(/Shared context/g)).toHaveLength(1)
  expect(host.textContent).toContain('A different source context')
  expect(JSON.stringify(report)).toBe(before)
})
