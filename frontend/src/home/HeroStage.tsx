import { createScope, createTimeline, animate, stagger, utils, type Timeline } from 'animejs'
import { useEffect, useRef } from 'react'
import { Fit } from './homeFit'
import { screenScale, useReducedMotion } from './homeMotion'

// Hero stage (hand-off section 2): two scenes take turns. Scene 1, a sheet becomes a report; scene 2,
// phrases are highlighted and sorted into theme cards. Each plays once forward, holds, cross-fades, and
// is rebuilt from a clean state every cycle. Ported from home_modern.py (stage_d_combined, SCRIPT_D_HERO2).

const TH: Record<string, string> = { t1: '#3f8a57', t2: '#2680c7', t3: '#26cbd8', t4: '#43b895', t5: '#0f6688' }
const TINT: Record<string, string> = { t1: 'rgba(63,138,87,.16)', t2: 'rgba(38,128,199,.16)', t3: 'rgba(38,203,216,.2)', t4: 'rgba(67,184,149,.2)', t5: 'rgba(15,102,136,.16)' }
const ON_DARK = new Set(['t1', 't2', 't5'])

const ANSWERS: Array<[string, string]> = [
  ['Too expensive for my budget', 't1'], ['No place to charge at home', 't2'], ['Not sure it fits what I need', 't4'],
  ['Range worries me on long trips', 't3'], ['Waiting lists are far too long', 't5'], ['Battery replacement costs scare me', 't1'],
  ['Cannot install a home charger', 't2'], ['Prices keep dropping, so I wait', 't1'],
]
const TILES: Array<[string, number, number, number, number, string]> = [
  ['Cost', 0, 0, 150, 88, 't1'], ['Charging', 156, 0, 134, 88, 't2'], ['Range', 0, 94, 92, 56, 't3'],
  ['Not needed', 98, 94, 100, 56, 't4'], ['Doubts', 204, 94, 86, 56, 't5'],
]
const TILE_OF = [0, 1, 3, 2, 4, 0, 1, 0]
const BARS: Array<[number, string]> = [[58, 't1'], [86, 't2'], [46, 't3'], [32, 't4']]

type Part = [string, string | null]
const CARDS: Part[][] = [
  [['I would buy one, but there is no way to ', null], ['charge at home', 'Charging'], [' and the ', null], ['upfront price', 'Cost'], [' is too high.', null]],
  [['The ', null], ['battery range', 'Range'], [' is fine for the city, but it is ', null], ['too expensive', 'Cost'], [' for what it is.', null]],
  [['There are ', null], ['few public chargers', 'Charging'], [' near me and I am ', null], ['worried about range', 'Range'], [' on long trips.', null]],
]
const COLS: Array<[string, string]> = [['Cost', 't1'], ['Charging', 't2'], ['Range', 't3']]
const COL_THEME: Record<string, string> = { Cost: 't1', Charging: 't2', Range: 't3' }

