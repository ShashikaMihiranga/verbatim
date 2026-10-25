import { animate, createScope, createTimeline, stagger, svg, utils, type Timeline } from 'animejs'
import { useEffect, useRef, useState } from 'react'
import { Fit } from './homeFit'
import { onView, useReducedMotion } from './homeMotion'
import {
  DB_CHIPS, EDIT_CHIPS, ICO, MAP_COLOURS, MAP_DOTS, MAP_H, MAP_STAGES, MAP_W, NODES, OTHER_STEPS, PLAIN, REPORT_BARS, SUBSTEPS,
  TECH, WIRES, ZONES, type NodeId,
} from './howItWorksData'

// "How Verbatim works" (hand-off section 7): six steps through three zones. A step lights its cards, draws
// its wires and sends glyph packets along them; the Web app card's report fills in as the backend answers.
// Auto-plays once it scrolls into view and loops; chips, previous/next and Left/Right jump. Ported from
// gen_howitworks.py (SCRIPT). Below 1100px wide the page shows the steps as a list instead (HomePage).

const GLY: Record<string, string> = {
  key: '<circle cx="-3" cy="0" r="3.4"/><path d="M0.4 0h8M5 0v3.4"/>', file: '<path d="M-5 -6h7l4 4v10h-11z"/><path d="M2 -6v4h4"/>',
  grid: '<rect x="-7" y="-5" width="14" height="11" rx="1.5"/><path d="M-7 0h14M-2 -5v11"/>', text: '<path d="M-7 -5h14v8h-8l-3 3v-3h-3z"/>',
  masked: '<circle cx="-5" cy="0.5" r="1.7"/><circle cx="0" cy="0.5" r="1.7"/><circle cx="5" cy="0.5" r="1.7"/>',
  vectors: '<circle cx="-5" cy="-3" r="1.6"/><circle cx="0" cy="3" r="1.6"/><circle cx="5" cy="-2" r="1.6"/><path d="M-5 -3l5 6 5-5"/>',
  themes: '<circle cx="-3" cy="-1" r="4"/><circle cx="4" cy="2" r="3"/>', numbers: '<path d="M-6 -3h12M-6 1h12M-6 5h7"/>', report: '<path d="M-5 5v-5M0 5V-4M5 5V1"/>',
}
const NS = 'http://www.w3.org/2000/svg'
const LOCK0 = 'One report build or theme rebuild per column at a time'
const dash = (st: string) => (st === 'dash' ? '6 7' : st === 'dot' ? '2 7' : undefined)

function Glyph({ name, size = 30, sw = 2.6, color = 'var(--accent)' }: { name: string; size?: number; sw?: number; color?: string }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" fill="none" stroke={color} strokeWidth={sw} strokeLinecap="round" strokeLinejoin="round"
      aria-hidden="true" style={{ flex: 'none' }} dangerouslySetInnerHTML={{ __html: ICO[name] }} />
  )
}

