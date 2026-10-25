// Everything the "Inside Other" panel shows, computed in one place from the job and the report's theme
// list, so the components only draw it (docs/REPORT_UI_REWORK.md, Phase 2). Live counts come from
// `job.progress` while answers are matched; the finished picture comes from `job.result`.
import type { Job, LookInsideOtherChart, LookInsideOtherResult } from './jobsApi'
import type { ReportOtherBreakdown, ReportThemeSummary } from './reportApi'
import type { AnswerMapResponse } from './themesApi'

// Same labels the server sets in app/api_themes.py `_start_look_inside`.
export const STEPS = ['Finding new groups', 'Sorting into main themes and sub-themes', 'Matching answers to themes', 'Updating the themes'] as const
// The automatic run (after a theme build) waits for a free slot before its first step.
const WAITING = 'Waiting to start'
const MATCHING_STEP = 2

export const MAX_KNOWN_LEAVES = 7
export const MAX_NEW_LEAVES = 6
// New themes are not in the treemap yet, so they get an accent ladder rather than theme colours.
const NEW_TINTS = [100, 82, 68, 56, 44, 34]

export type Phase = 'idle' | 'running' | 'done' | 'failed'

export interface PointGroup {
  // "minor": a known theme outside the treemap's top seven, drawn pale so the main clouds stand out.
  kind: 'known' | 'minor' | 'new' | 'still'
  label: string
  color: string
  dots: number // dots drawn for this group (a sample when Other was large)
  at: [number, number] | null // where its name is written: the middle of its cloud; null = no label
}
export interface PointMap {
  groups: PointGroup[] // still in Other first, then minor, known, new: later groups draw on top
  points: Array<[number, number, number]> // x, y (0..1, y down), index into `groups`
  sampled: boolean // fewer dots than answers
}

// Below this share of the dots a cloud is too small to name on the map; the legend still lists it.
const LABEL_MIN_SHARE = 0.02
const median = (v: number[]) => {
  const s = [...v].sort((a, b) => a - b)
  return s.length % 2 ? s[(s.length - 1) / 2] : (s[s.length / 2 - 1] + s[s.length / 2]) / 2
}

export interface Leaf {
  label: string
  count: number
  color: string // CSS colour value
  onColor: string // readable text colour on top of `color`
  share: number | null // % of all answered answers, when the total is known
  tone?: { neg: number; neu: number; pos: number } // new themes only, once matching is done
}

export interface InsideOtherModel {
  phase: Phase
  status: string
  stepIndex: number // 0..3 running step; 4 when done
  matchingProgress: number // 0..1 within "Matching answers to themes"
  known: Leaf[]
  knownMore: number // known themes beyond the drawn leaves
  knownTotal: number
  newThemes: Leaf[]
  newMore: number
  newTotal: number
  still: number | null // answers still in Other; null before any count is known
  sourceTotal: number | null // Other's answers being sorted, for ribbon widths
  answeredTotal: number | null
  otherBeforePct: number | null
  otherNowPct: number | null
  banner: string | null
  failedCount: number
  subThemes: Array<{ label: string; parent: string; count: number }> // new sub-themes inside known themes
  error: string | null
  charts: { icicle?: LookInsideOtherChart }
}

const pct = (part: number, whole: number | null) => (whole ? Math.round((part / whole) * 1000) / 10 : null)

// A share that rounds to 0.0% would print a real gain as "+0%" (BUG-045: 18 of 39,718 answers), so a
// leaf only shows its share when it is at least 0.1%; otherwise it shows the answer count.
export const hasShare = (l: Leaf): l is Leaf & { share: number } => l.share !== null && l.share >= 0.1

export function shareOrCount(l: Leaf, sign = ''): string {
  return hasShare(l) ? `${sign}${l.share}%` : `${sign}${l.count.toLocaleString('en-US')}`
}

