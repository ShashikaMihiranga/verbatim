// Everything the "Inside Other" panel shows, computed in one place from the job and the report's theme
// list, so the components only draw it (docs/REPORT_UI_REWORK.md, Phase 2). Live counts come from
// `job.progress` while answers are matched; the finished picture comes from `job.result`.
import type { Job, LookInsideOtherChart, LookInsideOtherResult } from './jobsApi'
import type { ReportOtherBreakdown, ReportThemeSummary } from './reportApi'

// Same labels the server sets in app/api_themes.py look_inside_other.
export const STEPS = ['Finding patterns in Other', 'Naming new themes', 'Matching answers to themes', 'Updating the report'] as const
const MATCHING_STEP = 2

export const MAX_KNOWN_LEAVES = 7
export const MAX_NEW_LEAVES = 6
// New themes are not in the treemap yet, so they get an accent ladder rather than theme colours.
const NEW_TINTS = [100, 82, 68, 56, 44, 34]

export type Phase = 'idle' | 'running' | 'done' | 'failed'

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

function isResult(r: Job['result']): r is LookInsideOtherResult {
  return r !== null && typeof r === 'object' && 'known_added' in r
}

export function insideOtherModel(
  job: Job | null,
  allThemes: ReportThemeSummary[],
  breakdown: ReportOtherBreakdown | null = null,
  // The report's findings were built before this run (BUG-046): the run updated the themes, not them.
  reportStale = false,
): InsideOtherModel {
  const realThemes = allThemes.map((t) => t.name)
  // Before a run (or after a failed one) everything in Other is still there: the report's own count.
  const base: InsideOtherModel = {
    phase: 'idle', status: '', stepIndex: -1, matchingProgress: 0,
    known: [], knownMore: 0, knownTotal: 0, newThemes: [], newMore: 0, newTotal: 0,
    still: breakdown?.noise_count ?? null, sourceTotal: null, answeredTotal: null, otherBeforePct: null,
    otherNowPct: breakdown?.noise_share ?? null,
    banner: null, failedCount: 0, error: null, charts: {},
  }
  if (!job) return base

  if (job.status === 'failed') {
    return { ...base, phase: 'failed', status: 'This run did not finish.', error: job.error }
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
  const found = k === 0 ? 'No new themes found.' : `${k} new theme${k === 1 ? '' : 's'} found.`
  const moved = otherBeforePct !== null && otherNowPct !== null ? ` Other went from ${otherBeforePct}% to ${otherNowPct}%.` : ''
  return {
    ...base,
    phase: 'done',
    stepIndex: STEPS.length,
    matchingProgress: 1,
    status: reportStale ? 'Done. Rebuild the report to update the findings.' : 'Done. The report below is updated.',
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
    charts: { icicle: r.charts?.icicle },
  }
}
