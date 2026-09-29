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
import ThemeChart, { MAX_SCALE, MIN_SCALE, computeScale } from './ThemeChart'

// Two `[data-theme]` groups, the same shape app/charts.py's treemap_svg draws (a <g data-theme="..."> per
// theme, with a rect and a nested sub-part inside it) - enough to exercise "dim every OTHER group" and
// "a click on a nested part still resolves to its own parent [data-theme] group via closest()".
const TWO_THEME_FRAGMENT = `<svg width="200" height="100">
  <g data-theme="Cost"><rect id="cost-rect" x="0" y="0" width="100" height="100"/></g>
  <g data-theme="Charging"><rect id="charging-rect" x="100" y="0" width="100" height="100"/></g>
</svg>`

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

  it('disconnects the resize observer on unmount', () => {
    act(() => {
      root.render(<ThemeChart fragment={fragment()} />)
    })
    const observer = FakeResizeObserver.instances[0]
    act(() => root.unmount())
    expect(observer.disconnect).toHaveBeenCalledTimes(1)
  })
})

describe('computeScale', () => {
  it('returns 1 when the container matches the fragment\'s natural width', () => {
    expect(computeScale(1180, 1180)).toBe(1)
  })

  it('scales up for a wider container, within bounds', () => {
    expect(computeScale(1408, 1180)).toBeCloseTo(1.193, 2)
  })

  it('never shrinks below MIN_SCALE for a narrower container', () => {
    expect(computeScale(700, 1180)).toBe(MIN_SCALE)
  })

  it('never grows past MAX_SCALE for a very wide container', () => {
    expect(computeScale(2000, 1180)).toBe(MAX_SCALE)
  })

  it('falls back to MIN_SCALE on falsy inputs instead of dividing by zero', () => {
    expect(computeScale(0, 1180)).toBe(MIN_SCALE)
    expect(computeScale(1180, 0)).toBe(MIN_SCALE)
  })
})

describe('ThemeChart scaling', () => {
  // jsdom has no layout engine, so clientWidth is always 0 - stub it directly on the scroll container
  // the same way the existing FakeResizeObserver lets a test invoke a "resize" without a real browser.
  function stubClientWidth(el: HTMLElement, width: number) {
    Object.defineProperty(el, 'clientWidth', { value: width, configurable: true })
  }

  it('scales the chart wrapper to fill a wider available container', () => {
    act(() => {
      root.render(<ThemeChart fragment={fragment()} />)
    })
    const scrollDiv = container.querySelector('.rp-chart-scroll') as HTMLElement
    const scaleDiv = container.querySelector('.rp-chart-scale') as HTMLElement
    const chartDiv = container.querySelector('.rp-chart') as HTMLElement
    stubClientWidth(scrollDiv, 300) // fragment().chart_width is 200 - a wider container than natural

    const observer = FakeResizeObserver.instances[0]
    act(() => {
      observer.callback([], observer as unknown as ResizeObserver)
    })

    const expected = computeScale(300, 200)
    expect(scaleDiv.style.width).toBe(`${200 * expected}px`)
    expect(scaleDiv.style.height).toBe(`${100 * expected}px`)
    expect(chartDiv.style.transform).toBe(`scale(${expected})`)
  })

  it('falls back to natural size (scale 1) when the container is narrower than the chart', () => {
    act(() => {
      root.render(<ThemeChart fragment={fragment()} />)
    })
    const scrollDiv = container.querySelector('.rp-chart-scroll') as HTMLElement
    const chartDiv = container.querySelector('.rp-chart') as HTMLElement
    stubClientWidth(scrollDiv, 100) // narrower than fragment().chart_width (200)

    const observer = FakeResizeObserver.instances[0]
    act(() => {
      observer.callback([], observer as unknown as ResizeObserver)
    })

    expect(chartDiv.style.transform).toBe('scale(1)')
  })
})