// One unit per list: if any row's share is too small to print, every row shows its answer count, so a
// column never mixes "0.1%" and "19".
export function listValue(items: Leaf[], sign = ''): (l: Leaf) => string {
  const byCount = items.some((l) => !hasShare(l))
  return (l) => (byCount ? `${sign}${l.count.toLocaleString('en-US')}` : shareOrCount(l, sign))
}

function knownColor(label: string, realThemes: string[]): { color: string; onColor: string } {
  // Same colour the theme has in the treemap: the first 7 real themes (largest first) get --t1..--t7.
  const i = realThemes.indexOf(label)
  if (i >= 0 && i < 7) {
    const dark = i === 0 || i === 1 || i === 4 // --t1, --t2, --t5 carry white text
    return { color: `var(--t${i + 1})`, onColor: dark ? '#ffffff' : 'var(--ink)' }
  }
  return { color: 'var(--other)', onColor: 'var(--ink)' }
}

function newColor(j: number): { color: string; onColor: string } {
  const mix = NEW_TINTS[Math.min(j, NEW_TINTS.length - 1)]
  return { color: `color-mix(in srgb, var(--accent) ${mix}%, var(--surface))`, onColor: mix >= 68 ? '#ffffff' : 'var(--ink)' }
}

function leaves(
  entries: Array<{ label: string; count: number }>,
  max: number,
  color: (label: string, i: number) => { color: string; onColor: string },
  answered: number | null,
): { shown: Leaf[]; more: number; total: number } {
  const sorted = [...entries].filter((e) => e.count > 0).sort((a, b) => b.count - a.count)
  return {
    shown: sorted.slice(0, max).map((e, i) => ({ ...e, ...color(e.label, i), share: pct(e.count, answered) })),
    more: Math.max(0, sorted.length - max),
    total: sorted.reduce((sum, e) => sum + e.count, 0),
  }
}

const fromRecord = (r: Record<string, number> | undefined) => Object.entries(r ?? {}).map(([label, count]) => ({ label, count }))

// The scatter plot under Inside Other: every theme's answers (GET /themes/answer-map), coloured like the
// panel's numbered rows (known themes) and leaves (this run's new themes); Other is grey and drawn first.
export function answerMapModel(
  raw: AnswerMapResponse | null, r: LookInsideOtherResult | null, realThemes: string[],
): PointMap | null {
  // Only a layout by meaning (UMAP) shows groups; an older PCA layout piles every theme together.
  if (!raw || raw.points.length === 0 || raw.layout !== 'umap') return null
  const newThemes = r?.new_themes ?? []
  const isNew = new Set(newThemes.map((t) => t.label))
  const kindOf = (g: { label: string; other: boolean }): PointGroup['kind'] => {
    if (g.other) return 'still'
    if (isNew.has(g.label)) return 'new'
    return knownColor(g.label, realThemes).color === 'var(--other)' ? 'minor' : 'known'
  }
  // New themes take the same accent step as their leaf in the columns: ranked by size.
  const newRank = [...newThemes].sort((a, b) => b.count - a.count).map((t) => t.label)
  const colorOf = (kind: PointGroup['kind'], label: string) => {
    if (kind === 'new') return newColor(Math.max(0, newRank.indexOf(label))).color
    if (kind === 'known') return knownColor(label, realThemes).color
    if (kind === 'minor') return 'color-mix(in srgb, var(--muted) 35%, var(--surface))'
    return 'var(--other)'
  }
  const xs: number[][] = raw.groups.map(() => [])
  const ys: number[][] = raw.groups.map(() => [])
  for (const [x, y, g] of raw.points) {
    xs[g]?.push(x)
    ys[g]?.push(y)
  }
  const rank = (k: PointGroup['kind']) => ['still', 'minor', 'known', 'new'].indexOf(k)
  const sorted = raw.groups.map((g, i) => ({ label: g.label, kind: kindOf(g), i, dots: xs[i].length }))
    .filter((g) => g.dots > 0)
    .sort((a, b) => rank(a.kind) - rank(b.kind) || b.dots - a.dots)
  const remap = new Map(sorted.map((g, j) => [g.i, j]))
  const named = (g: { kind: PointGroup['kind']; dots: number }) =>
    (g.kind === 'known' || g.kind === 'new') && g.dots >= raw.points.length * LABEL_MIN_SHARE
  return {
    groups: sorted.map((g) => ({
      kind: g.kind, label: g.label, color: colorOf(g.kind, g.label), dots: g.dots,
      at: named(g) ? [median(xs[g.i]), median(ys[g.i])] : null,
    })),
    points: raw.points.filter(([, , g]) => remap.has(g)).map(([x, y, g]) => [x, y, remap.get(g)!]),
    sampled: raw.points.length < raw.answers,
  }
}

