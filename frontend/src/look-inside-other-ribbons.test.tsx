import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import LookInsideOtherRibbons from './LookInsideOtherRibbons'

// Static-markup only (node environment) - same precedent as look-inside-other.test.tsx. This component
// has no event handlers, just data-driven SVG, so no jsdom/effects needed.

describe('LookInsideOtherRibbons', () => {
  it('draws one ribbon per known theme plus a "New themes" destination', () => {
    const html = renderToStaticMarkup(
      <LookInsideOtherRibbons
        allThemes={[
          { name: 'Cost', share: 42, count: 210, sentiment: -0.3 },
          { name: 'Support', share: 18, count: 90, sentiment: 0.1 },
        ]}
      />,
    )
    expect(html).toContain('Cost')
    expect(html).toContain('42%')
    expect(html).toContain('Support')
    expect(html).toContain('18%')
    expect(html).toContain('New themes')
    expect(html).toContain('lio-ribbon')
  })

  it('caps known-theme ribbons at 7, the treemap palette\'s own limit', () => {
    const allThemes = Array.from({ length: 10 }, (_, i) => ({
      name: `Theme ${i}`, share: 10 - i, count: 100 - i * 5, sentiment: 0,
    }))
    const html = renderToStaticMarkup(<LookInsideOtherRibbons allThemes={allThemes} />)
    // 7 known + 1 "New themes" destination circle label = 8 <text> destination labels total.
    expect(html).toContain('Theme 6')
    expect(html).not.toContain('Theme 7')
    expect(html).toContain('New themes')
  })

  it('never throws on an empty theme list - still draws the Other source and the New themes destination', () => {
    expect(() => renderToStaticMarkup(<LookInsideOtherRibbons allThemes={[]} />)).not.toThrow()
    const html = renderToStaticMarkup(<LookInsideOtherRibbons allThemes={[]} />)
    expect(html).toContain('Other')
    expect(html).toContain('New themes')
  })
})
