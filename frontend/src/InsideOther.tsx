import { useEffect, useMemo, useState, type ReactNode } from 'react'
import InsideOtherFlow from './InsideOtherFlow'
import { prefersReducedMotion } from './insideOtherGeometry'
import { hasShare, insideOtherModel, listValue, STEPS, answerMapModel, isResult, type InsideOtherModel, type Leaf, type PointMap } from './insideOtherModel'
import { getAnswerMap, type AnswerMapResponse } from './themesApi'
import type { Job } from './jobsApi'
import type { ReportOtherBreakdown, ReportThemeSummary } from './reportApi'
import ThemeChart from './ThemeChart'

// "Inside Other", built to the Other-Flow design (docs/REPORT_UI_REWORK.md, Phase 2): ribbons from Other
// to where its answers went, three columns of real numbers, the four real steps, and when done, one chart
// per question. Live counts while running come from job.progress; the finished picture from job.result.

const fmt = (n: number) => n.toLocaleString('en-US')

function Arrow() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
      <path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

function Rows({ items, largest, value }: { items: Leaf[]; largest: number; value: (l: Leaf) => string }) {
  return (
    <ol className="io-rows">
      {items.map((l, i) => (
        <li key={l.label} className="io-row">
          <span className="io-chip" style={{ background: l.color, color: l.onColor }}>{i + 1}</span>
          <span className="io-row-name">{l.label}</span>
          <span className="io-row-track" aria-hidden="true">
            <span className="io-row-bar" style={{ width: `${largest ? (l.count / largest) * 100 : 0}%`, background: l.color }} />
          </span>
          <span className="io-row-n">{value(l)}</span>
        </li>
      ))}
    </ol>
  )
}

function Columns({ m, allThemesToggle }: { m: InsideOtherModel; allThemesToggle?: ReactNode }) {
  const largestKnown = Math.max(0, ...m.known.map((l) => l.count))
  const largestNew = Math.max(0, ...m.newThemes.map((l) => l.count))
  const showNumbers = m.phase === 'running' || m.phase === 'done'
  return (
    <div className="io-cols">
      <section className="io-col io-col-known" aria-label="Known themes">
        <h4 className="io-col-title">Known themes</h4>
        <p className="io-col-note">Answers that match a theme already in the chart</p>
        <p className="io-col-n">{showNumbers ? `+${fmt(m.knownTotal)}` : '+0'} <span>answers</span></p>
        <Rows items={m.known} largest={largestKnown} value={listValue(m.known, '+')} />
        {m.knownMore > 0 && <p className="io-more">and {m.knownMore} more</p>}
      </section>
      <section className="io-col io-col-new" aria-label="New themes found">
        <h4 className="io-col-title">New themes found</h4>
        <p className="io-col-note">Patterns no known theme covered</p>
        <p className="io-col-n">
          {fmt(showNumbers ? m.newTotal : 0)} <span>answers, {m.newThemes.length + m.newMore} theme{m.newThemes.length + m.newMore === 1 ? '' : 's'}</span>
        </p>
        <Rows items={m.newThemes} largest={largestNew} value={listValue(m.newThemes)} />
        {m.newMore > 0 && <p className="io-more">and {m.newMore} more</p>}
      </section>
      <section className="io-col io-col-still" aria-label="Still in Other">
        <h4 className="io-col-title">Still in Other</h4>
        <p className="io-col-note">Varied answers that don't repeat enough to group</p>
        <p className="io-col-n">{m.still !== null ? fmt(m.still) : '–'} <span>answers</span></p>
        {m.otherNowPct !== null && (
          <p className="io-col-note">
            {m.otherNowPct}% of all answers.{m.otherBeforePct !== null && ` It was ${m.otherBeforePct}% before this run.`}
          </p>
        )}
        {m.otherNowPct !== null && m.otherBeforePct ? (
          <span className="io-row-track io-still-track" aria-hidden="true">
            <span className="io-row-bar" style={{ width: `${Math.min(100, (m.otherNowPct / m.otherBeforePct) * 100)}%`, background: 'var(--other)' }} />
          </span>
        ) : null}
        {allThemesToggle}
      </section>
    </div>
  )
}