function NodeCard({ id, tech }: { id: NodeId; tech: boolean }) {
  const [x, y, w, h] = NODES[id]
  const [t, s] = (tech ? TECH : PLAIN)[id]
  return (
    <div className={`dg-n${id === 'themes' ? ' is-col' : ''}`} data-id={id}
      style={{ left: x, top: y, width: w, height: h, padding: id === 'themes' || id === 'jobs' ? '10px 14px' : '12px 14px' }}>
      <div className="dg-n-head"><Glyph name={id} /><div className="dg-t">{t}</div></div>
      <div className="dg-s">{s}</div>
      {id === 'browser' && (
        <div>
          <div className="dg-rep" style={{ marginTop: 8, border: '1.5px solid var(--line)', borderRadius: 12, padding: '8px 9px', background: 'var(--bg)' }}>
            <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '.08em', color: 'var(--muted)' }}>YOUR REPORT</div>
            {REPORT_BARS.map(([l, bw]) => (
              <div key={l} style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 4 }}>
                <span style={{ fontSize: 10, fontWeight: 600, color: 'var(--muted)', width: 58, flex: 'none', whiteSpace: 'nowrap' }}>{l}</span>
                <div style={{ flex: 1, height: 8, borderRadius: 4, background: 'var(--line)', overflow: 'hidden' }}>
                  <div className="rp-bar" data-w={bw} style={{ height: 8, width: '0%', background: 'var(--accent)', borderRadius: 4 }} />
                </div>
              </div>
            ))}
            <div className="dg-amap" style={{ marginTop: 8, opacity: 0 }}>
              <svg width="100%" viewBox="0 0 132 98" style={{ height: 62 }} aria-hidden="true">
                {MAP_DOTS.map(([cx, cy, g]) => <circle key={`${cx}-${cy}`} className="dg-dot" data-g={g} cx={cx} cy={cy} r={3.2} fill="#9db3b6" style={{ opacity: 0 }} />)}
              </svg>
              <div style={{ fontSize: 9.5, fontWeight: 600, color: 'var(--muted)' }}>Answer map by theme</div>
            </div>
            <div style={{ marginTop: 8 }}>
              <div className="rp-ln" style={{ height: 7, borderRadius: 3, background: '#d3e0df', width: '100%' }} />
              <div className="rp-ln" style={{ height: 7, borderRadius: 3, background: '#d3e0df', width: '72%', marginTop: 4 }} />
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, marginTop: 6 }}>
                <svg width="86" height="30" viewBox="0 0 86 30" aria-hidden="true">
                  <path className="rp-trend" d="M2 24 L20 18 L38 21 L56 9 L72 12 L84 4" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
                <span className="rp-tag" style={{ opacity: 0, fontSize: 10, fontWeight: 600, padding: '1px 7px', borderRadius: 8, background: 'var(--surface)', border: '1.5px solid var(--accent)', color: 'var(--accent)' }}>&#10003; Solid</span>
              </div>
            </div>
          </div>
          <div style={{ marginTop: 8, border: '1.5px solid var(--line)', borderRadius: 12, padding: '8px 9px 4px', background: 'var(--bg)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 5, marginBottom: 2 }}>
              <Glyph name="other" size={12} sw={4} color="var(--muted)" />
              <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: '.08em', color: 'var(--muted)' }}>LOOK INSIDE OTHER</div>
            </div>
            {OTHER_STEPS.map(([a, who, icn], i) => (
              <div key={a} style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 7, height: 38 }}>
                {i < OTHER_STEPS.length - 1 && (
                  <div style={{ position: 'absolute', left: 10, top: 30, height: 16, width: 2, background: 'var(--line)', borderRadius: 1, overflow: 'hidden' }}>
                    <div className="dg-obar" style={{ width: 2, height: '0%', background: '#7fb6cc' }} />
                  </div>
                )}
                <span className="dg-on" style={{ width: 22, height: 22, borderRadius: 11, border: '1.5px solid #d3e0df', background: '#fff', color: '#9fbfca', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flex: 'none', position: 'relative', zIndex: 1 }}>
                  <Glyph name={icn} size={13} sw={3.4} color="currentColor" />
                </span>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 10.5, fontWeight: 600, color: 'var(--ink)', lineHeight: 1.2, whiteSpace: 'nowrap' }}>{a}</div>
                  <span style={{ display: 'inline-block', marginTop: 1, fontSize: 9.5, fontWeight: 600, padding: '0 6px', borderRadius: 8, background: 'var(--surface)', color: 'var(--muted)' }}>{who}</span>
                </div>
                <span className="dg-ocnt" style={{ fontSize: 11, fontWeight: 700, color: '#3f8a57', width: 10, textAlign: 'center' }} />
              </div>
            ))}
          </div>
          <div className="dg-edits" style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 8, opacity: 0 }}>
            {EDIT_CHIPS.map((c) => (
              <span key={c} className="dg-ech" style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 10, border: '1.5px solid var(--line)', color: 'var(--ink)', background: 'var(--surface)' }}>{c}</span>
            ))}
          </div>
        </div>
      )}
      {id === 'themes' && (
        <div style={{ flex: 1, minHeight: 0, marginTop: 12, display: 'flex', flexDirection: 'column', justifyContent: 'space-between', gap: 5 }}>
          {SUBSTEPS.map(([a, b], i) => (
            <div key={a} className="dg-sub" style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', borderRadius: 10, fontSize: 12, fontWeight: 500, color: 'var(--muted)' }}>
              <span style={{ width: 18, height: 18, borderRadius: 9, border: '1.5px solid currentColor', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', fontSize: 10.5, fontWeight: 600, flex: 'none' }}>{i + 1}</span>
              <span>{tech ? a : b}</span>
            </div>
          ))}
        </div>
      )}
      {id === 'jobs' && (
        <>
          <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 10 }}>
            <div style={{ flex: 1, height: 8, borderRadius: 4, background: 'var(--line)', overflow: 'hidden' }}>
              <div className="dg-bar" style={{ height: 8, width: '0%', background: 'var(--accent)', borderRadius: 4 }} />
            </div>
            <span className="dg-pct" style={{ fontSize: 12.5, fontWeight: 600, width: 34, textAlign: 'right', color: 'var(--muted)' }}>0%</span>
          </div>
          <div className="dg-jobstep" style={{ fontSize: 12.5, fontWeight: 600, marginTop: 5, minHeight: 17 }}>Waiting for a job</div>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 6, marginTop: 6, padding: '5px 8px', borderRadius: 9, background: 'var(--bg)', fontSize: 11.5, lineHeight: 1.3, color: 'var(--ink)' }}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" style={{ flex: 'none', marginTop: 1 }} aria-hidden="true">
              <rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 018 0v3" />
            </svg>
            <span className="dg-locktxt">{LOCK0}</span>
          </div>
        </>
      )}
      {id === 'db' && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 8 }}>
          {DB_CHIPS.map((c) => <span key={c} className="dg-dchip" data-k={c} style={{ fontSize: 11.5, fontWeight: 500, padding: '2px 8px', borderRadius: 10, background: 'var(--bg)', color: 'var(--ink)' }}>{c}</span>)}
        </div>
      )}
      {id === 'profile' && (
        <div className="dg-mask" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 6, padding: '3px 10px', borderRadius: 12, background: 'color-mix(in srgb,var(--accent) 10%,var(--surface))', fontSize: 12, fontWeight: 600, color: 'var(--accent)' }}>
          &#8226;&#8226;&#8226; masks personal details
        </div>
      )}
    </div>
  )
}

