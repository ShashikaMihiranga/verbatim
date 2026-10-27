import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { animate, createScope } from 'animejs'
import { useReducedMotion } from './home/motion'
import type { Job } from './jobsApi'
import { formatElapsed, SLOW_MS, stepIndex, STEPS, TIMEOUT_MS, TIPS } from './reportWaitingModel'
import './reportWaiting.css'

// The Reports page while themes are being found: the "Live picture" waiting card
// (design/handoffs/ReportWaiting_UIHandoff.md, design/gen_reportwait.py version_b). Live from the real job:
// the step the server reports, the elapsed time from the server's start time, and real counts for step 1
// (the answers embedded so far, `job.progress`). The picture is an example, not the customer's data.

const GREEN = '#3f8a57'
const BLUE = '#2680c7'
const CYAN = '#26cbd8'
const RED = '#c0614a'
const GREY = '#8a979b'
const COLOURS = [GREEN, BLUE, CYAN]
const CENTRES: Array<[number, number]> = [[120, 150], [250, 85], [370, 195]]
const GROUPS = ['Cost', 'Charging', 'Range']
const SUBS = ['Upfront price', 'Charge at home', 'Battery range']
const TONES: Array<[string, string]> = [['Mostly negative', RED], ['Mixed', GREY], ['Mostly positive', GREEN]]
const DOTS = 33

// The three dot layouts (scattered, clustered, split into sub-clusters); seeded so they never change.
function layouts() {
  let seed = 7
  const rnd = () => { seed = (seed * 1664525 + 1013904223) % 4294967296; return seed / 4294967296 }
  const scatter: Array<[number, number]> = []
  const cluster: Array<[number, number]> = []
  const split: Array<[number, number]> = []
  for (let i = 0; i < DOTS; i++) {
    const [cx, cy] = CENTRES[i % 3]
    const k = Math.floor(i / 3)
    const ang = k * 2.4
    const rad = 12 + (k % 6) * 6.5
    const px = Math.round(cx + rad * Math.cos(ang))
    const py = Math.round(cy + rad * Math.sin(ang))
    scatter.push([Math.round(24 + rnd() * 412), Math.round(24 + rnd() * 252)])
    cluster.push([px, py])
    split.push([px + (k % 2 ? 14 : -14), py + (k % 2 ? 8 : -8)])
  }
  return [scatter, cluster, split]
}
const LAYOUTS = layouts()
const layoutFor = (step: number) => LAYOUTS[step <= 0 ? 0 : step === 1 ? 1 : 2]

interface Progress { step?: string; done?: number; total?: number }

export interface ReportWaitingProps {
  job: Job
  resumed: boolean // the job was already running when the page opened: "Welcome back"
  onRetry: () => void
  onSeeThemes?: () => void // the done overlay's button, when the page held the card (tab in the background)
}