// Answer map geometry (InsideOther.tsx PointMapChart), in the SVG's own units.
export const MAP_W = 1000
export const MAP_H = 520
export const MAP_PAD = 12
const MAP_LABEL_MAX = 30 // characters; the legend and the dot's tooltip carry the full name
const LABEL_EM = 0.56 // average Jost character width at weight 600, in em
const LABEL_FS = 15
const LABEL_H = 22

export const shortName = (s: string) => (s.length > MAP_LABEL_MAX ? `${s.slice(0, MAP_LABEL_MAX - 1).trimEnd()}…` : s)

// Where each named cloud's label goes: kept inside the plot, and moved a line down or up (or left out)
// when it would cover a bigger cloud's label. Biggest clouds are placed first. Pure, for the tests.
export function placeLabels(
  wanted: Array<{ gi: number; x: number; y: number; text: string; dots: number }>,
): Array<{ gi: number; x: number; y: number; text: string }> {
  const placed: Array<{ gi: number; x: number; y: number; text: string; w: number }> = []
  const hits = (x: number, y: number, w: number) =>
    placed.some((p) => Math.abs(p.x - x) < (p.w + w) / 2 + 6 && Math.abs(p.y - y) < LABEL_H)
  for (const l of [...wanted].sort((a, b) => b.dots - a.dots)) {
    const w = l.text.length * LABEL_FS * LABEL_EM
    const x = Math.min(MAP_W - MAP_PAD - w / 2, Math.max(MAP_PAD + w / 2, l.x))
    const clampY = (v: number) => Math.min(MAP_H - MAP_PAD - LABEL_H / 2, Math.max(MAP_PAD + LABEL_H / 2, v))
    const y = [l.y, l.y + LABEL_H, l.y - LABEL_H].map(clampY).find((v) => !hits(x, v, w))
    if (y !== undefined) placed.push({ gi: l.gi, x, y, text: l.text, w })
  }
  return placed.map(({ gi, x, y, text }) => ({ gi, x, y, text }))
}


export function isResult(r: Job['result']): r is LookInsideOtherResult {
  return r !== null && typeof r === 'object' && 'known_added' in r
}

