// @vitest-environment jsdom
//
// Unlike every other test file in this repo (which renders presentational components with
// `renderToStaticMarkup` under vitest's default `environment: 'node'` - see report.test.tsx's and
// jobProgress.test.tsx's own comments on why), `ThemeChart` attaches real DOM event listeners in a
// `useEffect` and needs real hover/click events to fire against real elements to test that delegation -
// `renderToStaticMarkup` never runs effects at all. This file opts into a jsdom environment for itself
// only (the `@vitest-environment` docblock above), via `jsdom` as a devDependency, without changing the
// project's global `environment: 'node'` default every other test file already relies on.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ThemeChart from './ThemeChart'

// Two `[data-theme]` groups, the same shape app/charts.py's treemap_html draws (a <div data-theme="..."> per
// theme, with a rect and a nested sub-part inside it) - enough to exercise "dim every OTHER group" and
// "a click on a nested part still resolves to its own parent [data-theme] group via closest()".
const TWO_THEME_FRAGMENT = `<svg width="200" height="100">
  <g data-theme="Cost"><rect id="cost-rect" x="0" y="0" width="100" height="100"/></g>
  <g data-theme="Charging"><rect id="charging-rect" x="100" y="0" width="100" height="100"/></g>
</svg>`

// Stage 3b (docs/TODO.md, fixed 2026-10-23): a fragment with a real `[data-theme="Other"]` block, the
// same shape `app/charts.py::treemap_html` actually draws, for `highlightOtherRunning` tests.
const WITH_OTHER_FRAGMENT = `<div style="position:relative">
  <div data-theme="Cost" style="position:absolute"><div>Cost</div></div>
  <div data-theme="Other" style="position:absolute"><div>Other</div></div>
</div>`

// jsdom has no layout engine, so it never fires a real ResizeObserver - this fake captures the callback
// ThemeChart registers so a test can invoke it directly, the same way a real browser would after an
// actual container resize.
class FakeResizeObserver {
  static instances: FakeResizeObserver[] = []
  callback: ResizeObserverCallback
  observe = vi.fn()
  disconnect = vi.fn()
  unobserve = vi.fn()
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
    FakeResizeObserver.instances.push(this)
  }
}

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  FakeResizeObserver.instances = []
  vi.stubGlobal('ResizeObserver', FakeResizeObserver)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

function fragment() {
  return { chart_html: TWO_THEME_FRAGMENT, chart_width: 200, chart_height: 100 }
}

