import { useState } from 'react'
import type { CSSProperties } from 'react'
import { AGE_GROUPS, HEAT, MONTHS, THEMES, TREND } from './data'
import { useInView, useRevealed } from './motion'

const TABS = [
  { id: 'tone', label: 'Why they said it', sentence: 'Charging carries the most negative wording.' },
  { id: 'rank', label: 'What to fix first', sentence: 'Cost and charging are more than half of the reasons.' },
  { id: 'who', label: 'Who says what', sentence: 'People aged 65 and over say “Not needed” three times as often as those under 30.' },
  { id: 'time', label: 'How it changed', sentence: 'Charging worries fell across the year while cost worries grew.' },
] as const
type TabId = (typeof TABS)[number]['id']

const five = THEMES.slice(0, 5)

function ToneBars({ on }: { on: boolean }) {
  return (
    <div className="ch-tone">
      <ul className="ch-key" aria-label="Legend">
        <li><i style={{ background: 'var(--neg)' }} />Negative</li>
        <li><i style={{ background: 'var(--neu)' }} />Neutral</li>
        <li><i style={{ background: 'var(--pos)' }} />Positive</li>
      </ul>
      {five.map((t, i) => (
        <div className="ch-row" key={t.name}>
          <span className="ch-label">{t.name}</span>
          <div className={`ch-stack ${on ? 'on' : ''}`} style={{ '--d': `${i * 110}ms` } as CSSProperties}>
            {(['neg', 'neu', 'pos'] as const).map((k, j) => (
              <span key={k} className={`seg ${k}`} style={{ flexGrow: t.tone[j] }}>
                {t.tone[j] >= 14 ? `${t.tone[j]}%` : ''}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

function RankBars({ on }: { on: boolean }) {
  const max = five[0].pct
  return (
    <div className="ch-rank">
      {five.map((t, i) => (
        <div className="ch-row" key={t.name}>
          <span className="ch-label">{t.name}</span>
          <div className="ch-track">
            <i className={`bar ${on ? 'on' : ''}`} style={{ width: `${(t.pct / max) * 100}%`, background: t.color, '--d': `${i * 110}ms` } as CSSProperties} />
          </div>
          <b className={`ch-val ${on ? 'on' : ''}`} style={{ '--d': `${i * 110 + 500}ms` } as CSSProperties}>{t.pct}%</b>
        </div>
      ))}
    </div>
  )
}

function Heat({ on }: { on: boolean }) {
  return (
    <div className="ch-heat" role="table" aria-label="Share of answers by age group">
      <div className="h-head" role="row">
        <span />
        {AGE_GROUPS.map((g) => (
          <span key={g} role="columnheader">{g}</span>
        ))}
      </div>
      {HEAT.map((r, i) => (
        <div className="h-row" role="row" key={r.theme}>
          <span className="ch-label" role="rowheader">{r.theme}</span>
          {r.values.map((v, j) => (
            <span
              key={j}
              role="cell"
              className={`cell ${on ? 'on' : ''}`}
              style={{ '--a': 0.1 + 0.6 * (v / 34), '--d': `${(i + j) * 90}ms` } as CSSProperties}
            >
              {v}%
            </span>
          ))}
        </div>
      ))}
      <p className="ch-note">Share of each group’s answers. Darker means more.</p>
    </div>
  )
}

const W = 560
const H = 250
const PL = 8
const PR = 92
const PT = 16
const PB = 30
const yOf = (v: number) => PT + (1 - (v - 15) / 25) * (H - PT - PB)
const xOf = (i: number) => PL + (i / 11) * (W - PL - PR)
const line = (vs: number[]) => vs.map((v, i) => `${i ? 'L' : 'M'} ${xOf(i).toFixed(1)} ${yOf(v).toFixed(1)}`).join(' ')

function Trend({ on }: { on: boolean }) {
  const series = [
    { name: 'Charging', vs: TREND.charging, color: 'var(--t2)' },
    { name: 'Cost', vs: TREND.cost, color: 'var(--t1)' },
  ]
  return (
    <div className="ch-trend">
      <ul className="ch-key" aria-label="Legend">
        {series.map((s) => (
          <li key={s.name}><i style={{ background: s.color }} />{s.name}</li>
        ))}
      </ul>
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Line chart by month. Charging falls from 31% to 22%. Cost rises from 28% to 33%.">
        {[20, 30, 40].map((g) => (
          <g key={g}>
            <line x1={PL} x2={W - PR} y1={yOf(g)} y2={yOf(g)} className="grid" />
            <text x={W - PR + 8} y={yOf(g) + 4} className="axis">{g}%</text>
          </g>
        ))}
        {[0, 3, 6, 9].map((m) => (
          <text key={m} x={xOf(m)} y={H - 8} className="axis" textAnchor="middle">{MONTHS[m]}</text>
        ))}
        {series.map((s, k) => (
          <g key={s.name}>
            <path d={line(s.vs)} pathLength={1} className={`ln ${on ? 'on' : ''}`} style={{ stroke: s.color, '--d': `${k * 250}ms` } as CSSProperties} />
            <g className={`end ${on ? 'on' : ''}`} style={{ '--d': `${1100 + k * 250}ms` } as CSSProperties}>
              <circle cx={xOf(11)} cy={yOf(s.vs[11])} r={4} fill={s.color} />
              <text x={xOf(11) + 10} y={yOf(s.vs[11]) + 4} className="end-label">{s.name} {s.vs[11]}%</text>
            </g>
          </g>
        ))}
      </svg>
    </div>
  )
}

export default function Charts() {
  const [tab, setTab] = useState<TabId>('tone')
  const { ref, seen } = useInView<HTMLDivElement>()
  const on = useRevealed(seen, tab)
  const cur = TABS.find((t) => t.id === tab)!
  return (
    <section className="lp-section" id="charts" aria-labelledby="lp-charts-h">
      <div className="lp-section-head">
        <h2 id="lp-charts-h">The chart follows the question.</h2>
        <p>
          Verbatim looks at what you asked and which columns you uploaded, then picks the chart that reads best. Try the four
          most common ones.
        </p>
      </div>
      <div ref={ref} className="lp-charts">
        <div className="lp-tabs" role="tablist" aria-label="Chart types">
          {TABS.map((t) => (
            <button key={t.id} role="tab" type="button" id={`tab-${t.id}`} aria-selected={tab === t.id} aria-controls="lp-panel" tabIndex={tab === t.id ? 0 : -1} onClick={() => setTab(t.id)}
              onKeyDown={(e) => {
                const i = TABS.findIndex((x) => x.id === tab)
                if (e.key === 'ArrowRight') setTab(TABS[(i + 1) % TABS.length].id)
                if (e.key === 'ArrowLeft') setTab(TABS[(i + TABS.length - 1) % TABS.length].id)
              }}>
              {t.label}
            </button>
          ))}
        </div>
        <div id="lp-panel" role="tabpanel" aria-labelledby={`tab-${tab}`} className="lp-panel">
          <p className="lp-sentence on"><span className="lp-badge">Solid</span>{cur.sentence}</p>
          {tab === 'tone' && <ToneBars on={on} />}
          {tab === 'rank' && <RankBars on={on} />}
          {tab === 'who' && <Heat on={on} />}
          {tab === 'time' && <Trend on={on} />}
          <p className="lp-caption">Example data.</p>
        </div>
      </div>
    </section>
  )
}
