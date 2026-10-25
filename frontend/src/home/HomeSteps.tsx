import { animate, createScope, createTimeline, stagger, svg, utils, type JSAnimation, type Timeline } from 'animejs'
import { Fragment, useEffect, useRef, useState } from 'react'
import { Icon, StepIcon } from './homeArt'
import { PauseButton } from './homeFit'
import { onView, useReducedMotion, watchVisible } from './homeMotion'

// Five steps (hand-off section 3): cards zoom up into place, then each takes a turn (about 3.4s): it
// zooms in with a pulsing accent glow and plays its own icon loop while the others ease back and dim.
// Hover pauses, click jumps, off screen pauses. Ported from home_modern.py (steps_icons, SCRIPT_D).

const STEPS = [
  { icon: 'upload', title: 'Upload your sheet', text: 'Drop in an Excel or CSV file.', who: 'person', tag: 'You' },
  { icon: 'columns', title: 'Check the columns', text: 'Confirm what each column is.', who: 'person', tag: 'You' },
  { icon: 'themes', title: 'Find the themes', text: 'Similar answers are grouped by meaning, then named.', who: 'auto', tag: 'Automatic, you can edit' },
  { icon: 'find', title: 'See what stands out', text: 'Spot who feels differently, and how sure we are.', who: 'auto', tag: 'Automatic' },
  { icon: 'report', title: 'Get a visual report', text: 'A few clear blocks. Share or export.', who: 'person', tag: 'You share' },
] as const

const SEG = 3400
const GLOW = ['0 0 0 0 rgba(15,102,136,0), 0 10px 26px rgba(15,102,136,.12)', '0 0 0 7px rgba(15,102,136,.10), 0 16px 46px rgba(15,102,136,.34)']