function Steps({ m }: { m: InsideOtherModel }) {
  return (
    <ol className="io-steps" aria-label="Step by step">
      {STEPS.map((label, i) => {
        const state = i < m.stepIndex ? 'done' : i === m.stepIndex ? 'running' : 'waiting'
        const fill = state === 'done' ? 100 : state === 'running' && i === 2 ? Math.round(m.matchingProgress * 100) : 0
        return (
          <li key={label} className="io-step" data-state={state}>
            <span className="io-step-dot">{state === 'done' ? 'ok' : i + 1}</span>
            <span className="io-step-text">
              <span className="io-step-label">{label}</span>
              <span className="io-step-state">{state === 'done' ? 'Done' : state === 'running' ? 'Running' : 'Waiting'}</span>
            </span>
            {i < STEPS.length - 1 && (
              <span className="io-step-bar" aria-hidden="true"><span style={{ width: `${fill}%` }} /></span>
            )}
          </li>
        )
      })}
    </ol>
  )
}

// Same absolute cut-offs app/api_report.py uses to call the overall tone positive or negative.
function sentimentColor(sentiment: number): string {
  if (sentiment >= 0.05) return 'var(--pos)'
  if (sentiment <= -0.05) return 'var(--neg)'
  return 'var(--neu)'
}

