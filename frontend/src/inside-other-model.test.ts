import { describe, expect, it } from 'vitest'
import { insideOtherModel, MAX_KNOWN_LEAVES } from './insideOtherModel'
import type { Job, LookInsideOtherResult } from './jobsApi'
import type { ReportThemeSummary } from './reportApi'

const themes: ReportThemeSummary[] = ['Cost', 'Charging', 'Range', 'Doubts', 'Availability', 'Support', 'Noise', 'Parking']
  .map((name, i) => ({ name, share: 20 - i, count: 200 - i * 10, sentiment: 0 }))

const job = (o: Partial<Job>): Job => ({
  id: 1, dataset_id: 1, column: 'Why', kind: 'look_inside_other', status: 'running', step: 'Starting',
  error: null, result: null, ...o,
})

const result = (o: Partial<LookInsideOtherResult> = {}): LookInsideOtherResult => ({
  known_added: 180, still_other_count: 3716, failed_classification_count: 0,
  new_themes: [
    { label: 'Parking access', count: 122, sentiment: -0.3, tone: { neg: 62, neu: 26, pos: 12 } },
    { label: 'Elevators', count: 87, sentiment: -0.2, tone: { neg: 51, neu: 35, pos: 14 } },
  ],
  other_before_count: 4402, answered_total: 5830,
  known_gains: [{ label: 'Charging', count: 41 }, { label: 'Cost', count: 52 }],
  ...o,
})

describe('insideOtherModel', () => {
  it('idle: nothing counted yet', () => {
    const m = insideOtherModel(null, themes)
    expect(m.phase).toBe('idle')
    expect(m.still).toBeNull()
    expect(m.known).toEqual([])
  })

  it('running before matching starts: right step, no invented numbers', () => {
    const m = insideOtherModel(job({ step: 'Sorting into main themes and sub-themes' }), themes)
    expect(m.phase).toBe('running')
    expect(m.stepIndex).toBe(1)
    expect(m.status).toBe('Sorting into main themes and sub-themes...')
    expect(m.still).toBeNull()
    expect(m.known).toEqual([])
  })

  it('running while matching: live counts from progress, unmatched answers still count as Other', () => {
    const m = insideOtherModel(job({
      step: 'Matching answers to themes',
      progress: { done: 400, total: 1000, known: { Cost: 120, Range: 30 }, new: { 'Parking access': 50 }, still_other: 200 },
    }), themes)
    expect(m.stepIndex).toBe(2)
    expect(m.matchingProgress).toBeCloseTo(0.4)
    expect(m.status).toBe('Matching answers to themes... 400 of 1,000')
    expect(m.known.map((l) => [l.label, l.count])).toEqual([['Cost', 120], ['Range', 30]])
    expect(m.knownTotal).toBe(150)
    expect(m.newTotal).toBe(50)
    expect(m.still).toBe(600 + 200) // 600 not matched yet + 200 matched back to Other
    expect(m.sourceTotal).toBe(1000)
  })

  it('known themes keep their treemap colours (largest real theme first)', () => {
    const m = insideOtherModel(job({ status: 'done', step: 'Done', result: result() }), themes)
    expect(m.known.find((l) => l.label === 'Cost')?.color).toBe('var(--t1)')
    expect(m.known.find((l) => l.label === 'Charging')?.color).toBe('var(--t2)')
  })

  it('done: real numbers, shares of all answers, before/after and the banner', () => {
    const m = insideOtherModel(job({ status: 'done', step: 'Done', result: result() }), themes)
    expect(m.phase).toBe('done')
    expect(m.stepIndex).toBe(4)
    expect(m.known.map((l) => l.label)).toEqual(['Cost', 'Charging']) // largest gain first
    expect(m.known[0].share).toBe(0.9) // 52 / 5830
    expect(m.knownTotal).toBe(180)
    expect(m.newTotal).toBe(209)
    expect(m.still).toBe(3716)
    expect(m.otherBeforePct).toBe(75.5)
    expect(m.otherNowPct).toBe(63.7)
    expect(m.banner).toBe('Done. 2 new themes found. Other went from 75.5% to 63.7%.')
  })

  it('done, older run without the new fields: totals only, no invented before/after', () => {
    const legacy = result({ other_before_count: undefined, answered_total: undefined, known_gains: undefined })
    const m = insideOtherModel(job({ status: 'done', step: 'Done', result: legacy }), themes)
    expect(m.known).toEqual([])
    expect(m.knownTotal).toBe(180)
    expect(m.otherBeforePct).toBeNull()
    expect(m.banner).toBe('Done. 2 new themes found.')
  })

  it('caps the drawn known leaves and counts the rest', () => {
    const gains = Array.from({ length: 10 }, (_, i) => ({ label: `T${i}`, count: 100 - i }))
    const m = insideOtherModel(job({ status: 'done', step: 'Done', result: result({ known_gains: gains }) }), themes)
    expect(m.known).toHaveLength(MAX_KNOWN_LEAVES)
    expect(m.knownMore).toBe(3)
  })

  it('failed: shows the real error', () => {
    const m = insideOtherModel(job({ status: 'failed', error: 'Jev returned HTTP 401.' }), themes)
    expect(m.phase).toBe('failed')
    expect(m.error).toBe('Jev returned HTTP 401.')
  })
})

