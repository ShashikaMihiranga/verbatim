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

// Two `[data-theme]` groups, the same shape app/charts.py's treemap_svg draws (a <g data-theme="..."> per
// theme, with a rect and a nested sub-part inside it) - enough to exercise "dim every OTHER group" and
// "a click on a nested part still resolves to its own parent [data-theme] group via closest()".
const TWO_THEME_FRAGMENT = `<svg width="200" height="100">
  <g data-theme="Cost"><rect id="cost-rect" x="0" y="0" width="100" height="100"/></g>
  <g data-theme="Charging"><rect id="charging-rect" x="100" y="0" width="100" height="100"/></g>
</svg>`

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.restoreAllMocks()
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
})
