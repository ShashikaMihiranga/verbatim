// @vitest-environment jsdom
//
// Needs jsdom (not plain renderToStaticMarkup) because the test clicks a tab button to confirm the
// switcher actually switches - same reasoning as ThemeChart.test.tsx's own docblock.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LookInsideOtherChart } from './jobsApi'
import LookInsideOtherCharts from './LookInsideOtherCharts'

function chart(title: string, marker: string): LookInsideOtherChart {
  return { chart_title: title, chart_html: `<svg><text>${marker}</text></svg>`, chart_width: 100, chart_height: 100 }
}

// ThemeChart.tsx (rendered for every non-Arc tab) registers a real ResizeObserver - jsdom has none, so
// this fake stands in, same precedent as ThemeChart.test.tsx's own FakeResizeObserver.
class FakeResizeObserver {
  observe = vi.fn()
  disconnect = vi.fn()
  unobserve = vi.fn()
}

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  vi.stubGlobal('ResizeObserver', FakeResizeObserver)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

describe('LookInsideOtherCharts', () => {
  it('renders nothing when no real chart tab is available', () => {
    act(() => {
      root.render(<LookInsideOtherCharts charts={{}} />)
    })
    expect(container.innerHTML).toBe('')
  })

  it('only shows tabs for chart ids that are actually present', () => {
    act(() => {
      root.render(<LookInsideOtherCharts charts={{ rank: chart('Rank', 'RANK-MARK') }} />)
    })
    const tabs = Array.from(container.querySelectorAll('[role="tab"]')).map((b) => b.textContent)
    expect(tabs).toEqual(['Rank', 'Arc'])
  })

  it('switches the displayed chart when a tab is clicked', () => {
    act(() => {
      root.render(
        <LookInsideOtherCharts
          charts={{ othergrowth: chart('Sankey', 'SANKEY-MARK'), icicle: chart('Icicle', 'ICICLE-MARK') }}
        />,
      )
    })
    expect(container.innerHTML).toContain('SANKEY-MARK')

    const icicleTab = Array.from(container.querySelectorAll('[role="tab"]')).find((b) => b.textContent === 'Icicle') as HTMLElement
    act(() => {
      icicleTab.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(container.innerHTML).toContain('ICICLE-MARK')
    expect(container.innerHTML).not.toContain('SANKEY-MARK')
  })

  it('shows the honest explanatory message, not a chart, when the Arc tab is selected', () => {
    act(() => {
      root.render(<LookInsideOtherCharts charts={{ rank: chart('Rank', 'RANK-MARK') }} />)
    })
    const arcTab = Array.from(container.querySelectorAll('[role="tab"]')).find((b) => b.textContent === 'Arc') as HTMLElement
    act(() => {
      arcTab.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(container.querySelector('.lio-arc-note')).not.toBeNull()
    expect(container.innerHTML).not.toContain('RANK-MARK')
  })
})
