import { animate, stagger, utils } from 'animejs'
import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import type { ReportResponse } from '../reportApi'
import type { ChartFragmentData } from '../ThemeChart'
import { PauseButton } from './homeFit'
import { onView, useReducedMotion } from './homeMotion'
import { loadSampleReport, SAMPLE_TABS } from './sampleReport'

// What is in a report (hand-off section 4): six pill tabs and one panel. Each tab shows a real chart from
// the sample report with the sentence it supports. Tabs auto-advance every 6s (paused by the button, by
// keyboard or click focus, and under reduced motion); a shown chart rebuilds itself; hover replays it.

const ADVANCE_MS = 6000

// A server chart fragment (app/charts.py render_parts), scaled evenly to fit its box. Safe to embed: it is
// server-generated, escaped SVG/HTML from our own frozen sample file, the same markup Report.tsx embeds.
function ChartBox({ fragment, replay }: { fragment: ChartFragmentData; replay: number }) {
  const box = useRef<HTMLDivElement | null>(null)
  const inner = useRef<HTMLDivElement | null>(null)
  const [k, setK] = useState(0)
  const reduce = useReducedMotion()
  useLayoutEffect(() => {
    const el = box.current?.parentElement
    if (!el) return
    const measure = () => {
      const narrow = el.clientWidth < 600 // phones: keep the chart readable and let it scroll sideways in its box
      const fit = narrow ? el.clientWidth / fragment.chart_width : Math.min(el.clientWidth / fragment.chart_width, (el.clientHeight || 390) / fragment.chart_height)
      setK(Math.min(1, narrow ? Math.max(fit, 0.5) : fit))
    }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [fragment])
  useEffect(() => {
    const el = inner.current
    if (!el || reduce) return
    // Rebuild the chart: its marks fade and rise in, in drawing order.
    const marks = Array.from(el.querySelectorAll<SVGElement | HTMLElement>('svg rect, svg path, svg circle, svg text, svg line, svg polyline')).slice(0, 220)
    utils.set(marks, { opacity: 0 })
    const a = animate(marks, { opacity: [0, 1], translateY: [6, 0], duration: 520, delay: stagger(Math.max(2, Math.round(900 / Math.max(1, marks.length)))), ease: 'outQuad' })
    return () => { a.revert() }
  }, [fragment, replay, reduce])
  return (
    <div ref={box} className={`hd-chartbox${fragment.chart_id === 'quotes' ? ' is-tall' : ''}`} style={{ width: fragment.chart_width * k, height: fragment.chart_height * k }}>
      <div ref={inner} className="hd-chartbox-in" style={{ width: fragment.chart_width, height: fragment.chart_height, transform: `scale(${k})` }}
        dangerouslySetInnerHTML={{ __html: fragment.chart_html }} />
    </div>
  )
}

export default function ReportTabs() {
  const reduce = useReducedMotion()
  const [report, setReport] = useState<ReportResponse | null>(null)
  const [failed, setFailed] = useState(false)
  const [cur, setCur] = useState(0)
  const [playing, setPlaying] = useState(true)
  const [replay, setReplay] = useState(0)
  const [seen, setSeen] = useState(false)
  const section = useRef<HTMLDivElement | null>(null)
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([])

  useEffect(() => onView(section.current, () => setSeen(true), 9000, 0.05), [])
  useEffect(() => {
    if (!seen) return
    let live = true
    loadSampleReport().then((r) => { if (live) setReport(r) }).catch(() => { if (live) setFailed(true) })
    return () => { live = false }
  }, [seen])
  useEffect(() => {
    if (reduce || !playing || !report) return
    const t = window.setTimeout(() => setCur((c) => (c + 1) % SAMPLE_TABS.length), ADVANCE_MS)
    return () => window.clearTimeout(t)
  }, [cur, playing, reduce, report])

  const select = (i: number, focus = false) => {
    setCur(i)
    if (focus) tabRefs.current[i]?.focus()
  }
  const onKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const n = SAMPLE_TABS.length
    const to = e.key === 'ArrowRight' ? (i + 1) % n : e.key === 'ArrowLeft' ? (i - 1 + n) % n : e.key === 'Home' ? 0 : e.key === 'End' ? n - 1 : -1
    if (to < 0) return
    e.preventDefault()
    setPlaying(false) // the reader has taken over
    select(to, true)
  }

  const tab = SAMPLE_TABS[cur]
  const fragment = report ? tab.pick(report) : undefined
  return (
    <div ref={section}>
      <div className="hd-tabs-row">
        <div className="hd-tabs" role="tablist" aria-label="Report blocks">
          {SAMPLE_TABS.map((t, i) => (
            <button key={t.name} ref={(b) => { tabRefs.current[i] = b }} type="button" role="tab" id={`hd-tab-${i}`}
              aria-selected={i === cur} aria-controls="hd-tabpanel" tabIndex={i === cur ? 0 : -1} className="hd-tab"
              onClick={() => select(i)} onKeyDown={(e) => onKey(e, i)}>
              {t.name}
            </button>
          ))}
        </div>
        {!reduce && <PauseButton playing={playing} onToggle={() => setPlaying(!playing)} label="the report tabs" />}
      </div>
      <div className="hd-panel" id="hd-tabpanel" role="tabpanel" aria-labelledby={`hd-tab-${cur}`}>
        <div className="hd-pane">
          <div className="hd-pane-text">
            <div className="hd-pane-chap">{tab.chapter}</div>
            <div className="hd-pane-name">{tab.name}</div>
            <div className="hd-pane-sent">{tab.sentence}</div>
            <div className="hd-needs">Needs: {tab.needs}</div>
            <div style={{ marginTop: 18 }}><Link className="hd-sample-link" to="/sample">See the whole sample report</Link></div>
          </div>
          <div className="hd-pane-chart" onMouseEnter={() => setReplay((n) => n + 1)}
            role="img" aria-label={`${tab.name} chart from a sample workplace survey. ${tab.sentence}`}>
            {fragment ? <ChartBox fragment={fragment} replay={replay} />
              : <span className="hd-loading">{failed ? 'The sample chart could not be loaded.' : 'Loading the sample chart...'}</span>}
          </div>
        </div>
      </div>
    </div>
  )
}