describe('listValue', () => {
  it('uses one unit per list: counts for every row once any share is too small to print', async () => {
    const { listValue } = await import('./insideOtherModel')
    const leaf = (count: number, share: number) => ({ label: String(count), count, share, color: '', onColor: '' })
    const mixed = [leaf(40, 0.1), leaf(19, 0.05)]
    expect(mixed.map(listValue(mixed))).toEqual(['40', '19'])
    const shares = [leaf(400, 1), leaf(200, 0.5)]
    expect(shares.map(listValue(shares, '+'))).toEqual(['+1%', '+0.5%'])
  })
})

describe('insideOtherModel point map', () => {
  const pointMap = {
    groups: [
      { kind: 'known' as const, label: 'Cost' }, { kind: 'still' as const, label: 'Other' },
      { kind: 'new' as const, label: 'Elevators' }, { kind: 'new' as const, label: 'Parking access' },
      { kind: 'known' as const, label: 'Parking' }, // 8th real theme: outside the treemap's seven colours
    ],
    points: [[0.1, 0.2, 0], [0.3, 0.4, 1], [0.5, 0.6, 2], [0.7, 0.8, 3], [0.9, 0.1, 3], [0.2, 0.2, 4]] as Array<[number, number, number]>,
  }

  it('colours each group like its row or leaf, and draws Other first so themes sit on top', () => {
    const m = insideOtherModel(job({ status: 'done', step: 'Done', result: result({ point_map: pointMap }) }), themes)
    const byLabel = Object.fromEntries(m.pointMap!.groups.map((g) => [g.label, g]))
    expect(m.pointMap!.groups[0].kind).toBe('still')
    expect(byLabel.Other.color).toBe('var(--other)')
    expect(byLabel.Cost.color).toBe(m.known.find((l) => l.label === 'Cost')!.color)
    expect(byLabel.Parking.color).toBe('var(--muted)') // not mistaken for "still in Other"
    // New themes keep the accent step of their leaf (ranked by size).
    expect(byLabel['Parking access'].color).toBe(m.newThemes[0].color)
    expect(byLabel.Elevators.color).toBe(m.newThemes[1].color)
    expect(byLabel['Parking access'].dots).toBe(2)
    // Every point still points at its own group after reordering.
    for (const [x, , g] of m.pointMap!.points) {
      const original = pointMap.points.find(([px]) => px === x)!
      expect(m.pointMap!.groups[g].label).toBe(pointMap.groups[original[2]].label)
    }
    expect(m.pointMap!.sampled).toBe(true) // 6 dots for 4,402 answers
  })

  it('no map for older runs, or while running', () => {
    expect(insideOtherModel(job({ status: 'done', step: 'Done', result: result() }), themes).pointMap).toBeNull()
    expect(insideOtherModel(job({}), themes).pointMap).toBeNull()
  })
})
