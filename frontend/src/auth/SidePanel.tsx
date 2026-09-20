import type { CSSProperties } from 'react'
import type { Variant } from './variants'

// Decorative side panels, one per sign-in design. Only this layer differs between A, B, C and D.
// They carry no real data: wording is illustrative and there are no record counts.

const THEMES = [
  { name: 'Charging speed', pct: 34, tone: 'var(--t2)' },
  { name: 'Price', pct: 27, tone: 'var(--t1)' },
  { name: 'Range', pct: 22, tone: 'var(--t4)' },
  { name: 'Service', pct: 17, tone: 'var(--t6)' },
]

function PanelA() {
  return (
    <div className="panel-a">
      <p className="panel-kicker">Sample report</p>
      <h2>What people are talking about</h2>
      <ul>
        {THEMES.map((t, i) => (
          <li key={t.name} style={{ '--i': i } as CSSProperties}>
            <span className="lbl">{t.name}</span>
            <span className="bar">
              <i style={{ width: `${t.pct * 2.4}%`, background: t.tone }} />
            </span>
            <b>{t.pct}%</b>
          </li>
        ))}
      </ul>
      <p className="panel-note">Every bar links back to the real answers behind it.</p>
    </div>
  )
}

const WORDS: [string, string, string][] = [
  ['“too pricey for what you get”', 'Price', 'var(--t1)'],
  ['“waited ages to charge”', 'Charging speed', 'var(--t2)'],
  ['“gets me to work and back”', 'Range', 'var(--t4)'],
]

function PanelB() {
  return (
    <div className="panel-b">
      <p className="panel-kicker">From words to themes</p>
      <h2>Many answers, a few clear themes</h2>
      <ol>
        {WORDS.map(([quote, theme, tone], i) => (
          <li key={theme} style={{ '--i': i } as CSSProperties}>
            <span className="q">{quote}</span>
            <span className="arrow">to</span>
            <span className="chip" style={{ borderColor: tone }}>
              <i style={{ background: tone }} />
              {theme}
            </span>
          </li>
        ))}
      </ol>
    </div>
  )
}

const QUOTES: [string, string][] = [
  ['Charging at home is easy, public chargers are not.', 'var(--t2)'],
  ['I would pay more if the service was faster.', 'var(--t1)'],
  ['Range is fine for my commute.', 'var(--t4)'],
  ['The app keeps logging me out.', 'var(--t6)'],
]

function PanelC() {
  return (
    <div className="panel-c">
      <p className="panel-kicker">In their own words</p>
      <div className="wall">
        {QUOTES.map(([q, tone], i) => (
          <blockquote key={q} style={{ borderLeftColor: tone, '--i': i } as CSSProperties}>
            {q}
          </blockquote>
        ))}
      </div>
    </div>
  )
}

const TILES = ['--t1', '--t2', '--t3', '--t4', '--t5', '--t6', '--t7', '--other']

function PanelD() {
  const cells = Array.from({ length: 30 }, (_, i) => TILES[(i * 5 + (i >> 2)) % TILES.length])
  return (
    <div className="panel-d">
      <p className="panel-kicker">Every answer finds its place</p>
      <div className="mosaic">
        {cells.map((c, i) => (
          <i key={i} style={{ background: `var(${c})`, '--i': i % 9 } as CSSProperties} />
        ))}
      </div>
    </div>
  )
}

export default function SidePanel({ variant }: { variant: Variant }) {
  return (
    <aside className={`auth-side side-${variant}`} aria-hidden="true" data-variant={variant}>
      {variant === 'a' && <PanelA />}
      {variant === 'b' && <PanelB />}
      {variant === 'c' && <PanelC />}
      {variant === 'd' && <PanelD />}
    </aside>
  )
}
