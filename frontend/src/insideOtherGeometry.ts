import type { InsideOtherModel, Leaf } from './insideOtherModel'

// The design's flow (verbatim-visual-system/generator/gen_otherflow.py): ribbons leave Other along its
// bottom edge and land on one leaf per destination. Wider ribbon, more answers.
export const W = 1328
export const TOP = 30 // Other strip sits above the ribbons
export const LY = 290 // leaf line
export const OW = 259.3
// Other's left edge: centred over the flow, so ribbons fan out to both sides (user decision 2026-10-25;
// the design put it top right, over the treemap's Other block).
export const OX = (W - OW) / 2
const USABLE = OW - 24
const MIN_W = 3.6
const KNOWN_X = (i: number) => 60 + 66 * i
const NEW_X = (j: number) => 520 + 66 * j
const STILL_X = 1115

export interface Ribbon {
  key: string
  sa: number // start and end along Other's bottom edge
  sb: number
  x: number // leaf centre
  w: number
  color: string
  number: string | null
  count: number
  still?: boolean
}

export function ribbonPath(sa: number, sb: number, x: number, w: number): string {
  const da = x - w / 2
  const db = x + w / 2
  const mid = (TOP + LY) / 2
  return `M${sa.toFixed(1)} ${TOP} C${sa.toFixed(1)} ${mid}, ${da.toFixed(1)} ${mid}, ${da.toFixed(1)} ${LY} `
    + `L${db.toFixed(1)} ${LY} C${db.toFixed(1)} ${mid}, ${sb.toFixed(1)} ${mid}, ${sb.toFixed(1)} ${TOP} Z`
}

export function centreline(s: number, x: number): string {
  const mid = (TOP + LY) / 2
  return `M${s.toFixed(1)} ${TOP} C${s.toFixed(1)} ${mid}, ${x.toFixed(1)} ${mid}, ${x.toFixed(1)} ${LY}`
}

export function flowRibbons(model: InsideOtherModel): Ribbon[] {
  const total = model.sourceTotal && model.sourceTotal > 0 ? model.sourceTotal : null
  const width = (n: number) => (total ? Math.max(MIN_W, (n * USABLE) / total) : MIN_W)
  const leaf = (l: Leaf, x: number, n: number): Ribbon => ({ key: l.label, sa: 0, sb: 0, x, w: width(l.count), color: l.color, number: String(n), count: l.count })
  const out: Ribbon[] = [
    ...model.known.map((l, i) => leaf(l, KNOWN_X(i), i + 1)),
    ...model.newThemes.map((l, j) => leaf(l, NEW_X(j), j + 1)),
  ]
  const used = out.reduce((s, r) => s + r.w, 0)
  // Still in Other takes what is left of Other's edge (all of it before anything is sorted).
  out.push({ key: 'still', sa: 0, sb: 0, x: STILL_X, w: Math.max(MIN_W, USABLE - used), color: 'var(--other)', number: null, count: model.still ?? 0, still: true })
  let cursor = OX + 12
  for (const r of out) {
    r.sa = cursor
    r.sb = cursor + r.w
    cursor = r.sb
  }
  return out
}

export function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches
}
