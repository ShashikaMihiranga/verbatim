import { useLayoutEffect, useEffect, useRef, useState } from 'react'

// Matches app/charts.py's own DIM constant (opacity of an unselected/dimmed theme) - kept as one named
// constant here rather than a bare literal, same reasoning as that module's own comment on it.
const DIM_OPACITY = '0.28'

// Never shrink below the fragment's own natural size (app/charts.py's fixed-pixel layout already hand-
// sizes its text for legibility at that scale - shrinking further would make small labels harder to
// read, so a container narrower than natural falls back to today's horizontal scroll instead). Never
// grow past 1.35x either, so text doesn't become absurd on an ultrawide monitor - matches report.css's
// own 1600px cap on a 1180px-natural chart (1600/1180 ~= 1.356).
export const MIN_SCALE = 1
export const MAX_SCALE = 1.35

// Plain, DOM-free so it's directly unit-testable - jsdom has no layout engine, so a real container width
// is never available in a test; this function's own inputs/output can still be asserted without one.
export function computeScale(containerWidth: number, naturalWidth: number): number {
  if (!containerWidth || !naturalWidth) return MIN_SCALE
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, containerWidth / naturalWidth))
}

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
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const [scale, setScale] = useState(MIN_SCALE)

  // .rp-chart-scroll's own scrollLeft is browser-owned state that outlives a resize: if a viewer scrolls
  // this chart while the window is narrow (more of the chart's fixed pixel width needs scrolling), then
  // widens the window, the browser clamps the stale scrollLeft to the new, smaller max-scroll instead of
  // resetting it to 0 - so the chart stays shifted and its own left edge (title, first cell, first stat)
  // renders clipped even though the chart may now fit almost entirely. Resetting scrollLeft to 0 on every
  // resize matches what a viewer actually expects from "I made the window bigger."
  //
  // The same resize signal also drives the scale computation below (report.css's breakout lets
  // .rp-chart-scroll grow past .page's normal 960px column - see that file's own comment - so this
  // container's real width is the "available width" the chart should fill, up to MAX_SCALE). One
  // ResizeObserver on one element covers both concerns; two observers on the same node would be
  // redundant. Scale is computed synchronously on mount too (not just from the observer's first async
  // callback) so the right size applies before first paint.
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el) return
    function recompute() {
      setScale(computeScale(el!.clientWidth, fragment.chart_width))
      el!.scrollLeft = 0
    }
    recompute()
    const observer = new ResizeObserver(recompute)
    observer.observe(el)
    return () => observer.disconnect()
  }, [fragment.chart_html, fragment.chart_width])

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
    <div className="rp-chart-scroll" ref={scrollRef}>
      <div
        className="rp-chart-scale"
        style={{ width: fragment.chart_width * scale, height: fragment.chart_height * scale }}
      >
        <div
          ref={ref}
          className="rp-chart"
          style={{
            width: fragment.chart_width,
            minHeight: fragment.chart_height,
            transform: `scale(${scale})`,
            transformOrigin: 'top left',
          }}
          aria-label={title}
          dangerouslySetInnerHTML={{ __html: fragment.chart_html }}
        />
      </div>
    </div>
  )
}