export default function HeroStage() {
  const reduce = useReducedMotion()
  const root = useRef<HTMLDivElement | null>(null)
  const control = useRef<{ pause: () => void; play: () => void } | null>(null)

  useEffect(() => {
    const el = root.current
    if (!el) return
    const timers: number[] = []
    const later = (fn: () => void, ms: number) => { timers.push(window.setTimeout(fn, ms)) }
    const $$ = (s: string, r: ParentNode = el) => Array.from(r.querySelectorAll<HTMLElement>(s))
    const $ = (s: string) => el.querySelector<HTMLElement>(s)!
    let cycle = !reduce
    let heroTl: Timeline | null = null
    let pending: (() => void) | null = null // the next scene, held while paused

    const scope = createScope({ root: el }).add(() => {
      const s1 = $('.hd-s1'), s2 = $('.hd-s2'), f = $('.hd-f')
      const k = screenScale(s1)
      // ---------- scene 1: sheet becomes a report card
      const rows = $$('.hd-row'), tiles = $$('.hd-tile'), bchart = $$('.hd-bchart'), scan = $('.hd-scan')
      const r1 = s1.getBoundingClientRect()
      const c1 = (n: HTMLElement): [number, number] => {
        const r = n.getBoundingClientRect()
        return [(r.left - r1.left + r.width / 2) / k, (r.top - r1.top + r.height / 2) / k]
      }
      const dots = rows.map((r) => {
        const d = document.createElement('div')
        d.className = 'hd-dot'
        d.style.background = TH[r.dataset.c!]
        s1.appendChild(d)
        return d
      })
      const start = rows.map(c1), end = rows.map((_, i) => c1(tiles[TILE_OF[i]]))
      const buildD = (auto = true) => {
        utils.set(rows, { opacity: 0, y: 12, backgroundColor: 'rgba(255,255,255,0)' })
        rows.forEach((r) => utils.set(r.querySelector('.hd-rbar')!, { backgroundColor: 'rgba(0,0,0,0)' }))
        utils.set(tiles, { scale: 0, opacity: 0 }); utils.set(bchart, { scaleY: 0 })
        utils.set('.hd-rtitle', { opacity: 0, y: 8 }); utils.set('.hd-badge', { scale: 0.5, opacity: 0 })
        utils.set('.hd-report', { opacity: 0.55 }); utils.set(scan, { opacity: 0, y: 0 })
        dots.forEach((d, i) => utils.set(d, { x: start[i][0] - 8 + 70, y: start[i][1] - 8, scale: 0, opacity: 0 }))
        const tl = createTimeline({ autoplay: auto, defaults: { ease: 'inOutQuad' }, onComplete: () => next(toF, 1900) })
        tl.add(rows, { opacity: [0, 1], y: [12, 0], duration: 500, delay: stagger(70) }, 0).add(scan, { opacity: [0, 1], duration: 300 }, 900)
        rows.forEach((r, i) => {
          tl.add(scan, { y: i * 52, duration: 280, ease: 'outQuad' }, 950 + i * 380)
            .add(r.querySelector('.hd-rbar')!, { backgroundColor: ['rgba(0,0,0,0)', TH[r.dataset.c!]], duration: 260 }, 1000 + i * 380)
            .add(r, { backgroundColor: ['rgba(255,255,255,0)', TINT[r.dataset.c!]], duration: 260 }, 1000 + i * 380)
        })
        tl.add(scan, { opacity: [1, 0], duration: 300 }, 4100).add('.hd-report', { opacity: [0.55, 1], duration: 500 }, 4000)
          .add('.hd-rtitle', { opacity: [0, 1], y: [8, 0], duration: 600 }, 4300)
        dots.forEach((d, i) => {
          tl.add(d, { opacity: [0, 1], scale: [0, 1], duration: 200 }, 4200 + i * 70)
            .add(d, { x: end[i][0] - 8, y: end[i][1] - 8, duration: 1100, ease: 'inOutCubic' }, 4350 + i * 70)
            .add(d, { opacity: [1, 0], scale: [1, 0.4], duration: 250 }, 5380 + i * 70)
        })
        tl.add(tiles, { scale: [0, 1], opacity: [0, 1], duration: 520, delay: stagger(110), ease: 'outBack' }, 5300)
          .add(rows, { opacity: [1, 0.35], duration: 600 }, 5400)
          .add(bchart, { scaleY: [0, 1], duration: 700, delay: stagger(100), ease: 'outBack' }, 6100)
          .add('.hd-badge', { scale: [0.5, 1], opacity: [0, 1], duration: 450, ease: 'outBack' }, 6800)
        return tl
      }
      // ---------- scene 2: highlight phrases, then sort them into theme cards (forward only)
      const cards = $$('.hd-card', f), cols = $$('.hd-col', f)
      const col = (n: string) => cols.find((c) => c.dataset.th === n)!
      const TC: Record<string, [string, string]> = { Cost: ['#3f8a57', '#ffffff'], Charging: ['#2680c7', '#ffffff'], Range: ['#26cbd8', '#12303a'] }
      const rf = f.getBoundingClientRect(), slotCount: Record<string, number> = { Cost: 0, Charging: 0, Range: 0 }
      const chips: Array<{ chip: HTMLElement; card: HTMLElement; th: string; sx: number; sy: number; tx: number; ty: number }> = []
      cards.forEach((card) => $$('.hd-hl', card).forEach((h) => {
        const th = h.dataset.th!, cr = col(th).getBoundingClientRect(), hr = h.getBoundingClientRect(), n = slotCount[th]++
        const chip = document.createElement('div')
        chip.className = 'hd-chip'
        chip.textContent = h.textContent
        chip.setAttribute('aria-hidden', 'true')
        chip.style.background = TC[th][0]; chip.style.color = TC[th][1]
        f.appendChild(chip)
        chips.push({ chip, card, th, sx: (hr.left - rf.left) / k - 6, sy: (hr.top - rf.top) / k - 4, tx: (cr.left - rf.left) / k + 14, ty: (cr.top - rf.top) / k + 62 + n * 44 })
      }))
      const buildF = () => {
        utils.set(cards, { opacity: 0, y: 14 }); utils.set($$('.hd-hl-bg', f), { scaleX: 0 }); utils.set($$('.hd-cnt', f), { scale: 1 })
        cols.forEach((c) => { c.querySelector('.hd-cnt')!.textContent = '0' })
        chips.forEach((c) => utils.set(c.chip, { x: c.sx, y: c.sy, opacity: 0, scale: 0.9 }))
        const counts: Record<string, number> = { Cost: 0, Charging: 0, Range: 0 }
        const tl = createTimeline({ defaults: { ease: 'inOutQuad' }, onComplete: () => next(toD, 2400) })
        cards.forEach((card, ci) => {
          const t0 = ci * 3200
          tl.add(card, { opacity: [0, 1], y: [14, 0], duration: 500 }, t0)
          $$('.hd-hl-bg', card).forEach((b, n) => tl.add(b, { scaleX: [0, 1], duration: 500, ease: 'outQuad' }, t0 + 700 + n * 350))
          chips.filter((c) => c.card === card).forEach((c, n) => {
            const t1 = t0 + 1700 + n * 330, cnt = col(c.th).querySelector<HTMLElement>('.hd-cnt')!
            counts[c.th]++
            const o = { n: counts[c.th] - 1 }, to = counts[c.th]
            tl.add(c.chip, { opacity: [0, 1], scale: [0.9, 1], duration: 160 }, t1)
              .add(c.chip, { x: c.tx, y: c.ty, duration: 900, ease: 'inOutCubic' }, t1)
              .add(cnt, { scale: [1, 1.25, 1], duration: 360 }, t1 + 800)
              .add(o, { n: to, duration: 200, onUpdate: () => { cnt.textContent = String(Math.round(o.n)) } }, t1 + 800)
          })
          if (ci < cards.length - 1) tl.add(card, { opacity: [1, 0], y: [0, -10], duration: 400 }, t0 + 2800)
        })
        return tl
      }
      // ---------- take turns
      const crossfade = (a: HTMLElement, b: HTMLElement) => {
        animate(a, { opacity: 0, duration: 450, ease: 'linear' }); animate(b, { opacity: 1, duration: 450, ease: 'linear' })
      }
      function next(step: () => void, ms: number) { later(() => { if (cycle) step(); else pending = step }, ms) }
      function toF() { crossfade(s1, s2); later(() => { heroTl?.revert(); heroTl = buildF() }, 500) }
      function toD() { crossfade(s2, s1); later(() => { heroTl?.revert(); heroTl = buildD() }, 500) }
      utils.set(s2, { opacity: 0 })
      if (reduce) buildD(false).seek(7600)
      else heroTl = buildD()
      control.current = {
        pause: () => { cycle = false; heroTl?.pause() },
        play: () => {
          cycle = true
          if (heroTl && !heroTl.completed) heroTl.play()
          const step = pending
          pending = null
          step?.()
        },
      }
    })
    return () => { timers.forEach((t) => window.clearTimeout(t)); control.current = null; scope.revert() }
  }, [reduce])

  // No pause button (user's call, 2026-10-26): pointing at the stage or focusing into it pauses the scenes.
  const hold = () => { if (!reduce) control.current?.pause() }
  const resume = () => { if (!reduce) control.current?.play() }

  return (
    <div className="hd-hero-stage" onMouseEnter={hold} onMouseLeave={resume} onFocus={hold} onBlur={resume}>
      <Fit w={720} h={560}>
        <div ref={root} role="img" aria-label="Animation: a sheet of written answers becomes a short report, then phrases from answers are highlighted and sorted into themes."
          style={{ position: 'relative', width: 720, height: 560 }}>
          <div className="hd-s1" style={{ position: 'absolute', inset: 0 }} aria-hidden="true">
            <div className="hd-sheet">
              <div className="hd-sheet-head">Answer</div>
              <div>
                {ANSWERS.map(([t, c]) => (
                  <div key={t} className="hd-row" data-c={c}><span className="hd-rbar" />{t}</div>
                ))}
              </div>
              <div className="hd-scan" />
            </div>
            <div className="hd-report">
              <div className="hd-cap">Report</div>
              <div className="hd-rtitle">Cost and Charging are the biggest reasons.</div>
              <div className="hd-tiles">
                {TILES.map(([n, x, y, w, h, c]) => (
                  <div key={n} className="hd-tile" style={{ left: x, top: y, width: w, height: h, background: TH[c], color: ON_DARK.has(c) ? '#ffffff' : '#12303a' }}>{n}</div>
                ))}
              </div>
              <div className="hd-bars">
                {BARS.map(([h, c], i) => <div key={c} className="hd-bchart" style={{ left: i * 74 + 6, height: h, background: TH[c] }} />)}
              </div>
              <div className="hd-rfoot"><span>From the written answers</span><div className="hd-badge">&#10003; Solid</div></div>
            </div>
          </div>
          <div className="hd-s2" style={{ position: 'absolute', inset: 0, opacity: 0 }} aria-hidden="true">
            <div className="hd-f" style={{ position: 'relative', width: 720, height: 560 }}>
              <div style={{ position: 'absolute', left: 0, top: 70, right: 0, height: 170 }}>
                {CARDS.map((parts, i) => (
                  <div key={i} className="hd-card">
                    {parts.map(([txt, th], j) => th ? (
                      <span key={j} className="hd-hl" data-th={th}><i className="hd-hl-bg" style={{ background: TH[COL_THEME[th]] }} />{txt}</span>
                    ) : <span key={j}>{txt}</span>)}
                    <div className="hd-cap" style={{ marginTop: 14 }}>Answer {i + 1}</div>
                  </div>
                ))}
              </div>
              <div className="hd-cols">
                {COLS.map(([n, c]) => (
                  <div key={n} className="hd-col" data-th={n}>
                    <div className="hd-col-head">
                      <span style={{ color: TH[c] }}>{n}</span>
                      <span className="hd-cnt" style={{ background: TH[c], color: c === 't3' ? '#12303a' : '#ffffff' }}>0</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </Fit>
    </div>
  )
}