// Every real theme, including the ones folded into Other because the treemap has seven colours.
function AllThemes({ themes }: { themes: ReportThemeSummary[] }) {
  const largest = Math.max(1, ...themes.map((t) => t.share))
  return (
    <section className="io-chart" aria-label="All themes">
      <h4 className="io-chart-title">All {themes.length} themes</h4>
      <ul className="io-gains">
        {themes.map((t) => (
          <li key={t.name} className="io-gain">
            <span className="io-gain-name">{t.name}</span>
            <span className="io-gain-track"><span style={{ width: `${(t.share / largest) * 100}%`, background: sentimentColor(t.sentiment) }} /></span>
            <span className="io-gain-n"><strong>{t.share}%</strong> {fmt(t.count)} answers</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

// Colour a new theme by how its answers sound (its own tone split), never against an assumed average.
function toneOf(l: Leaf): { color: string; text: string } {
  if (!l.tone) return { color: l.color, text: '' }
  const { neg, neu, pos } = l.tone
  if (neg >= pos && neg >= neu) return { color: 'var(--neg)', text: `${Math.round(neg)}% negative` }
  if (pos >= neg && pos >= neu) return { color: 'var(--pos)', text: `${Math.round(pos)}% positive` }
  return { color: 'var(--neu)', text: `${Math.round(neu)}% neutral` }
}

// Most legend entries before the rest fold into "and N more".
const MAX_LEGEND = 9
const MAP_W = 1000
const MAP_H = 520
const MAP_PAD = 12

// Each dot is one answer from the whole column, placed by meaning (the theme build's embeddings, laid out
// in 2D), so themes show as clouds; the colour is the answer's theme now, after this run.
function PointMapChart({ map }: { map: PointMap }) {
  const [focus, setFocus] = useState<number | null>(null)
  const legend = [...map.groups.keys()].sort((a, b) => {
    const k = (i: number) => ['new', 'known', 'still'].indexOf(map.groups[i].kind)
    return k(a) - k(b) || map.groups[b].dots - map.groups[a].dots
  })
  const shown = legend.slice(0, MAX_LEGEND)
  const total = map.points.length
  const x = (v: number) => MAP_PAD + v * (MAP_W - 2 * MAP_PAD)
  const y = (v: number) => MAP_PAD + v * (MAP_H - 2 * MAP_PAD)
  return (
    <section className="io-chart io-map" aria-label="Every theme's answers, as a map">
      <h4 className="io-chart-title">How all answers group</h4>
      <p className="io-map-note">
        Each dot is one answer{map.sampled ? ` (a sample of ${fmt(total)})` : ''}. Answers that say similar things sit close together. Colour shows its theme now; new themes are outlined.
      </p>
      <svg className="io-map-svg" viewBox={`0 0 ${MAP_W} ${MAP_H}`} role="img"
        aria-label={`${fmt(total)} answers: ${shown.map((i) => `${map.groups[i].label} ${fmt(map.groups[i].dots)}`).join(', ')}`}>
        {map.groups.map((g, gi) => (
          // New themes also get an outline, so they read as new without relying on colour alone.
          <g key={`${g.kind}/${g.label}`} fill={g.color}
            stroke={g.kind === 'new' ? 'var(--ink)' : undefined} strokeWidth={g.kind === 'new' ? 1 : undefined}
            opacity={focus === null || focus === gi ? (g.kind === 'still' ? 0.55 : 0.9) : 0.08}>
            <title>{`${g.kind === 'still' ? 'Still in Other' : g.label} · ${fmt(g.dots)} answers`}</title>
            {map.points.map(([px, py, pg], i) => (pg === gi
              ? <circle key={i} cx={x(px).toFixed(1)} cy={y(py).toFixed(1)} r={g.kind === 'still' ? 3 : g.kind === 'new' ? 4.5 : 4} />
              : null))}
          </g>
        ))}
      </svg>
      <ul className="io-map-legend">
        {shown.map((gi) => {
          const g = map.groups[gi]
          return (
            <li key={`${g.kind}/${g.label}`}>
              <button type="button" className="io-map-key" aria-pressed={focus === gi}
                onClick={() => setFocus(focus === gi ? null : gi)}>
                <span className={`io-map-swatch${g.kind === 'new' ? ' is-new' : ''}`} style={{ background: g.color }} aria-hidden="true" />
                {g.kind === 'new' && <span className="io-newbadge">new</span>}
                {g.kind === 'still' ? 'Still in Other' : g.label}
                {/* A sample's dot counts would contradict the answer counts above. */}
                {!map.sampled && <span className="io-map-n">{fmt(g.dots)}</span>}
              </button>
            </li>
          )
        })}
        {legend.length > MAX_LEGEND && <li className="io-map-more">and {legend.length - MAX_LEGEND} more</li>}
      </ul>
    </section>
  )
}

// Fetched once the run is done: the map needs the themes as this run left them.
function AnswerMap({ job, realThemes }: { job: Job; realThemes: string[] }) {
  const [raw, setRaw] = useState<AnswerMapResponse | null>(null)
  useEffect(() => {
    let live = true
    getAnswerMap(job.dataset_id, job.column)
      .then((r) => { if (live) setRaw(r) })
      .catch(() => { /* the map is optional; the rest of the panel stands on its own */ })
    return () => { live = false }
  }, [job.id, job.dataset_id, job.column])
  const map = useMemo(() => answerMapModel(raw, isResult(job.result) ? job.result : null, realThemes),
    [raw, job.result, realThemes])
  return map ? <PointMapChart map={map} /> : null
}

function Results({ m, mapSlot }: { m: InsideOtherModel; mapSlot?: ReactNode }) {
  const largest = Math.max(0, ...m.known.map((l) => l.count))
  const largestNew = Math.max(0, ...m.newThemes.map((l) => l.count))
  const newValue = listValue(m.newThemes)
  return (
    <div className="io-results">
      <div className="io-banner">
        <span className="io-check" aria-hidden="true">✓</span>
        <p className="io-banner-text">{m.banner}</p>
      </div>
      {m.newThemes.length > 0 && (
        <ul className="io-chips" aria-label="New themes">
          {m.newThemes.map((l) => (
            <li key={l.label} className="io-newchip">
              <span className="io-newbadge">new</span>
              {l.label}
              <span className="io-newshare">{newValue(l)}</span>
            </li>
          ))}
        </ul>
      )}
      {m.subThemes.length > 0 && (
        <ul className="io-chips" aria-label="New sub-themes">
          {m.subThemes.map((st) => (
            <li key={`${st.parent}/${st.label}`} className="io-newchip">
              <span className="io-newbadge">sub</span>
              {st.label}
              <span className="io-newshare">in {st.parent} · {fmt(st.count)}</span>
            </li>
          ))}
        </ul>
      )}
      {mapSlot}
      {m.known.length > 0 && (
        <section className="io-chart">
          <h4 className="io-chart-title">What each known theme gained</h4>
          <ul className="io-gains">
            {m.known.map((l) => (
              <li key={l.label} className="io-gain">
                <span className="io-gain-name">{l.label}</span>
                <span className="io-gain-track"><span style={{ width: `${largest ? (l.count / largest) * 100 : 0}%`, background: l.color }} /></span>
                <span className="io-gain-n">
                  {hasShare(l) ? <><strong>+{l.share}%</strong> {fmt(l.count)} answers</> : <><strong>+{fmt(l.count)}</strong> answers</>}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
      {m.newThemes.length > 0 && (
        <section className="io-chart">
          <h4 className="io-chart-title">New themes, biggest first</h4>
          <ul className="io-gains">
            {m.newThemes.map((l) => {
              const tone = toneOf(l)
              return (
                <li key={l.label} className="io-gain">
                  <span className="io-gain-name">{l.label}</span>
                  <span className="io-gain-track"><span style={{ width: `${largestNew ? (l.count / largestNew) * 100 : 0}%`, background: tone.color }} /></span>
                  <span className="io-gain-n">
                    {hasShare(l) && <strong>{l.share}%</strong>} {fmt(l.count)} answers{tone.text && ` · ${tone.text}`}
                  </span>
                </li>
              )
            })}
          </ul>
        </section>
      )}
      {m.charts.icicle && (
        <section className="io-chart">
          <ThemeChart fragment={m.charts.icicle} title="What's inside the new themes" />
        </section>
      )}
    </div>
  )
}

export default function InsideOther({
  job, onStart, allThemes = [], breakdown = null, context = 'themes', note = null,
}: {
  job: Job | null
  // The themes screen runs Look inside; the report only shows an earlier run's result (no button).
  onStart?: () => void
  allThemes?: ReportThemeSummary[]
  breakdown?: ReportOtherBreakdown | null
  context?: 'themes' | 'report'
  note?: string | null // e.g. why the automatic run after a theme build did not start
}) {
  const m = useMemo(() => insideOtherModel(job, allThemes, breakdown, context), [job, allThemes, breakdown, context])
  const reducedMotion = useMemo(() => prefersReducedMotion(), [])
  const realThemes = useMemo(() => allThemes.map((t) => t.name), [allThemes])
  const [showAll, setShowAll] = useState(false)
  // The full list only adds something when real themes are folded into Other; otherwise it repeats the treemap.
  const canShowAll = (breakdown?.hidden_real_theme_count ?? 0) > 0 && allThemes.length > 0
  const toggle = canShowAll ? (
    <button type="button" className="io-link" aria-expanded={showAll} onClick={() => setShowAll(!showAll)}>
      {showAll ? 'Hide all themes' : `See all ${allThemes.length} themes`}
    </button>
  ) : null
  return (
    <section className="io" aria-labelledby="io-title">
      <div className="io-head">
        <h3 id="io-title" className="io-title">Inside Other</h3>
        {onStart && m.phase !== 'running' && (
          <button type="button" className="io-cta" onClick={onStart}>
            {m.phase === 'done' ? 'Look inside again' : 'Look inside'} <Arrow />
          </button>
        )}
      </div>
      <p className="io-status" aria-live="polite">
        {m.phase === 'running' && <span className="io-live-dot" aria-hidden="true" />}
        {m.phase === 'failed' ? m.error ?? m.status : m.status}
      </p>
      {note && m.phase === 'idle' && <p className="io-warn">{note}</p>}
      <p className="io-help">Each ribbon is a group of answers. Wider ribbon, more answers.</p>
      {m.failedCount > 0 && (
        <p className="io-warn">{fmt(m.failedCount)} answer{m.failedCount === 1 ? '' : 's'} could not be checked and stayed in Other.</p>
      )}
      <InsideOtherFlow model={m} reducedMotion={reducedMotion} />
      <Columns m={m} allThemesToggle={toggle} />
      {canShowAll && showAll && <AllThemes themes={allThemes} />}
      {m.phase !== 'idle' && <Steps m={m} />}
      {m.phase === 'done' && m.banner && (
        <Results m={m} mapSlot={job && <AnswerMap job={job} realThemes={realThemes} />} />
      )}
    </section>
  )
}