export function insideOtherModel(
  job: Job | null,
  allThemes: ReportThemeSummary[],
  breakdown: ReportOtherBreakdown | null = null,
  // Where the panel sits: on the themes screen the updated themes follow it; in the report it only
  // shows what an earlier run did.
  context: 'themes' | 'report' = 'themes',
): InsideOtherModel {
  const realThemes = allThemes.map((t) => t.name)
  // Before a run (or after a failed one) everything in Other is still there: the report's own count.
  const base: InsideOtherModel = {
    phase: 'idle', status: '', stepIndex: -1, matchingProgress: 0,
    known: [], knownMore: 0, knownTotal: 0, newThemes: [], newMore: 0, newTotal: 0,
    still: breakdown?.noise_count ?? null, sourceTotal: null, answeredTotal: null, otherBeforePct: null,
    otherNowPct: breakdown?.noise_share ?? null,
    banner: null, failedCount: 0, subThemes: [], error: null, charts: {},
  }
  if (!job) return base

  if (job.status === 'failed') {
    return { ...base, phase: 'failed', status: 'This run did not finish.', error: job.error }
  }

  if (job.status === 'running' && job.step === WAITING) {
    return { ...base, phase: 'running', stepIndex: 0, status: 'Starting...', still: null, otherNowPct: null }
  }

  if (job.status === 'running') {
    const stepIndex = Math.max(0, STEPS.indexOf(job.step as (typeof STEPS)[number]))
    const p = job.progress ?? null
    const model: InsideOtherModel = { ...base, phase: 'running', stepIndex, status: `${STEPS[stepIndex]}...`, still: null, otherNowPct: null }
    if (!p || p.total <= 0) return model
    const known = leaves(fromRecord(p.known), MAX_KNOWN_LEAVES, (l) => knownColor(l, realThemes), null)
    const fresh = leaves(fromRecord(p.new), MAX_NEW_LEAVES, (_l, i) => newColor(i), null)
    return {
      ...model,
      stepIndex: Math.max(stepIndex, MATCHING_STEP),
      status: `${STEPS[Math.max(stepIndex, MATCHING_STEP)]}... ${p.done.toLocaleString('en-US')} of ${p.total.toLocaleString('en-US')}`,
      matchingProgress: Math.min(1, p.done / p.total),
      known: known.shown, knownMore: known.more, knownTotal: known.total,
      newThemes: fresh.shown, newMore: fresh.more, newTotal: fresh.total,
      // Answers not matched yet are still in Other, alongside the ones already sent back there.
      still: p.total - p.done + p.still_other,
      sourceTotal: p.total,
    }
  }

  // done
  const r = isResult(job.result) ? job.result : null
  if (!r) return { ...base, phase: 'done', stepIndex: STEPS.length, status: 'Done.', still: null, otherNowPct: null }
  const answered = r.answered_total ?? null
  const known = leaves(r.known_gains ?? [], MAX_KNOWN_LEAVES, (l) => knownColor(l, realThemes), answered)
  const fresh = leaves(r.new_themes.map((t) => ({ label: t.label, count: t.count })), MAX_NEW_LEAVES, (_l, i) => newColor(i), answered)
  const toneOf = new Map(r.new_themes.map((t) => [t.label, t.tone]))
  fresh.shown = fresh.shown.map((l) => ({ ...l, tone: toneOf.get(l.label) }))
  const newTotal = fresh.total
  const before = r.other_before_count ?? null
  const otherBeforePct = before !== null ? pct(before, answered) : null
  const otherNowPct = pct(r.still_other_count, answered)
  const k = r.new_themes.length
  const subThemes = (r.sub_theme_gains ?? []).filter((s) => s.is_sub_theme)
  const s = subThemes.length
  const parts = [k > 0 && `${k} new theme${k === 1 ? '' : 's'}`, s > 0 && `${s} new sub-theme${s === 1 ? '' : 's'} inside existing themes`]
    .filter(Boolean)
  const found = parts.length === 0 ? 'No new themes found.' : `${parts.join(' and ')} found.`
  const moved = otherBeforePct !== null && otherNowPct !== null ? ` Other went from ${otherBeforePct}% to ${otherNowPct}%.` : ''
  return {
    ...base,
    phase: 'done',
    stepIndex: STEPS.length,
    matchingProgress: 1,
    // Runs before 2026-10-25 kept no "before" chart, so the themes screen shows no separate updated chart.
    status: context === 'themes' && r.before_chart ? 'Done. The updated themes are below.' : 'Done.',
    known: known.shown, knownMore: known.more,
    // Older runs have no per-theme breakdown; the total is still real.
    knownTotal: r.known_added,
    newThemes: fresh.shown, newMore: fresh.more, newTotal,
    still: r.still_other_count,
    sourceTotal: before ?? r.known_added + newTotal + r.still_other_count,
    answeredTotal: answered,
    otherBeforePct, otherNowPct,
    banner: `Done. ${found}${moved}`,
    failedCount: r.failed_classification_count ?? 0,
    subThemes: subThemes.map(({ label, parent, count }) => ({ label, parent, count })),
    charts: { icicle: r.charts?.icicle },
  }
}
