import { useEffect, useLayoutEffect, useRef } from 'react'

// Matches app/charts.py's own DIM constant (opacity of an unselected/dimmed theme) - kept as one named
// constant here rather than a bare literal, same reasoning as that module's own comment on it.
const DIM_OPACITY = '0.28'

export interface ChartFragmentData {
  chart_id?: string
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
  finding?: boolean
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
  // Stage 3b (docs/TODO.md, fixed 2026-10-23): true while a "look inside Other" job is running - adds a
  // pulsing ring to the treemap's own `[data-theme="Other"]` block and a small "Look inside..." label
  // overlaid on it, matching the mockup's own `class="{{tm.ring}}"` + "Look inside ↓" affordance baked
  // into the Other block itself (not just the separate CTA section below the chart). Pure client-side
  // DOM styling on the already-rendered fragment - no chart-renderer/backend change needed. A no-op on
  // any fragment with no `[data-theme="Other"]` group at all (every chart except the treemap).
  highlightOtherRunning?: boolean
}

// Shared chart-fragment renderer used by both Report.tsx's overview block and Themes.tsx's browse view.
// Adds one delegated click/hover listener for any `[data-theme]` group inside the fragment: hovering over
// a theme dims every OTHER theme group to the same opacity app/charts.py's own DIM constant uses (0.28),
// restoring full opacity on mouseout; clicking calls `onThemeSelect` with that theme's name. Selection
// itself is not tracked here - the caller decides what "selected" means (e.g. which ThemeDetail to show)
// and keeps that as its own state; this component only ever dims on hover, never persists a "selected"
// look across renders.
export default function ThemeChart({ fragment, title, onThemeSelect, selectedTheme, highlightOtherRunning, finding = false }: ThemeChartProps) {
  const ref = useRef<HTMLDivElement | null>(null)
  const scrollRef = useRef<HTMLDivElement | null>(null)

  useLayoutEffect(() => {
    const root = ref.current
    if (!root) return
    for (const child of Array.from(root.children)) {
      if (!(child instanceof HTMLElement) || !child.style.padding) continue
      child.classList.add('rp-chart-body')
      const heading = child.firstElementChild
      if (heading instanceof HTMLElement && heading.style.fontWeight === '600' && heading.style.fontSize) {
        heading.classList.add('rp-chart-question')
      }
      for (const spacer of Array.from(child.children)) {
        if (spacer instanceof HTMLElement && spacer.style.height && parseFloat(spacer.style.height) <= 64
            && !spacer.children.length && !spacer.textContent?.trim()) spacer.classList.add('rp-chart-spacer')
      }
    }
    for (const label of root.querySelectorAll<HTMLElement>(':scope > p')) {
      if (label.style.fontWeight === '500') label.classList.add('rp-focus-label')
    }
    if (fragment.chart_id === 'byScore') {
      for (const row of root.querySelectorAll<HTMLElement>('div')) {
        if (row.style.display !== 'flex' || !row.style.borderTop || row.children.length !== 3) continue
        const [label, bar, pill] = Array.from(row.children)
        if (!(label instanceof HTMLElement) || label.style.width !== '200px') continue
        row.classList.add('rp-score-row')
        label.classList.add('rp-score-label')
        bar.classList.add('rp-score-bar')
        pill.classList.add('rp-score-pill')
      }
    }
    if (fragment.chart_id !== 'heatmap') return
    // The existing heatmap fragment has a grid and a selected-cell explanation, but no semantic
    // hooks. Adapt that known structure here; never match customer text, React IDs or cell positions.
    const grid = Array.from(root.querySelectorAll<HTMLElement>('div')).find((el) => !!el.style.gridTemplateColumns)
    if (!grid) return
    grid.classList.add('rp-heatmap-grid')
    const count = grid.style.gridTemplateColumns.match(/repeat\((\d+)/)?.[1]
    if (count) {
      grid.style.setProperty('--rp-group-count', count)
      grid.style.setProperty('--rp-grid-min', `${160 + Number(count) * 100}px`)
    }
    for (const cell of Array.from(grid.children)) {
      if (!(cell instanceof HTMLElement) || !cell.style.outline) continue
      const explanation = Array.from(cell.children).find((el) => el instanceof HTMLElement && el.style.position === 'absolute')
      if (!(explanation instanceof HTMLElement)) continue
      cell.tabIndex = 0
      cell.setAttribute('aria-label', explanation.textContent ?? '')
      explanation.removeAttribute('style')
      explanation.className = 'rp-selected-explanation'
      explanation.setAttribute('role', 'note')
      grid.parentElement?.appendChild(explanation)
    }
    // Every cell the server gave a note (data-cell-note) can be picked: the outline moves to it and the
    // note below the grid says what it shows. The server's own pick stays selected until then.
    const cells = Array.from(grid.querySelectorAll<HTMLElement>(':scope > [data-cell-note]'))
    if (!cells.length) return
    let note = grid.parentElement?.querySelector<HTMLElement>(':scope > .rp-selected-explanation') ?? null
    const select = (picked: HTMLElement) => {
      if (!note) {
        note = document.createElement('div')
        note.className = 'rp-selected-explanation'
        note.setAttribute('role', 'note')
        grid.parentElement?.appendChild(note)
      }
      for (const cell of cells) cell.setAttribute('aria-pressed', String(cell === picked))
      note.textContent = picked.dataset.cellNote ?? ''
    }
    for (const cell of cells) {
      // The effect can run twice on the same DOM (React dev re-run): the first pass already moved the outline.
      const selected = !!cell.style.outline || cell.getAttribute('aria-pressed') === 'true'
      cell.style.outline = ''
      cell.style.outlineOffset = ''
      cell.classList.add('rp-heatmap-cell')
      cell.tabIndex = 0
      cell.setAttribute('role', 'button')
      cell.setAttribute('aria-pressed', String(selected))
      cell.setAttribute('aria-label', cell.dataset.cellNote ?? '')
    }
    const onClick = (e: Event) => {
      const cell = (e.target as Element).closest<HTMLElement>('[data-cell-note]')
      if (cell && cells.includes(cell)) select(cell)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Enter' && e.key !== ' ') return
      const cell = (e.target as Element).closest<HTMLElement>('[data-cell-note]')
      if (!cell || !cells.includes(cell)) return
      e.preventDefault()
      select(cell)
    }
    grid.addEventListener('click', onClick)
    grid.addEventListener('keydown', onKey)
    return () => {
      grid.removeEventListener('click', onClick)
      grid.removeEventListener('keydown', onKey)
    }
  }, [fragment.chart_html, fragment.chart_id])

  // A chart always opens at its start (BUG-049: dataset 12's first heatmap was found scrolled to its end,
  // hiding the theme-name column). Runs after the DOM adaptation above, which moves nodes and changes the
  // grid's minimum width, so nothing that layout change does can leave the box scrolled.
  useLayoutEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollLeft = 0
  }, [fragment.chart_html, fragment.chart_id])

  // .rp-chart-scroll's own scrollLeft is browser-owned state that outlives a resize: if a viewer scrolls
  // this chart while the window is narrow (more of the chart's fixed pixel width needs scrolling), then
  // widens the window, the browser clamps the stale scrollLeft to the new, smaller max-scroll instead of
  // resetting it to 0 - so the chart stays shifted and its own left edge (title, first cell, first stat)
  // renders clipped even though the chart may now fit almost entirely. A ResizeObserver on the scroll
  // container resets scrollLeft to 0 whenever its size changes, so widening the window always shows the
  // chart's start, matching what a viewer actually expects from "I made the window bigger." The chart itself
  // is observed too: its width settles after first paint (Jost loading, the heatmap's grid minimum), and
  // that late change must not leave the box scrolled either (BUG-049).
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const observer = new ResizeObserver(() => {
      el.scrollLeft = 0
    })
    observer.observe(el)
    if (ref.current) observer.observe(ref.current)
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

  // Stage 3b: the Other-block ring/label, as its own effect (not folded into the selection effect above)
  // so toggling `highlightOtherRunning` alone - the common case, a job starting/finishing while nothing
  // else about this chart changes - doesn't tear down and re-attach the click/hover listeners too.
  useEffect(() => {
    const root = ref.current
    if (!root) return
    const otherEl = root.querySelector<HTMLElement>('[data-theme="Other"]')
    if (!otherEl) return

    if (highlightOtherRunning) {
      otherEl.classList.add('lio-other-ring')
      if (!otherEl.querySelector('.lio-other-label')) {
        const label = document.createElement('div')
        label.className = 'lio-other-label'
        label.textContent = 'Looking inside...'
        otherEl.appendChild(label)
      }
    } else {
      otherEl.classList.remove('lio-other-ring')
      otherEl.querySelector('.lio-other-label')?.remove()
    }

    return () => {
      otherEl.classList.remove('lio-other-ring')
      otherEl.querySelector('.lio-other-label')?.remove()
    }
  }, [fragment.chart_html, highlightOtherRunning])

  return (
    <div className="rp-chart-scroll" ref={scrollRef} role="region" aria-label={title ? `${title}, chart area` : 'Chart area'} tabIndex={0}>
      <div
        ref={ref}
        className="rp-chart"
        // Gallery/export dimensions are not a minimum page height. The fragment's actual plot/SVG
        // supplies its intrinsic height; short evidence rows should not inherit an empty canvas.
        style={{ width: '100%', maxWidth: fragment.chart_width }}
        data-chart-kind={fragment.chart_id}
        data-presentation={finding ? 'finding' : 'overview'}
        aria-label={title}
        dangerouslySetInnerHTML={{ __html: fragment.chart_html }}
      />
    </div>
  )
}
