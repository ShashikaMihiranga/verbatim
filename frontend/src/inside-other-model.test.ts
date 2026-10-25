import { describe, expect, it } from 'vitest'
import { answerMapModel, insideOtherModel, MAX_KNOWN_LEAVES } from './insideOtherModel'
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

describe('answerMapModel', () => {
  // Groups as GET /themes/answer-map returns them: every theme of the column, Other flagged.
  const raw = {
    answers: 5830,
    layout: 'umap' as const,
    groups: [
      { label: 'Cost', other: false }, { label: 'Other', other: true }, { label: 'Elevators', other: false },
      { label: 'Parking access', other: false }, { label: 'Parking', other: false }, { label: 'Empty', other: false },
    ],
    points: [[0.1, 0.2, 0], [0.3, 0.4, 1], [0.5, 0.6, 2], [0.7, 0.8, 3], [0.9, 0.1, 3], [0.2, 0.2, 4]] as Array<[number, number, number]>,
  }

  it('colours every theme like its row or leaf, Other grey and drawn first', () => {
    const r = result()
    const m = insideOtherModel(job({ status: 'done', step: 'Done', result: r }), themes)
    const map = answerMapModel(raw, r, themes.map((t) => t.name))!
    const byLabel = Object.fromEntries(map.groups.map((g) => [g.label, g]))
    expect(map.groups[0].kind).toBe('still')
    expect(byLabel.Other.color).toBe('var(--other)')
    expect(byLabel.Cost.kind).toBe('known')
    expect(byLabel.Cost.color).toBe(m.known.find((l) => l.label === 'Cost')!.color)
    // 8th real theme: pale, so the top themes stand out, and not mistaken for Other.
    expect(byLabel.Parking.kind).toBe('minor')
    expect(byLabel.Parking.color).toContain('color-mix')
    expect(byLabel.Parking.at).toBeNull() // minor themes are not named on the map
    expect(byLabel.Other.at).toBeNull()
    expect(byLabel['Parking access'].at).toEqual([0.8, 0.45]) // the middle of its two dots
    expect(map.groups.map((g) => g.kind)).toEqual(['still', 'minor', 'known', 'new', 'new'])
    expect(byLabel['Parking access'].kind).toBe('new')
    expect(byLabel['Parking access'].color).toBe(m.newThemes[0].color)
    expect(byLabel.Elevators.color).toBe(m.newThemes[1].color)
    expect(byLabel['Parking access'].dots).toBe(2)
    expect(byLabel.Empty).toBeUndefined() // a theme with no dots in the sample has no legend entry
    for (const [x, , g] of map.points) {
      const original = raw.points.find(([px]) => px === x)!
      expect(map.groups[g].label).toBe(raw.groups[original[2]].label)
    }
    expect(map.sampled).toBe(true) // 6 dots for 5,830 answers
  })

  it('without this run, every theme is a known theme; no points, no map', () => {
    const map = answerMapModel(raw, null, themes.map((t) => t.name))!
    expect(map.groups.some((g) => g.kind === 'new')).toBe(false)
    expect(answerMapModel({ ...raw, points: [] }, null, [])).toBeNull()
    expect(answerMapModel({ ...raw, layout: 'pca' }, null, [])).toBeNull() // older layout: every theme overlaps
    expect(answerMapModel(null, null, [])).toBeNull()
  })
})