export default function ReportWaiting({ job, resumed, onRetry, onSeeThemes }: ReportWaitingProps) {
  const reduce = useReducedMotion()
  const step = stepIndex(job)
  const failed = job.status === 'failed'
  const done = job.status === 'done'
  const shown = Math.min(step, 4) // the step whose name and picture are shown

  // Elapsed from the server's start time (a just-started job has none yet: count from when we saw it).
  const [firstSeen] = useState(() => Date.now())
  const started = job.created_at ? Date.parse(job.created_at) : firstSeen
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (job.status !== 'running') return
    const t = window.setInterval(() => setNow(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [job.status])
  const end = job.status === 'running' ? now : job.updated_at ? Date.parse(job.updated_at) : now
  const elapsed = Math.max(0, end - started)

  // How far the running step is: real counts when the job reports them, else a slow fill toward 90% from
  // when this page saw the step start (the real duration is unknown), jumping to full when it finishes.
  const [stepSeen, setStepSeen] = useState(() => ({ step, at: now }))
  if (stepSeen.step !== step) setStepSeen({ step, at: now }) // adjust while rendering: the step just changed
  const progress = (job.progress ?? null) as Progress | null
  const real = progress && progress.step === STEPS[shown].name && progress.total ? (progress.done ?? 0) / progress.total : null
  const guessed = 0.9 * (1 - Math.exp(-(now - stepSeen.at) / 25_000))
  const fraction = failed ? 1 : real ?? guessed

  const [dismissedTimeout, setDismissedTimeout] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const note: 'failed' | 'timeout' | 'back' | 'slow' | null = failed ? 'failed'
    : done ? null
      : elapsed >= TIMEOUT_MS && !dismissedTimeout ? 'timeout'
        : resumed && elapsed >= 60_000 ? 'back'
          : elapsed >= SLOW_MS ? 'slow' : null

  const announce = done ? 'All 5 steps done. Your themes are ready.'
    : failed ? `Step ${shown + 1} of 5 stopped: ${STEPS[shown].name}. We could not finish finding themes.`
      : `Step ${shown + 1} of 5: ${STEPS[shown].name}`

  return (
    <section className="rw-card" aria-labelledby="rw-title">
      <span className="rw-sr" role="status" aria-live="polite">{announce}</span>
      <div className="rw-cols">
        <div className="rw-pic"><Picture step={done ? 4 : shown} reduce={reduce} /></div>
        <div className="rw-status">
          <div className="rw-stepn">{done ? 'All 5 steps done' : `Step ${shown + 1} of 5`}</div>
          <h2 id="rw-title" className="rw-name">{done ? 'Finding themes: done' : STEPS[shown].name}</h2>
          <p className="rw-desc">{done ? 'Your themes are ready.' : STEPS[shown].desc}</p>
          <div className="rw-bar" role="progressbar" aria-valuemin={0} aria-valuemax={5} aria-valuenow={Math.min(step, 5)}
            aria-valuetext={done ? 'All steps done' : STEPS[shown].name}>
            {STEPS.map((s, i) => {
              const w = i < step || done ? 1 : i === step ? fraction : 0
              const colour = i < step || done ? GREEN : failed && i === step ? RED : 'var(--accent)'
              return <span key={s.name} className="rw-seg"><i style={{ width: `${Math.round(w * 100)}%`, background: colour }} /></span>
            })}
          </div>
          <ol className="rw-list">
            {STEPS.map((s, i) => {
              const state = done || i < step ? 'done' : i === step ? (failed ? 'failed' : 'running') : 'todo'
              return (
                <li key={s.name} className={`rw-row is-${state}`}>
                  <StepIcon state={state} n={i + 1} />
                  <span>{s.name}</span>
                  {state === 'running' && real !== null && progress?.total ? (
                    <span className="rw-count">{Math.round((real ?? 0) * 100)}%</span>
                  ) : null}
                </li>
              )
            })}
          </ol>
        </div>
      </div>
      <p className="rw-caption">
        Finding themes in your answers. This usually takes a minute or two. <b>{formatElapsed(elapsed)}</b> elapsed. The
        picture is an example, not your data.
      </p>
      <Tip reduce={reduce} />
      {note === 'slow' && (
        <div className="rw-note is-slow"><b>Taking a little longer than usual.</b> Large files can need a few more minutes. It is
          still working, and your answers are safe.</div>
      )}
      {note === 'back' && (
        <div className="rw-note is-info"><b>Welcome back.</b> Your themes are still being found. It started{' '}
          {Math.max(1, Math.round(elapsed / 60_000))} minute{Math.round(elapsed / 60_000) === 1 ? '' : 's'} ago. You can leave again at
          any time.</div>
      )}
      {note === 'timeout' && (
        <div className="rw-note is-info">
          <b>This is taking much longer than expected.</b> You do not have to wait here. It keeps working in the background,
          and your themes will be here when you come back.
          <div className="rw-note-btns">
            <button type="button" className="rw-pill" onClick={() => setLeaving(true)}>Leave and come back later</button>
            <button type="button" className="rw-pill is-outline" onClick={() => setDismissedTimeout(true)}>Keep waiting</button>
          </div>
        </div>
      )}
      {note === 'failed' && (
        <div className="rw-note is-failed" role="alert">
          <b>We could not finish finding themes.</b> Nothing was lost. Your cleaned file is still saved.
          {job.error && <span className="rw-error"> {job.error}</span>}
          <div className="rw-note-btns"><button type="button" className="rw-pill" onClick={onRetry}>Try again</button></div>
        </div>
      )}
      {leaving && !done && !failed && (
        <div className="rw-overlay">
          <span className="rw-badge is-info" aria-hidden="true">
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></svg>
          </span>
          <div className="rw-ov-title">We will keep working on it</div>
          <p className="rw-ov-text">You can close this page. When you come back to this report, your themes will be here, or you will see
            how far along it is.</p>
          <div className="rw-ov-btns">
            <Link className="rw-btn" to="/projects">Go to my files</Link>
            <button type="button" className="rw-link" onClick={() => setLeaving(false)}>Stay on this page</button>
          </div>
        </div>
      )}
      {done && onSeeThemes && (
        <div className="rw-overlay">
          <span className="rw-badge is-done" aria-hidden="true">
            <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M5 12l5 5 9-10" /></svg>
          </span>
          <div className="rw-ov-title">{resumed ? 'Welcome back. Your themes are ready' : 'Your themes are ready'}</div>
          <p className="rw-ov-text">Every theme links back to real answers.</p>
          <div className="rw-ov-btns"><button type="button" className="rw-btn" onClick={onSeeThemes}>See your themes</button></div>
        </div>
      )}
    </section>
  )
}

function StepIcon({ state, n }: { state: string; n: number }) {
  if (state === 'done') {
    return <svg className="rw-ico" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill={GREEN} /><path d="M7 12.5l3.2 3.2L17 9" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
  }
  if (state === 'failed') {
    return <svg className="rw-ico" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill={RED} /><path d="M8 8l8 8M16 8l-8 8" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" /></svg>
  }
  if (state === 'running') {
    return <svg className="rw-ico rw-spin" viewBox="0 0 24 24" fill="none" strokeWidth="3" strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9" stroke="var(--line)" /><path d="M12 3a9 9 0 019 9" stroke="var(--accent)" /></svg>
  }
  return <svg className="rw-ico" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10.5" fill="none" stroke="var(--line)" strokeWidth="1.8" /><text x="12" y="16" textAnchor="middle" className="rw-ico-n">{n}</text></svg>
}

// The example picture: dots that scatter, cluster, split, get names and tone. Opens straight on the current
// step's layout (no replay of earlier steps); later steps move with anime.js, or jump when motion is reduced.
function Picture({ step, reduce }: { step: number; reduce: boolean }) {
  const root = useRef<SVGSVGElement | null>(null)
  const initial = useMemo(() => layoutFor(step), []) // eslint-disable-line react-hooks/exhaustive-deps
  const shownStep = useRef(step)
  useEffect(() => {
    if (!root.current || shownStep.current === step) return
    shownStep.current = step
    const lay = layoutFor(step)
    const scope = createScope({ root: root.current }).add(() => {
      root.current!.querySelectorAll<SVGCircleElement>('.rw-dot').forEach((d, i) => {
        if (reduce) {
          d.setAttribute('cx', String(lay[i][0]))
          d.setAttribute('cy', String(lay[i][1]))
        } else {
          animate(d, { cx: lay[i][0], cy: lay[i][1], duration: 900, delay: i * 12, ease: 'outExpo' })
        }
      })
    })
    return () => scope.revert()
  }, [step, reduce])
  const on = (from: number) => (step >= from ? 'is-on' : '')
  return (
    <svg ref={root} viewBox="0 0 460 300" className="rw-svg" aria-hidden="true">
      {CENTRES.flatMap(([cx, cy], g) => [[-14, -8], [14, 8]].map(([dx, dy]) => (
        <circle key={`r${g}${dx}`} className={`rw-fade ${on(2)}`} cx={cx + dx} cy={cy + dy} r="30" fill="none" stroke={COLOURS[g]}
          strokeWidth="1.6" strokeDasharray="4 5" />
      )))}
      {initial.map(([x, y], i) => <circle key={i} className="rw-dot" cx={x} cy={y} r="6.5" fill={COLOURS[i % 3]} />)}
      {CENTRES.map(([cx, cy], g) => (
        <g key={g}>
          <text className={`rw-fade rw-glab ${on(1)}`} x={cx} y={cy - 58} textAnchor="middle">{GROUPS[g]}</text>
          <text className={`rw-fade rw-slab ${on(3)}`} x={cx} y={cy + 66} textAnchor="middle">{SUBS[g]}</text>
          <g className={`rw-fade ${on(4)}`}>
            <rect x={cx - 44} y={cy + 74} width="88" height="22" rx="11" fill={TONES[g][1]} fillOpacity="0.16" />
            <text className="rw-tone" x={cx} y={cy + 89} textAnchor="middle">{TONES[g][0]}</text>
          </g>
        </g>
      ))}
    </svg>
  )
}

function Tip({ reduce }: { reduce: boolean }) {
  const [i, setI] = useState(0)
  const [fade, setFade] = useState(false)
  const [paused, setPaused] = useState(false)
  useEffect(() => {
    if (paused) return
    let swap = 0
    const t = window.setInterval(() => {
      if (reduce) { setI((n) => (n + 1) % TIPS.length); return }
      setFade(true)
      swap = window.setTimeout(() => { setI((n) => (n + 1) % TIPS.length); setFade(false) }, 300)
    }, 5000)
    return () => { window.clearInterval(t); window.clearTimeout(swap) }
  }, [paused, reduce])
  return (
    <div className="rw-tip" tabIndex={0} onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)} onBlur={() => setPaused(false)}>
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9 18h6M10 21h4M12 3a6 6 0 00-4 10.5c.8.8 1 1.5 1 2.5h6c0-1 .2-1.7 1-2.5A6 6 0 0012 3z" /></svg>
      <span className={fade ? 'is-fading' : ''}>{TIPS[i]}</span>
    </div>
  )
}