describe('ThemeChart', () => {
  it('sizes the chart wrapper to fill its container, capped at the fragment\'s own chart_width', () => {
    // Regression pin: chart_width is a design cap now, not a forced size - app/charts.py's charts
    // genuinely reflow within whatever width they're given (see docs/DECISIONS.md), so the wrapper
    // should fill available space up to that cap rather than always rendering at exactly chart_width.
    act(() => {
      root.render(<ThemeChart fragment={fragment()} />)
    })
    const chartDiv = container.querySelector('.rp-chart') as HTMLElement
    expect(chartDiv.style.width).toBe('100%')
    expect(chartDiv.style.maxWidth).toBe('200px')
  })

  it('dims every OTHER [data-theme] group on hover, and restores opacity on mouseout', () => {
    act(() => {
      root.render(<ThemeChart fragment={fragment()} />)
    })

    const costGroup = container.querySelector('[data-theme="Cost"]') as HTMLElement
    const chargingGroup = container.querySelector('[data-theme="Charging"]') as HTMLElement
    const costRect = container.querySelector('#cost-rect') as HTMLElement

    act(() => {
      costRect.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
    })
    expect(costGroup.style.opacity).toBe('') // the hovered theme itself is never dimmed
    expect(chargingGroup.style.opacity).toBe('0.28') // matches app/charts.py's own DIM constant

    act(() => {
      costRect.dispatchEvent(new MouseEvent('mouseout', { bubbles: true }))
    })
    expect(chargingGroup.style.opacity).toBe('')
  })

  it('calls onThemeSelect with the clicked theme\'s name, resolving a nested element to its parent group', () => {
    const onThemeSelect = vi.fn()
    act(() => {
      root.render(<ThemeChart fragment={fragment()} onThemeSelect={onThemeSelect} />)
    })

    const chargingRect = container.querySelector('#charging-rect') as HTMLElement
    act(() => {
      chargingRect.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })

    expect(onThemeSelect).toHaveBeenCalledTimes(1)
    expect(onThemeSelect).toHaveBeenCalledWith('Charging')
  })

  // Theme editing (docs/TODO.md, fixed 2026-10-22): a PERSISTED highlight, independent of hover.

  it('dims every OTHER group when selectedTheme is set, on initial render', () => {
    act(() => {
      root.render(<ThemeChart fragment={fragment()} selectedTheme="Cost" />)
    })
    const costGroup = container.querySelector('[data-theme="Cost"]') as HTMLElement
    const chargingGroup = container.querySelector('[data-theme="Charging"]') as HTMLElement
    expect(costGroup.style.opacity).toBe('')
    expect(chargingGroup.style.opacity).toBe('0.28')
  })

  it('restores the persisted selection (not a blanket clear) after a hover ends', () => {
    act(() => {
      root.render(<ThemeChart fragment={fragment()} selectedTheme="Charging" />)
    })
    const costGroup = container.querySelector('[data-theme="Cost"]') as HTMLElement
    const chargingGroup = container.querySelector('[data-theme="Charging"]') as HTMLElement
    const costRect = container.querySelector('#cost-rect') as HTMLElement

    act(() => {
      costRect.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }))
    })
    expect(chargingGroup.style.opacity).toBe('0.28') // dimmed by hover over Cost

    act(() => {
      costRect.dispatchEvent(new MouseEvent('mouseout', { bubbles: true }))
    })
    // Charging is the PERSISTED selection - it must stay highlighted, and Cost must go back to dimmed,
    // not both cleared to '' the way a plain hover-only mouseout would.
    expect(chargingGroup.style.opacity).toBe('')
    expect(costGroup.style.opacity).toBe('0.28')
  })

  it('updates the highlight when selectedTheme changes on a re-render, without changing the fragment', () => {
    act(() => {
      root.render(<ThemeChart fragment={fragment()} selectedTheme="Cost" />)
    })
    const costGroup = container.querySelector('[data-theme="Cost"]') as HTMLElement
    const chargingGroup = container.querySelector('[data-theme="Charging"]') as HTMLElement
    expect(costGroup.style.opacity).toBe('')

    act(() => {
      root.render(<ThemeChart fragment={fragment()} selectedTheme="Charging" />)
    })
    expect(costGroup.style.opacity).toBe('0.28')
    expect(chargingGroup.style.opacity).toBe('')
  })

  it('dims nothing when selectedTheme is null/omitted - today\'s behaviour unchanged', () => {
    act(() => {
      root.render(<ThemeChart fragment={fragment()} />)
    })
    const costGroup = container.querySelector('[data-theme="Cost"]') as HTMLElement
    const chargingGroup = container.querySelector('[data-theme="Charging"]') as HTMLElement
    expect(costGroup.style.opacity).toBe('')
    expect(chargingGroup.style.opacity).toBe('')
  })

  // Stage 3b (docs/TODO.md, fixed 2026-10-23): the treemap's own Other-block ring/label.

  it('adds the ring class and a label to the Other block when highlightOtherRunning is true', () => {
    act(() => {
      root.render(
        <ThemeChart
          fragment={{ chart_html: WITH_OTHER_FRAGMENT, chart_width: 200, chart_height: 100 }}
          highlightOtherRunning
        />,
      )
    })
    const otherEl = container.querySelector('[data-theme="Other"]') as HTMLElement
    expect(otherEl.classList.contains('lio-other-ring')).toBe(true)
    expect(otherEl.querySelector('.lio-other-label')).not.toBeNull()
    // Nothing added to an unrelated theme block.
    const costEl = container.querySelector('[data-theme="Cost"]') as HTMLElement
    expect(costEl.classList.contains('lio-other-ring')).toBe(false)
  })

  it('removes the ring and label once highlightOtherRunning goes back to false', () => {
    act(() => {
      root.render(
        <ThemeChart
          fragment={{ chart_html: WITH_OTHER_FRAGMENT, chart_width: 200, chart_height: 100 }}
          highlightOtherRunning
        />,
      )
    })
    act(() => {
      root.render(
        <ThemeChart
          fragment={{ chart_html: WITH_OTHER_FRAGMENT, chart_width: 200, chart_height: 100 }}
          highlightOtherRunning={false}
        />,
      )
    })
    const otherEl = container.querySelector('[data-theme="Other"]') as HTMLElement
    expect(otherEl.classList.contains('lio-other-ring')).toBe(false)
    expect(otherEl.querySelector('.lio-other-label')).toBeNull()
  })

  it('does nothing when highlightOtherRunning is set but the fragment has no Other block', () => {
    expect(() => {
      act(() => {
        root.render(<ThemeChart fragment={fragment()} highlightOtherRunning />)
      })
    }).not.toThrow()
    expect(container.querySelector('.lio-other-ring')).toBeNull()
  })

  it('does not throw when no onThemeSelect is passed and a theme is clicked', () => {
    act(() => {
      root.render(<ThemeChart fragment={fragment()} />)
    })
    const costRect = container.querySelector('#cost-rect') as HTMLElement
    expect(() => {
      act(() => {
        costRect.dispatchEvent(new MouseEvent('click', { bubbles: true }))
      })
    }).not.toThrow()
  })

  it('re-attaches listeners when the fragment html changes', () => {
    const onThemeSelect = vi.fn()
    act(() => {
      root.render(<ThemeChart fragment={fragment()} onThemeSelect={onThemeSelect} />)
    })

    const otherFragment = {
      chart_html: '<svg><g data-theme="Only"><rect id="only-rect" width="10" height="10"/></g></svg>',
      chart_width: 10,
      chart_height: 10,
    }
    act(() => {
      root.render(<ThemeChart fragment={otherFragment} onThemeSelect={onThemeSelect} />)
    })

    const onlyRect = container.querySelector('#only-rect') as HTMLElement
    act(() => {
      onlyRect.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(onThemeSelect).toHaveBeenCalledWith('Only')
  })

  it('resets the scroll container to scrollLeft 0 when it is resized', () => {
    // Regression test: .rp-chart-scroll's scrollLeft is browser-owned state that outlives a resize - a
    // chart scrolled while the window was narrow stayed clipped after widening, because the browser
    // clamps a stale scrollLeft to the new max instead of resetting it to 0. See docs/DECISIONS.md.
    act(() => {
      root.render(<ThemeChart fragment={fragment()} />)
    })

    const scrollDiv = container.querySelector('.rp-chart-scroll') as HTMLElement
    scrollDiv.scrollLeft = 150

    expect(FakeResizeObserver.instances).toHaveLength(1)
    const observer = FakeResizeObserver.instances[0]
    expect(observer.observe).toHaveBeenCalledWith(scrollDiv)

    act(() => {
      observer.callback([], observer as unknown as ResizeObserver)
    })

    expect(scrollDiv.scrollLeft).toBe(0)
  })

  // BUG-049: dataset 12's first heatmap opened scrolled to its end, hiding its theme-name column.
  const heatmap = (note: string) => ({
    chart_id: 'heatmap', chart_width: 1180, chart_height: 700,
    chart_html: `<div style="padding:56px 48px"><div style="display:grid;grid-template-columns:minmax(160px,220px) repeat(2,minmax(0,1fr))">
      <div></div><div>18-34</div><div>35+</div>
      <div>Cost</div><div style="outline:2px solid var(--ink)">40%<div style="position:absolute;left:50%">${note}</div></div><div>20%</div>
    </div></div>`,
  })

  it('a heatmap opens at scrollLeft 0, and a new fragment resets a scrolled box', () => {
    act(() => {
      root.render(<ThemeChart fragment={heatmap('Cost is high')} />)
    })
    const scrollDiv = container.querySelector('.rp-chart-scroll') as HTMLElement
    expect(scrollDiv.scrollLeft).toBe(0)
    expect(container.querySelector('.rp-selected-explanation')?.textContent).toBe('Cost is high')
    scrollDiv.scrollLeft = 32
    act(() => {
      root.render(<ThemeChart fragment={heatmap('Cost is higher')} />)
    })
    expect(scrollDiv.scrollLeft).toBe(0)
  })

  it('nothing takes focus when a heatmap renders, so the page never scrolls to it', () => {
    act(() => {
      root.render(<ThemeChart fragment={heatmap('Cost is high')} />)
    })
    expect(document.activeElement).toBe(document.body)
  })

  it('resets scrollLeft when the chart content itself changes size after load', () => {
    act(() => {
      root.render(<ThemeChart fragment={fragment()} />)
    })
    const scrollDiv = container.querySelector('.rp-chart-scroll') as HTMLElement
    const observer = FakeResizeObserver.instances[0]
    expect(observer.observe).toHaveBeenCalledWith(container.querySelector('.rp-chart'))
    scrollDiv.scrollLeft = 32
    act(() => {
      observer.callback([], observer as unknown as ResizeObserver)
    })
    expect(scrollDiv.scrollLeft).toBe(0)
  })

  it('disconnects the resize observer on unmount', () => {
    act(() => {
      root.render(<ThemeChart fragment={fragment()} />)
    })
    const observer = FakeResizeObserver.instances[0]
    act(() => root.unmount())
    expect(observer.disconnect).toHaveBeenCalledTimes(1)
  })
})
