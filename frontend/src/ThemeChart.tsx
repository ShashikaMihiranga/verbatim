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
  // Called with a theme's name (its `data-theme` attribute - see app/charts.py's treemap_html, the only
  // chart that currently draws these groups) when the viewer clicks anywhere inside that theme's group,
  // including one of its sub-theme rects (a click there still resolves to the parent theme's own
  // `[data-theme]` group via `closest()`).
  onThemeSelect?: (name: string) => void
  // Theme editing (docs/TODO.md, fixed 2026-10-22): a PERSISTED highlight (dims every other theme group
  // to the same DIM_OPACITY), independent of hover - `null`/undefined means "nothing selected, dim
  // nothing" (today's only behaviour before this prop existed). Unlike hover (transient, cleared on
  // mouseout), this stays applied across re-renders until the caller changes it - the "selecting a theme
  // in one chart highlights it in all charts" feature from docs/TODO.md's "also unbuilt" note, now wired
  // by having every `ThemeChart` instance on a page receive the SAME selected name from its caller.
  selectedTheme?: string | null
}

// Shared chart-fragment renderer used by both Report.tsx's overview block and Themes.tsx's browse view.
// Adds one delegated click/hover listener for any `[data-theme]` group inside the fragment: hovering over
// a theme dims every OTHER theme group to the same opacity app/charts.py's own DIM constant uses (0.28),
// restoring full opacity on mouseout; clicking calls `onThemeSelect` with that theme's name. Selection
// itself is not tracked here - the caller decides what "selected" means (e.g. which ThemeDetail to show)
// and keeps that as its own state; this component only ever dims on hover, never persists a "selected"
// look across renders.
export default function ThemeChart({ fragment, title, onThemeSelect, selectedTheme }: ThemeChartProps) {
  const ref = useRef<HTMLDivElement | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  // .rp-chart-scroll's own scrollLeft is browser-owned state that outlives a resize: if a viewer scrolls
  // this chart while the window is narrow (more of the chart's fixed pixel width needs scrolling), then
  // widens the window, the browser clamps the stale scrollLeft to the new, smaller max-scroll instead of
  // resetting it to 0 - so the chart stays shifted and its own left edge (title, first cell, first stat)
  // renders clipped even though the chart may now fit almost entirely. A ResizeObserver on the scroll
  // container resets scrollLeft to 0 whenever its size changes, so widening the window always shows the
  // chart's start, matching what a viewer actually expects from "I made the window bigger."
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const observer = new ResizeObserver(() => {
      el.scrollLeft = 0
    })
    observer.observe(el)
    return () => observer.disconnect()
  }, [fragment.chart_html])

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

    function applySelection() {
      for (const el of themeGroups()) {
        if (!selectedTheme) {
          el.style.opacity = ''
        } else {
          el.style.opacity = el.getAttribute('data-theme') === selectedTheme ? '' : DIM_OPACITY
        }
      }
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
      applySelection() // restore the PERSISTED selection state, not a blanket clear - see selectedTheme's own comment
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
    applySelection() // apply the persisted selection immediately - dangerouslySetInnerHTML just replaced
                     // every node, so nothing carries the previous render's inline opacity forward.
    return () => {
      root.removeEventListener('mouseover', onOver)
      root.removeEventListener('mouseout', onOut)
      root.removeEventListener('click', onClick)
    }
    // Re-run (detach then re-attach) whenever the fragment's own HTML changes: dangerouslySetInnerHTML
    // replaces the DOM nodes wholesale, so anything bound to the PREVIOUS nodes would otherwise be
    // attached to now-detached elements. `onThemeSelect`/`selectedTheme` are also dependencies so a
    // caller passing a fresh closure or a new selection is honoured on the next interaction/render.
  }, [fragment.chart_html, onThemeSelect, selectedTheme])

  return (
    <div className="rp-chart-scroll" ref={scrollRef}>
      <div
        ref={ref}
        className="rp-chart"
        // chart_width/chart_height are a DESIGN CAP, not a forced size: each chart's own markup (see
        // app/charts.py's fluid-layout rewrite, docs/DECISIONS.md) genuinely reflows within whatever
        // width it's given via CSS/container queries, so this wrapper should fill its container up to
        // that cap rather than always rendering at exactly chart_width - never wider than the design was
        // built for on a huge monitor, but never artificially pinned narrower either.
        style={{ width: '100%', maxWidth: fragment.chart_width, minHeight: fragment.chart_height }}
        aria-label={title}
        dangerouslySetInnerHTML={{ __html: fragment.chart_html }}
      />
    </div>
  )
}
