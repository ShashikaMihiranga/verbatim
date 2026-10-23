import type { ReportThemeSummary } from './reportApi'

// Stage 3b (docs/TODO.md, fixed 2026-10-23): the real ribbon-flow animation from the mockup
// (Other-Flow-Mid.dc.html), replacing the earlier placeholder's single generic dashed strip. Ribbons
// fan out from one "Other" source point to one destination per KNOWN theme (real data - `allThemes`,
// already-sorted largest-first, same `report.all_themes` the "see all themes" list already uses) plus
// one "New themes" destination. Capped at the same 7 themes the treemap's own palette supports (`--t1`
// .. `--t7`) - an 8th+ known theme has no color token to borrow, same constraint every other chart in
// this app already respects.
//
// Ribbon WIDTH is each known theme's REAL CURRENT share (honest, already-known data) - never a live
// per-destination count, since the backend only reports coarse step names while this job runs (see
// LookInsideOther.tsx's own comment for why). The flowing-dash motion is a pure activity indicator, the
// same honesty line this app already draws for a plain spinner - it does not claim to show live
// progress toward any particular destination.

const MAX_KNOWN_RIBBONS = 7
const COLOR_TOKENS = ['--t1', '--t2', '--t3', '--t4', '--t5', '--t6', '--t7']

function ribbonPath(sx: number, sy: number, dx: number, dy: number): string {
  const midX = (sx + dx) / 2
  return `M${sx} ${sy} C ${midX} ${sy}, ${midX} ${dy}, ${dx} ${dy}`
}

export default function LookInsideOtherRibbons({ allThemes }: { allThemes: ReportThemeSummary[] }) {
  const known = allThemes.slice(0, MAX_KNOWN_RIBBONS)
  // "New themes" is always included as a destination, even with no real share yet (nothing is known
  // about it until the job finishes) - drawn as a thin, muted ribbon rather than omitted, so the
  // diagram reads as "this is where new discoveries will land," not a missing destination.
  const destinations: Array<{ label: string; share: number; color: string }> = [
    ...known.map((t, i) => ({ label: t.name, share: t.share, color: `var(${COLOR_TOKENS[i]})` })),
    { label: 'New themes', share: 0, color: 'var(--accent)' },
  ]

  const width = 760
  const rowH = 34
  const topPad = 16
  const height = topPad * 2 + destinations.length * rowH
  const sx = 70
  const sy = height / 2
  const dx = width - 170

  const maxShare = Math.max(1, ...known.map((t) => t.share))

  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }} aria-hidden="true">
      <circle cx={sx} cy={sy} r="22" style={{ fill: 'var(--other)' }} />
      <text x={sx} y={sy - 32} textAnchor="middle" style={{ fontSize: 13, fontWeight: 600, fill: 'var(--ink)' }}>
        Other
      </text>
      {destinations.map((d, i) => {
        const dy = topPad + rowH * i + rowH / 2
        const isNew = d.label === 'New themes'
        const strokeWidth = isNew ? 4 : Math.max(3, (d.share / maxShare) * 16)
        return (
          <g key={d.label}>
            <path
              d={ribbonPath(sx + 20, sy, dx - 10, dy)}
              className={isNew ? 'lio-ribbon lio-ribbon-new' : 'lio-ribbon'}
              style={{ stroke: d.color, strokeWidth, fill: 'none', opacity: isNew ? 0.55 : 0.75 }}
            />
            <circle cx={dx} cy={dy} r="7" style={{ fill: d.color }} />
            <text x={dx + 14} y={dy} dominantBaseline="central" style={{ fontSize: 12.5, fontWeight: 600, fill: 'var(--ink)' }}>
              {d.label}
              {!isNew && <tspan style={{ fontWeight: 400, fill: 'var(--muted)' }}> {d.share}%</tspan>}
            </text>
          </g>
        )
      })}
    </svg>
  )
}