export default function HomeSteps() {
  const reduce = useReducedMotion()
  const root = useRef<HTMLDivElement | null>(null)
  const api = useRef<{ jump: (i: number) => void; setPaused: (p: boolean) => void } | null>(null)
  const [active, setActive] = useState(-1)
  const [playing, setPlaying] = useState(true)

  useEffect(() => {
    const el = root.current
    if (!el) return
    const cleanups: Array<() => void> = []
    const scope = createScope({ root: el }).add(() => {
      const sts = Array.from(el.querySelectorAll<HTMLElement>('.hd-st')), arrs = Array.from(el.querySelectorAll<HTMLElement>('.hd-arr'))
      let act = -1, cyc = 0, live: Array<JSAnimation | Timeline> = [], started = false, hover = false, paused = false, visible = true
      const stopLive = () => { live.forEach((a) => { try { a.revert() } catch { /* already gone */ } }); live = []; window.clearTimeout(cyc) }
      const ICONS: Array<(c: HTMLElement) => void> = [
        (c) => { live.push(animate(c.querySelector('.u-arrow')!, { translateY: [16, -8], opacity: [0, 1, 1, 0], duration: 1300, loop: true, ease: 'outQuad' })) },
        (c) => {
          const d = svg.createDrawable(c.querySelector('.c-check')!)
          utils.set(d, { draw: '0 0' })
          live.push(createTimeline({ loop: true, loopDelay: 500, defaults: { ease: 'inOutQuad' } })
            .add(c.querySelector('.c-hl')!, { opacity: [0, 1], duration: 150 }, 0)
            .add(c.querySelector('.c-hl')!, { translateX: [0, 23, 46], duration: 1500 }, 0)
            .add(d, { draw: ['0 0', '0 1'], duration: 600 }, 1500))
        },
        (c) => {
          live.push(animate(c.querySelectorAll('.t-dot'), {
            translateX: (t: unknown) => [0, +((t as HTMLElement).dataset.dx ?? 0)], translateY: (t: unknown) => [0, +((t as HTMLElement).dataset.dy ?? 0)],
            opacity: [0, 1, 1, 0], duration: 1500, delay: stagger(110), loop: true, loopDelay: 400, ease: 'inOutQuad',
          }))
          live.push(animate(c.querySelectorAll('.t-circ'), { scale: [1, 1.08, 1], duration: 700, delay: stagger(140, { start: 900 }), loop: true, loopDelay: 800, ease: 'inOutQuad' }))
        },
        (c) => {
          live.push(createTimeline({ loop: true, loopDelay: 700, defaults: { ease: 'inOutSine' } })
            .add(c.querySelector('.f-lens')!, { translateX: [0, 44], duration: 1700 }, 0)
            .add(c.querySelector('.f-hi')!, { fillOpacity: [0.25, 1], duration: 300 }, 1400))
        },
        (c) => { live.push(animate(c.querySelectorAll('.r-bar'), { scaleY: [0, 1], duration: 700, delay: stagger(160), loop: true, loopDelay: 1500, ease: 'outBack' })) },
      ]
      function activate(i: number) {
        stopLive(); act = i; setActive(i)
        sts.forEach((c, n) => {
          const on = n === i
          c.style.zIndex = on ? '2' : '1'
          animate(c, { scale: on ? 1.07 : 0.97, translateY: on ? -8 : 0, opacity: on ? 1 : 0.62, duration: 1100, ease: 'outExpo' })
          animate(c.querySelector('.hd-ico')!, { scale: on ? 1.14 : 1, duration: 1100, ease: 'outExpo' })
          c.style.boxShadow = 'none'
          ;(c.querySelector('.hd-ico') as HTMLElement).style.boxShadow = 'none'
        })
        live.push(animate(sts[i], { boxShadow: GLOW, duration: 1100, alternate: true, loop: true, ease: 'inOutSine' }))
        live.push(animate(sts[i].querySelector('.hd-ico')!, { boxShadow: ['0 0 0 0 rgba(15,102,136,0)', '0 0 22px 4px rgba(15,102,136,.28)'], duration: 1100, alternate: true, loop: true, ease: 'inOutSine' }))
        live.push(animate(sts[i].querySelector('.hd-num')!, { scale: [1, 1.25, 1], duration: 500, ease: 'outBack' }))
        ICONS[i](sts[i])
        if (i > 0) animate(arrs[i - 1], { translateX: [0, 8, 0], duration: 500, ease: 'outQuad' })
        if (!hover && !paused && visible) cyc = window.setTimeout(() => activate((i + 1) % sts.length), SEG)
      }
      const loopStart = () => { if (reduce || started || paused) return; started = true; activate(0) }
      utils.set(sts, { opacity: 0, y: 40, scale: 0.9 }); utils.set(arrs, { opacity: 0 })
      cleanups.push(onView(el, () => {
        animate(sts, { opacity: [0, 1], y: [40, 0], scale: [0.9, 1], duration: reduce ? 1 : 1000, delay: stagger(180), ease: 'outExpo' })
        animate(arrs, { opacity: [0, 1], duration: reduce ? 1 : 400, delay: stagger(260, { start: 350 }) })
        const t = window.setTimeout(loopStart, reduce ? 0 : 2000)
        cleanups.push(() => window.clearTimeout(t))
      }, 5000))
      const enter = () => { hover = true; window.clearTimeout(cyc) }
      const leave = () => { hover = false; if (started && act >= 0 && !paused) activate(act) }
      el.addEventListener('mouseenter', enter); el.addEventListener('mouseleave', leave)
      cleanups.push(() => { el.removeEventListener('mouseenter', enter); el.removeEventListener('mouseleave', leave) })
      cleanups.push(watchVisible(el, (v) => {
        visible = v
        if (!started || paused) return
        if (v) { if (!live.length) activate(Math.max(act, 0)) } else stopLive()
      }))
      cleanups.push(stopLive)
      api.current = {
        jump: (i) => { if (reduce) return; started = true; activate(i) },
        setPaused: (p) => {
          paused = p
          if (p) stopLive()
          else if (started) activate(Math.max(act, 0))
          else loopStart()
        },
      }
    })
    return () => { cleanups.forEach((c) => c()); api.current = null; scope.revert() }
  }, [reduce])

  const toggle = () => { api.current?.setPaused(playing); setPlaying(!playing) }

  return (
    <>
      <div ref={root} className="hd-steps">
        {STEPS.map((s, i) => (
          <Fragment key={s.title}>
            {i > 0 && (
              <div className="hd-arr" aria-hidden="true">
                <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
              </div>
            )}
            <button type="button" className={`hd-st${active === i ? ' is-on' : ''}`} onClick={() => api.current?.jump(i)}
              aria-label={`Step ${i + 1}: ${s.title}. ${s.text} ${s.tag}.`}>
              <div className="hd-st-top">
                <div className="hd-ico"><StepIcon name={s.icon} /></div>
                <div className="hd-num">{i + 1}</div>
              </div>
              <div className="hd-st-t">{s.title}</div>
              <div className="hd-st-b">{s.text}</div>
              <div className="hd-who"><Icon name={s.who} size={18} sw={4} />{s.tag}</div>
            </button>
          </Fragment>
        ))}
      </div>
      {!reduce && <div className="hd-steps-ctl"><PauseButton playing={playing} onToggle={toggle} label="the steps animation" /></div>}
    </>
  )
}