export default function HowItWorksMap() {
  const reduce = useReducedMotion()
  const root = useRef<HTMLDivElement | null>(null)
  const map = useRef<HTMLDivElement | null>(null)
  const api = useRef<{ go: (i: number) => void; setPlaying: (p: boolean) => void } | null>(null)
  const [tech, setTech] = useState(false)
  const [cur, setCur] = useState(0)
  const [started, setStarted] = useState(false)

  useEffect(() => {
    const el = map.current
    if (!el) return
    let stopView = () => {}
    const scope = createScope({ root: el }).add(() => {
      const $ = <T extends Element = HTMLElement>(s: string) => el.querySelector<T>(s)!
      const $$ = <T extends Element = HTMLElement>(s: string) => Array.from(el.querySelectorAll<T>(s))
      const nodes: Record<string, HTMLElement> = {}
      $$('.dg-n').forEach((n) => { nodes[n.dataset.id!] = n })
      const conns: Record<string, SVGPathElement> = {}
      $$<SVGPathElement>('.dg-c').forEach((c) => { conns[c.dataset.id!] = c })
      const drawables: Record<string, ReturnType<typeof svg.createDrawable>> = {}
      Object.keys(conns).forEach((k) => { if (conns[k].dataset.k === 'solid') drawables[k] = svg.createDrawable(conns[k]) })
      const pkLayer = $<SVGGElement>('.dg-packets'), amb = $<SVGGElement>('.dg-amb')
      const chips = Array.from(root.current?.querySelectorAll<HTMLElement>('.dg-chip-s') ?? [])
      let i0 = 0, tl: Timeline | null = null, timer = 0, isPlaying = !reduce, ambientOn = false, begun = false

      const ambient = () => {
        if (reduce || ambientOn) return
        ambientOn = true
        // A pale bubble drifts along every route, in the direction the data goes, with a fading trail.
        $$<SVGPathElement>('.dg-gh').forEach((p, k) => {
          if (typeof p.getTotalLength !== 'function') return
          const g = document.createElementNS(NS, 'g')
          g.style.opacity = '0'
          g.innerHTML = '<circle r="7" fill="#5aa7c2" fill-opacity=".10"/><circle r="2.2" fill="#5aa7c2" fill-opacity=".55"/>'
          const len = p.getTotalLength(), dur = Math.max(2400, len * 10), del = (k * 617) % 3400, mp = svg.createMotionPath(p)
          const N = 18, tlen = Math.min(380, len * 0.9), seg = tlen / N, tail = (tlen * dur) / len, ld = Math.max(1800, tail + 300) + ((k * 331) % 1200)
          for (let i = 0; i < N; i++) {
            const o = document.createElementNS(NS, 'path')
            o.setAttribute('d', p.getAttribute('d')!)
            o.style.cssText = `fill:none;stroke:#5aa7c2;stroke-width:2;stroke-opacity:${(0.4 - i * 0.021).toFixed(2)};stroke-dasharray:${seg.toFixed(2)} ${Math.ceil(len + tlen * 3)};stroke-dashoffset:${((i + 1) * seg).toFixed(2)}`
            amb.appendChild(o)
            animate(o, { strokeDashoffset: [(i + 1) * seg, (i + 1) * seg - (len + tlen)], duration: dur + tail, delay: del, loop: true, loopDelay: ld - tail, ease: 'linear' })
          }
          amb.appendChild(g)
          animate(g, { ...mp, duration: dur, delay: del, loop: true, loopDelay: ld, ease: 'linear' })
          animate(g, { opacity: [0, 1, 1, 0], duration: dur, delay: del, loop: true, loopDelay: ld, ease: 'linear' })
        })
      }

      const packet = (kind: string) => {
        const g = document.createElementNS(NS, 'g')
        g.innerHTML = `<rect x="-15" y="-11" width="30" height="22" rx="7" fill="#ffffff" stroke="#0f6688" stroke-width="2"/><g fill="none" stroke="#0f6688" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${GLY[kind] ?? GLY.file}</g>`
        g.style.opacity = '0'
        pkLayer.appendChild(g)
        return g
      }
      const barEls = $$('.rp-bar'), trend = svg.createDrawable($<SVGPathElement>('.rp-trend'))
      const repBars = (on: boolean) => barEls.forEach((b) => { utils.remove(b); b.style.width = on ? `${b.dataset.w}%` : '0%' })
      const repMap = (on: boolean) => {
        $$<SVGCircleElement>('.dg-dot').forEach((d) => { utils.remove(d); d.style.opacity = on ? '1' : '0'; d.setAttribute('fill', on ? MAP_COLOURS[+d.dataset.g!] : '#9db3b6') })
        utils.remove($('.dg-amap')); $('.dg-amap').style.opacity = on ? '1' : '0'
      }
      const repFind = (on: boolean) => {
        $$('.rp-ln').forEach((l) => { utils.remove(l); l.style.background = on ? '#12303a' : '#d3e0df'; l.style.opacity = on ? '0.75' : '1' })
        utils.remove(trend); utils.set(trend, { draw: on ? '0 1' : '0 0' })
        utils.remove($('.rp-tag')); $('.rp-tag').style.opacity = on ? '1' : '0'
      }
      const clear = () => {
        if (tl) { tl.revert(); tl = null }
        $$('.dg-packets > g').forEach((g) => { utils.remove(g); g.remove() })
        Object.keys(conns).forEach((k) => { utils.remove(conns[k]); utils.set(conns[k], { opacity: 0 }); if (drawables[k]) utils.set(drawables[k], { draw: '0 0' }) })
        utils.set($('.dg-bar'), { width: '0%' }); $('.dg-pct').textContent = '0%'
        $$('.dg-sub').forEach((s) => { s.style.background = 'transparent'; s.style.color = '#546b71' })
        $('.dg-jobstep').textContent = 'Waiting for a job'; $('.dg-locktxt').textContent = LOCK0
        repBars(false); repMap(false); repFind(false); utils.remove($('.dg-edits')); utils.set($('.dg-edits'), { opacity: 0 })
        $$('.dg-ech').forEach((e) => { utils.remove(e); e.style.background = '#fff'; e.style.color = '#12303a'; e.style.borderColor = '#d3e0df' })
        $$('.dg-obar').forEach((b) => { utils.remove(b); b.style.height = '0%' }); $$('.dg-ocnt').forEach((c) => { c.textContent = '' })
        $$('.dg-on').forEach((c) => { c.style.background = '#fff'; c.style.color = '#9fbfca'; c.style.borderColor = '#d3e0df' })
      }

      function go(target: number) {
        let i = target
        if (i < 0) i = MAP_STAGES.length - 1
        if (i >= MAP_STAGES.length) i = 0
        i0 = i; setCur(i); clear()
        const s = MAP_STAGES[i]
        chips.forEach((c, k) => {
          animate(c.querySelector('.dg-ct')!, { opacity: k === i ? 1 : 0.55, duration: 300 })
          const p = c.querySelector<HTMLElement>('.dg-prog')!
          utils.remove(p); utils.set(p, { width: k < i ? '100%' : '0%' })
        })
        Object.keys(nodes).forEach((id) => {
          const on = s.focus.includes(id as NodeId)
          animate(Array.from(nodes[id].children), { opacity: on ? 1 : 0.38, duration: 350 })
          nodes[id].style.borderColor = on ? '#0f6688' : '#d3e0df'
          nodes[id].style.borderWidth = on ? '2.5px' : '1.5px'
        })
        if (s.title === 'Build the report' || s.title === 'Edit, share, export') { repBars(true); repMap(true) }
        if (s.title === 'Edit, share, export') repFind(true)
        $$('.dg-dchip').forEach((c) => {
          const on = s.db.includes(c.dataset.k!)
          c.style.background = on ? '#0f6688' : '#eef4f4'; c.style.color = on ? '#fff' : '#12303a'; c.style.fontWeight = on ? '600' : '500'
        })
        tl = createTimeline({ loop: !reduce, loopDelay: 1400, defaults: { ease: 'inOutQuad' } })
        let end = 1000
        s.conns.forEach(([cid, pk, ms, only]) => {
          const c = conns[cid]
          if (only) { /* packet only: the wire is already drawn */ } else if (!drawables[cid]) tl!.add(c, { opacity: [0, 0.9], duration: 500 }, ms)
          else { utils.set(c, { opacity: 1 }); tl!.add(drawables[cid], { draw: ['0 0', '0 1'], duration: 800 }, ms) }
          if (pk !== 'bar') {
            const p = packet(pk), mp = svg.createMotionPath(c)
            tl!.add(p, { opacity: [0, 1], duration: 160 }, ms + 450).add(p, { ...mp, duration: 1700, ease: 'inOutSine' }, ms + 450).add(p, { opacity: [1, 0], duration: 220 }, ms + 450 + 1500)
            end = Math.max(end, ms + 2400)
          }
        })
        if (s.title === 'Find themes') {
          tl.add($('.dg-bar'), { width: ['0%', '100%'], duration: 7000, ease: 'linear' }, 1600)
          const pc = { n: 0 }
          tl.add(pc, { n: 100, duration: 7000, ease: 'linear', onUpdate: () => { $('.dg-pct').textContent = `${Math.round(pc.n)}%` } }, 1600)
          const subs = $$('.dg-sub'), at = [2000, 3600, 5200, 6400, 7800]
          subs.forEach((sub, k) => { tl!.add(sub, { backgroundColor: ['rgba(15,102,136,0)', 'rgba(15,102,136,.12)'], color: ['#546b71', '#12303a'], duration: 350 }, at[k]) })
          const names: Array<[number, string]> = [[2000, 'Turning answers into vectors'], [5200, 'Naming each group'], [6400, 'Finding sub-themes'], [7200, 'Naming sub-themes'], [7800, 'Scoring tone']]
          names.forEach(([ms, n]) => tl!.call(() => { $('.dg-jobstep').textContent = n }, ms))
          tl.call(() => { $('.dg-locktxt').textContent = 'A second build for this column is refused, with a message' }, 4000)
          tl.call(() => { $('.dg-locktxt').textContent = 'Allowed again now that this one finished'; $('.dg-jobstep').textContent = 'Done' }, 8800)
          tl.add(barEls, { width: (b: unknown) => ['0%', `${(b as HTMLElement).dataset.w}%`], duration: 800, delay: stagger(130), ease: 'outExpo' }, 7900)
          tl.add($('.dg-amap'), { opacity: [0, 1], duration: 400 }, 8600)
          tl.add($$('.dg-dot'), { opacity: [0, 1], duration: 300, delay: stagger(35) }, 8800)
          $$<SVGCircleElement>('.dg-dot').forEach((d, k) => tl!.call(() => d.setAttribute('fill', MAP_COLOURS[+d.dataset.g!]), 10000 + k * 20))
          const ons = $$('.dg-on'), obars = $$('.dg-obar'), ocnt = $$('.dg-ocnt')
          ;([[9600, 1300], [10900, 1300], [12200, 1300], [13500, 300]] as const).forEach(([ms, dur], k) => {
            tl!.call(() => { const n = ons[k]; n.style.background = '#dcecf3'; n.style.color = '#0f6688'; n.style.borderColor = '#9cc7d8' }, ms)
            if (obars[k]) tl!.add(obars[k], { height: ['0%', '100%'], duration: dur, ease: 'linear' }, ms)
            tl!.call(() => { ocnt[k].textContent = '✓' }, ms + dur)
          })
          tl.call(() => { $('.dg-jobstep').textContent = 'Updating the themes' }, 13500)
          end = 15200
        }
        if (s.title === 'Build the report') {
          tl.call(() => { $$('.rp-ln').forEach((l) => { l.style.transition = 'background .6s, opacity .6s'; l.style.background = '#12303a'; l.style.opacity = '0.75' }) }, 3400)
          tl.add(trend, { draw: ['0 0', '0 1'], duration: 900, ease: 'inOutQuad' }, 4200)
          tl.add($('.rp-tag'), { opacity: [0, 1], duration: 400 }, 5800)
        }
        if (s.title === 'Edit, share, export') {
          tl.add($('.dg-edits'), { opacity: [0, 1], duration: 400 }, 200)
          const at = [600, 1000, 1400, 1800, 2400, 3200]
          $$('.dg-ech').forEach((e, k) => tl!.call(() => { e.style.background = '#0f6688'; e.style.color = '#fff'; e.style.borderColor = '#0f6688' }, at[k]))
          tl.add($$('.rp-ln'), { opacity: [0.75, 0.25, 0.75], duration: 900 }, 3200)
          end = 7200
        }
        if (s.title === 'Clean and mask') tl.add($('.dg-mask'), { scale: [1, 1.12, 1], duration: 700 }, 400)
        tl.add({ n: 0 }, { n: 1, duration: 10 }, Math.max(end, 3000))
        if (reduce) { tl.pause(); tl.seek(Math.max(end, 3000)) }
        window.clearTimeout(timer)
        const cycle = Math.max(end, 3000) + 1400
        if (isPlaying && !reduce) {
          animate(chips[i].querySelector('.dg-prog')!, { width: ['0%', '100%'], duration: cycle, ease: 'linear' })
          timer = window.setTimeout(() => go(i + 1), cycle)
        }
      }
      api.current = {
        go,
        setPlaying: (p) => {
          if (reduce || !begun || p === isPlaying) return
          isPlaying = p
          if (p) go(i0)
          else { window.clearTimeout(timer); chips.forEach((c) => utils.remove(c.querySelector('.dg-prog')!)) }
        },
      }
      // Starts only when the map scrolls into view (it loops forever), with a fallback for thumbnails.
      stopView = onView(el, () => { begun = true; setStarted(true); ambient(); go(0) }, 6000, 0.1)
      return () => window.clearTimeout(timer)
    })
    return () => { stopView(); api.current = null; scope.revert() }
  }, [reduce])

  const onKeyDown = (e: React.KeyboardEvent) => {
    if (e.key !== 'ArrowRight' && e.key !== 'ArrowLeft') return
    if ((e.target as HTMLElement).closest('.dg-mode')) return
    e.preventDefault()
    api.current?.go(cur + (e.key === 'ArrowRight' ? 1 : -1))
  }
  const stage = MAP_STAGES[cur]

  return (
    // No pause button (user's call): pointing at the map or focusing into it holds it on the current step.
    <div ref={root} onKeyDown={onKeyDown} onMouseEnter={() => api.current?.setPlaying(false)} onMouseLeave={() => api.current?.setPlaying(true)}
      onFocus={() => api.current?.setPlaying(false)} onBlur={() => api.current?.setPlaying(true)}>
      <div className="hd-map-bar">
        <div className="dg-steps" role="group" aria-label="Steps">
          {MAP_STAGES.map((s, i) => (
            <button key={s.title} type="button" className="dg-chip-s" aria-current={started && i === cur ? 'step' : undefined} onClick={() => api.current?.go(i)}>
              <span className="dg-track" /><span className="dg-prog" />
              <span className="dg-cs">Step {i + 1}</span><span className="dg-ct">{s.title}</span>
            </button>
          ))}
        </div>
        <div className="dg-tools">
          <div className="dg-mode" role="group" aria-label="Detail level">
            <button type="button" aria-pressed={!tech} onClick={() => setTech(false)}>Plain English</button>
            <button type="button" aria-pressed={tech} onClick={() => setTech(true)}>Technical</button>
          </div>
          <button type="button" className="dg-round" aria-label="Previous step" onClick={() => api.current?.go(cur - 1)}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 6l-6 6 6 6" /></svg>
          </button>
          <button type="button" className="dg-round" aria-label="Next step" onClick={() => api.current?.go(cur + 1)}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 6l6 6-6 6" /></svg>
          </button>
        </div>
      </div>
      <p className="dg-sr" aria-live="polite">
        {`Step ${cur + 1} of ${MAP_STAGES.length}: ${stage.title}. ${tech ? stage.tech : stage.plain} What leaves your data: ${stage.leaves}`}
      </p>
      <div className="hd-map-fit">
        <Fit w={MAP_W} h={MAP_H}>
          <div ref={map} className="dg-map" aria-hidden="true">
            {ZONES.map(([t, x, y, w, h]) => (
              <div key={t} className="dg-zone" style={{ left: x, top: y, width: w, height: h }}><div className="dg-zone-l">{t}</div></div>
            ))}
            <svg className="dg-svg" width={MAP_W} height={MAP_H} viewBox={`0 0 ${MAP_W} ${MAP_H}`}>
              <g>{Object.entries(WIRES).map(([k, [d]]) => <path key={k} className="dg-gh" d={d} style={{ fill: 'none', stroke: 'none' }} />)}</g>
              <g className="dg-amb" />
              <g>
                {Object.entries(WIRES).map(([k, [d, st]]) => (
                  <path key={k} className="dg-c" data-id={k} data-k={st} d={d}
                    style={{ fill: 'none', stroke: st === 'dot' ? 'var(--muted)' : 'var(--accent)', strokeWidth: 2.4, strokeLinecap: 'round', strokeDasharray: dash(st), opacity: 0 }} />
                ))}
              </g>
              <g className="dg-packets" />
            </svg>
            {(Object.keys(NODES) as NodeId[]).map((id) => <NodeCard key={id} id={id} tech={tech} />)}
          </div>
        </Fit>
      </div>
    </div>
  )
}
