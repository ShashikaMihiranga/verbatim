import { centreline, flowRibbons, LY, OW, OX, ribbonPath, TOP, W } from './insideOtherGeometry'
import type { InsideOtherModel } from './insideOtherModel'

// Draws the flow computed in insideOtherGeometry.ts (the design's ribbons: wider ribbon, more answers).
export default function InsideOtherFlow({ model, reducedMotion }: { model: InsideOtherModel; reducedMotion: boolean }) {
  const ribbons = flowRibbons(model)
  const moving = model.phase === 'running' && !reducedMotion
  return (
    <svg className="io-flow" viewBox={`0 0 ${W} ${LY + 56}`} role="img"
      aria-label="Answers flowing from Other to known themes, new themes and Still in Other">
      <rect x={OX} y={0} width={OW} height={TOP - 6} rx={4} fill="var(--other)" />
      <text x={OX + 12} y={(TOP - 6) / 2} dominantBaseline="central" className="io-flow-source">Other</text>
      {ribbons.map((r, i) => {
        const { sa, sb } = r
        const centre = (sa + sb) / 2
        const dur = r.still ? 3.4 : 2.3
        const dots = moving && r.w > 0.5 ? Math.min(8, Math.max(1, Math.round(Math.sqrt(Math.max(r.count, 1)) / 7))) : 0
        return (
          <g key={r.key} data-ribbon={r.still ? 'still' : 'theme'}>
            <path d={ribbonPath(sa, sb, r.x, r.w)} fill={r.color} opacity={r.still ? 0.5 : 0.84} />
            {Array.from({ length: dots }, (_, k) => (
              <circle key={k} r={Math.min(6, Math.max(3.4, r.w * 0.45))} fill="var(--surface)" stroke={r.color} strokeWidth={2}>
                <animateMotion dur={`${dur}s`} repeatCount="indefinite" begin={`${(-(k * dur) / dots - i * 0.17).toFixed(2)}s`}
                  path={centreline(centre, r.x)} />
              </circle>
            ))}
            <rect x={r.x - r.w / 2} y={LY} width={r.w} height={6} fill={r.color} />
            {model.phase === 'running' && <circle className="io-leaf-ring" cx={r.x} cy={LY + 3} r={r.still ? 11 : 9} fill="none" stroke={r.color} strokeWidth={2.4} />}
            {r.number !== null ? (
              <g>
                <circle cx={r.x} cy={LY + 30} r={11} fill={r.color} />
                <text x={r.x} y={LY + 30} textAnchor="middle" dominantBaseline="central" className="io-flow-n"
                  fill={ribbonTextColor(model, r.key)}>{r.number}</text>
              </g>
            ) : (
              <text x={r.x} y={LY + 30} textAnchor="middle" dominantBaseline="central" className="io-flow-still">Still in Other</text>
            )}
          </g>
        )
      })}
    </svg>
  )
}

function ribbonTextColor(model: InsideOtherModel, label: string): string {
  const leaf = [...model.known, ...model.newThemes].find((l) => l.label === label)
  return leaf?.onColor ?? 'var(--ink)'
}
