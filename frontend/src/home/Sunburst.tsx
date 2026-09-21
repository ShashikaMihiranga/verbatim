import type { CSSProperties } from 'react'
import { THEMES } from './data'

const CX = 220
const CY = 220
const GAP = 1.4 // degrees left between neighbouring arcs

function polar(r: number, deg: number) {
  const a = ((deg - 90) * Math.PI) / 180
  return { x: CX + r * Math.cos(a), y: CY + r * Math.sin(a) }
}

function arc(r: number, a0: number, a1: number) {
  const p0 = polar(r, a0)
  const p1 = polar(r, a1)
  return `M ${p0.x.toFixed(2)} ${p0.y.toFixed(2)} A ${r} ${r} 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${p1.x.toFixed(2)} ${p1.y.toFixed(2)}`
}

function wrap(name: string, max = 13): string[] {
  const out: string[] = []
  let line = ''
  for (const w of name.split(' ')) {
    if (line && (line + ' ' + w).length > max) {
      out.push(line)
      line = w
    } else line = line ? `${line} ${w}` : w
  }
  if (line) out.push(line)
  return out
}

type Seg = { key: string; theme: number; d: string; ring: 0 | 1 }

function build(): Seg[] {
  const segs: Seg[] = []
  let start = 0
  THEMES.forEach((t, i) => {
    const span = t.pct * 3.6
    segs.push({ key: `t${i}`, theme: i, d: arc(120, start + GAP / 2, start + span - GAP / 2), ring: 0 })
    let s = start
    for (const sub of t.subs) {
      const w = sub.pct * 3.6
      segs.push({ key: `t${i}-${sub.name}`, theme: i, d: arc(182, s + GAP / 2, s + w - GAP / 2), ring: 1 })
      s += w
    }
    start += span
  })
  return segs
}
const SEGS = build()
export const ARC_DELAY = (theme: number) => 450 + theme * 150

export default function Sunburst({ active, revealed, onHover }: { active: number | null; revealed: boolean; onHover: (i: number | null) => void }) {
  const t = active === null ? null : THEMES[active]
  const label = THEMES.map((x) => `${x.name} ${x.pct}%`).join(', ')
  return (
    <svg className="lp-sun" viewBox="0 0 440 440" role="img" aria-label={`Sunburst chart of reasons. ${label}.`}>
      {SEGS.map((s) => {
        const th = THEMES[s.theme]
        const dim = active !== null && active !== s.theme
        return (
          <path
            key={s.key}
            d={s.d}
            pathLength={1}
            className={`lp-arc ${revealed ? 'on' : ''} ${dim ? 'is-dim' : ''} ring-${s.ring}`}
            style={{ stroke: th.color, '--d': `${ARC_DELAY(s.theme) + s.ring * 350}ms` } as CSSProperties}
            onMouseEnter={() => onHover(s.theme)}
            onMouseLeave={() => onHover(null)}
          />
        )
      })}
      <g className="lp-sun-center" textAnchor="middle" aria-hidden="true">
        {t ? (
          <>
            {wrap(t.name).map((ln, i, all) => (
              <text key={ln} x={CX} y={CY - 8 - (all.length - 1) * 11 + i * 22} className="c-name">
                {ln}
              </text>
            ))}
            <text x={CX} y={CY + 38 + (wrap(t.name).length - 1) * 11} className="c-pct">
              {t.pct}%
            </text>
          </>
        ) : (
          <>
            <text x={CX} y={CY - 2} className="c-name">
              Reasons
            </text>
            <text x={CX} y={CY + 22} className="c-sub">
              example data
            </text>
          </>
        )}
      </g>
    </svg>
  )
}
