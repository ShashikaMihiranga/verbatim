import { animate, stagger, svg, utils, type JSAnimation } from 'animejs'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import { Link } from 'react-router-dom'
import { BLOCK_TABS } from './homeBlocks'
import { useReducedMotion } from './homeMotion'

// What is in a report (hand-off section 4): six pill tabs and one panel showing the active block: chapter,
// name, one sentence, a "Needs" chip and the mockup's example chart, which builds itself when shown (cells
// pop, bars grow, strokes draw, labels fade; home_blocks.py CHART_JS). Tabs auto-advance every 6s; hover
// replays the chart; arrow keys move between tabs; reduced motion shows finished charts and no advance.

const ADVANCE_MS = 6000

function reveal(el: Element): JSAnimation[] {
  const d = Array.from(el.querySelectorAll<SVGGeometryElement>('.cb-d')), r = el.querySelectorAll('.cb-r'), rx = el.querySelectorAll('.cb-rx')
  const c = el.querySelectorAll('.cb-c'), f = el.querySelectorAll('.cb-f')
  const drawables = d.length ? svg.createDrawable(d) : []
  utils.set(drawables, { draw: '0 0' }); utils.set(r, { scaleY: 0 }); utils.set(rx, { scaleX: 0 })
  utils.set(c, { scale: 0, opacity: 0 }); utils.set(f, { opacity: 0 })
  return [
    animate(drawables, { draw: ['0 0', '0 1'], duration: 1000, delay: stagger(70), ease: 'inOutQuad' }),
    animate(r, { scaleY: [0, 1], duration: 700, delay: stagger(90, { start: 200 }), ease: 'outBack' }),
    animate(rx, { scaleX: [0, 1], duration: 750, delay: stagger(80, { start: 150 }), ease: 'outQuart' }),
    animate(c, { scale: [0, 1], opacity: [0, 1], duration: 520, delay: stagger(28, { start: 150, grid: [5, 6], from: 'first' }), ease: 'outBack' }),
    animate(f, { opacity: [0, 1], duration: 500, delay: 700 }),
  ]
}

export default function ReportTabs() {
  const reduce = useReducedMotion()
  const [cur, setCur] = useState(0)
  const [held, setHeld] = useState(false) // pointer or keyboard focus on the tabs: stop auto-advancing
  const [taken, setTaken] = useState(false) // the reader moved with the keys: stop for good
  const [replay, setReplay] = useState(0)
  const chart = useRef<SVGSVGElement | null>(null)
  const tabRefs = useRef<Array<HTMLButtonElement | null>>([])

  useEffect(() => {
    if (!chart.current || reduce) return
    const anims = reveal(chart.current)
    return () => anims.forEach((a) => a.revert())
  }, [cur, replay, reduce])
  useEffect(() => {
    if (reduce || held || taken) return
    const t = window.setTimeout(() => setCur((c) => (c + 1) % BLOCK_TABS.length), ADVANCE_MS)
    return () => window.clearTimeout(t)
  }, [cur, held, taken, reduce])

  const onKey = (e: KeyboardEvent<HTMLButtonElement>, i: number) => {
    const n = BLOCK_TABS.length
    const to = e.key === 'ArrowRight' ? (i + 1) % n : e.key === 'ArrowLeft' ? (i - 1 + n) % n : e.key === 'Home' ? 0 : e.key === 'End' ? n - 1 : -1
    if (to < 0) return
    e.preventDefault()
    setTaken(true) // the reader has taken over
    setCur(to)
    tabRefs.current[to]?.focus()
  }

  const tab = BLOCK_TABS[cur]
  return (
    <div onMouseEnter={() => setHeld(true)} onMouseLeave={() => setHeld(false)} onFocus={() => setHeld(true)} onBlur={() => setHeld(false)}>
      <div className="hd-tabs-row">
        <div className="hd-tabs" role="tablist" aria-label="Report blocks">
          {BLOCK_TABS.map((t, i) => (
            <button key={t.key} ref={(b) => { tabRefs.current[i] = b }} type="button" role="tab" id={`hd-tab-${i}`}
              aria-selected={i === cur} aria-controls="hd-tabpanel" tabIndex={i === cur ? 0 : -1} className="hd-tab"
              onClick={() => setCur(i)} onKeyDown={(e) => onKey(e, i)}>
              {t.name}
            </button>
          ))}
        </div>
      </div>
      <div className="hd-panel" id="hd-tabpanel" role="tabpanel" aria-labelledby={`hd-tab-${cur}`}>
        <div className="hd-pane">
          <div className="hd-pane-text">
            <div className="hd-pane-chap">{tab.chapter}</div>
            <div className="hd-pane-name">{tab.name}</div>
            <div className="hd-pane-sent">{tab.sentence}</div>
            <div className="hd-needs">Needs: {tab.needs}</div>
          </div>
          <div className="hd-pane-chart" onMouseEnter={() => setReplay((n) => n + 1)}>
            {/* A static example drawing from homeBlocks.ts: our own markup, nobody's data. */}
            <svg key={tab.key} ref={chart} className="hd-blockchart" viewBox="0 0 480 300" role="img" aria-label={`${tab.name} example. ${tab.sentence}`}
              style={{ overflow: 'visible', fill: 'none', strokeLinecap: 'round', strokeLinejoin: 'round' }}
              dangerouslySetInnerHTML={{ __html: tab.svg }} />
          </div>
        </div>
      </div>
      <p className="hd-sample-row"><Link className="hd-sample-link" to="/sample">See a real report built from a workplace survey</Link></p>
    </div>
  )
}
