import { useEffect, useState } from 'react'
import type { CSSProperties } from 'react'
import { Link } from 'react-router-dom'
import { QUOTES, THEMES } from './data'
import { useReducedMotion, useRevealed } from './motion'
import Sunburst, { ARC_DELAY } from './Sunburst'

// The one orchestrated moment: answers, then themes drawing in, then the sentence a report would print.
export default function Hero() {
  const reduce = useReducedMotion()
  const [play, setPlay] = useState(0)
  const revealed = useRevealed(true, play)
  const [toldFor, setToldFor] = useState<number | null>(null)
  const told = reduce || toldFor === play
  const [hover, setHover] = useState<number | null>(null)
  const [locked, setLocked] = useState<number | null>(null)
  const active = hover ?? locked

  useEffect(() => {
    if (reduce) return
    const id = window.setTimeout(() => setToldFor(play), ARC_DELAY(THEMES.length - 1) + 1300)
    return () => window.clearTimeout(id)
  }, [play, reduce])

  const dim = (theme: number) => (active !== null && active !== theme ? 'is-dim' : '')

  return (
    <section className="lp-hero" aria-labelledby="lp-h1">
      <div className="lp-hero-text">
        <h1 id="lp-h1">What people said, in one look.</h1>
        <p className="lp-lede">
          Upload a spreadsheet of survey answers. Verbatim groups them into themes, reads the tone, and shows the story as
          a short visual report. No statistics needed.
        </p>
        <div className="lp-cta">
          <Link className="lp-btn primary" to="/sign-up">
            Create an account
          </Link>
          <Link className="lp-btn" to="/sign-in">
            Sign in
          </Link>
        </div>
        <p className="lp-fine">Works with .xlsx and .csv files. Your projects stay private to your account.</p>
      </div>

      <div className="lp-stage">
        <div className="lp-col lp-answers">
          <h2 className="lp-col-title">What they wrote</h2>
          <ul>
            {QUOTES.map((q, i) => (
              <li
                key={q.text}
                className={`lp-quote ${revealed ? 'on' : ''} ${dim(q.theme)} ${i > 4 ? 'lp-more' : ''}`}
                style={{ '--c': THEMES[q.theme].color, '--d': `${ARC_DELAY(q.theme) + 200}ms` } as CSSProperties}
                onMouseEnter={() => setHover(q.theme)}
                onMouseLeave={() => setHover(null)}
              >
                <span className="q-text">“{q.text}”</span>
                <span className="q-tag">{THEMES[q.theme].name}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="lp-col lp-chart">
          <h2 className="lp-col-title">What it found</h2>
          <Sunburst active={active} revealed={revealed} onHover={setHover} />
        </div>

        <div className="lp-col lp-story">
          <h2 className="lp-col-title">What it says</h2>
          <p className={`lp-sentence ${told ? 'on' : ''}`}>
            <span className="lp-badge">Solid</span>
            Cost and charging make up more than half of the reasons.
          </p>
          <ul className="lp-legend" aria-label="Themes">
            {THEMES.map((t, i) => (
              <li key={t.name} className={dim(i)}>
                <button
                  type="button"
                  aria-pressed={locked === i}
                  onMouseEnter={() => setHover(i)}
                  onMouseLeave={() => setHover(null)}
                  onFocus={() => setHover(i)}
                  onBlur={() => setHover(null)}
                  onClick={() => setLocked(locked === i ? null : i)}
                >
                  <i style={{ background: t.color }} aria-hidden="true" />
                  <span className="l-name">{t.name}</span>
                  <b>{t.pct}%</b>
                </button>
              </li>
            ))}
          </ul>
          <button type="button" className="lp-replay" onClick={() => setPlay((n) => n + 1)}>
            Replay
          </button>
        </div>
      </div>
      <p className="lp-caption">Example: why people have not bought an electric vehicle yet. Illustrative data.</p>
    </section>
  )
}
