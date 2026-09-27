import { useEffect, useRef } from 'react'

// Matches app/charts.py's own DIM constant (opacity of an unselected/dimmed theme) - kept as one named
// constant here rather than a bare literal, same reasoning as that module's own comment on it.
const DIM_OPACITY = '0.28'

export interface ChartFragmentData {
  // Raw body fragment (app.charts.render_parts's shape: no <!doctype html>, no own background/font load) -
  // meant to be embedded straight into this page's own DOM, sized by its own chart_width/chart_height
  // rather than a hardcoded guess. Safe to embed via dangerouslySetInnerHTML specifically because it is
  // always server-generated, esc()-escaped SVG/HTML built from stored numbers and theme labels, never
  // anything a viewer typed - this is the one place in the app that uses it, same as the report page's
  // original ChartFragment this component generalizes (see docs/DECISIONS.md).
  chart_html: string
  chart_width: number
  chart_height: number
}

interface ThemeChartProps {
  fragment: ChartFragmentData
  title?: string
  // Called with a theme's name (its `data-theme` attribute - see app/charts.py's treemap_svg, the only
  // chart that currently draws these groups) when the viewer clicks anywhere inside that theme's group,
  // including one of its sub-theme rects (a click there still resolves to the parent theme's own
  // `[data-theme]` group via `closest()`).
  onThemeSelect?: (name: string) => void
}

// Shared chart-fragment renderer used by both Report.tsx's overview block and Themes.tsx's browse view.
// Adds one delegated click/hover listener for any `[data-theme]` group inside the fragment: hovering over
// a theme dims every OTHER theme group to the same opacity app/charts.py's own DIM constant uses (0.28),
// restoring full opacity on mouseout; clicking calls `onThemeSelect` with that theme's name. Selection
// itself is not tracked here - the caller decides what "selected" means (e.g. which ThemeDetail to show)
// and keeps that as its own state; this component only ever dims on hover, never persists a "selected"
// look across renders.
export default function ThemeChart({ fragment, title, onThemeSelect }: ThemeChartProps) {
  const ref = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const root = ref.current
    if (!root) return

    function themeGroups(): HTMLElement[] {
      return Array.from(root!.querySelectorAll<HTMLElement>('[data-theme]'))
    }

    function closestThemeEl(e: Event): HTMLElement | null {
      const target = e.target as Element | null
      return target ? (target.closest('[data-theme]') as HTMLElement | null) : null
    }

    function onOver(e: Event) {
      const hovered = closestThemeEl(e)
      if (!hovered) return
      for (const el of themeGroups()) {
        if (el !== hovered) el.style.opacity = DIM_OPACITY
      }
    }

    function onOut(e: Event) {
      const left = closestThemeEl(e)
      if (!left) return
      for (const el of themeGroups()) el.style.opacity = ''
    }

    function onClick(e: Event) {
      const clicked = closestThemeEl(e)
      if (!clicked || !onThemeSelect) return
      const name = clicked.getAttribute('data-theme')
      if (name) onThemeSelect(name)
    }

    root.addEventListener('mouseover', onOver)
    root.addEventListener('mouseout', onOut)
    root.addEventListener('click', onClick)
    return () => {
      root.removeEventListener('mouseover', onOver)
      root.removeEventListener('mouseout', onOut)
      root.removeEventListener('click', onClick)
    }
    // Re-run (detach then re-attach) whenever the fragment's own HTML changes: dangerouslySetInnerHTML
    // replaces the DOM nodes wholesale, so anything bound to the PREVIOUS nodes would otherwise be
    // attached to now-detached elements. `onThemeSelect` is also a dependency so a caller that passes a
    // fresh closure per render (e.g. one capturing different state) is honoured on the next interaction.
  }, [fragment.chart_html, onThemeSelect])

  return (
    <div className="rp-chart-scroll">
      <div
        ref={ref}
        className="rp-chart"
        style={{ width: fragment.chart_width, minHeight: fragment.chart_height }}
        aria-label={title}
        dangerouslySetInnerHTML={{ __html: fragment.chart_html }}
      />
    </div>
  )
}
