import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import InsideOther from './InsideOther'
import InsideOtherFlow from './InsideOtherFlow'
import { flowRibbons } from './insideOtherGeometry'
import { insideOtherModel } from './insideOtherModel'
import type { Job, LookInsideOtherResult } from './jobsApi'
import type { ReportThemeSummary } from './reportApi'

const themes: ReportThemeSummary[] = ['Cost', 'Charging', 'Range'].map((name, i) => ({ name, share: 30 - i, count: 300, sentiment: 0 }))
const job = (o: Partial<Job>): Job => ({
  id: 1, dataset_id: 1, column: 'Why', kind: 'look_inside_other', status: 'running', step: 'Starting',
  error: null, result: null, ...o,
})
const done: LookInsideOtherResult = {
  known_added: 93, still_other_count: 3716, failed_classification_count: 0,
  new_themes: [{ label: 'Parking access', count: 122, sentiment: -0.3, tone: { neg: 62, neu: 26, pos: 12 } }],
  other_before_count: 4402, answered_total: 5830,
  known_gains: [{ label: 'Cost', count: 52 }, { label: 'Charging', count: 41 }],
  charts: { rank: { chart_title: 'Rank themes', chart_html: '<div>RANK-CHART</div>', chart_width: 1180, chart_height: 400 } },
}
const render = (j: Job | null) => renderToStaticMarkup(<InsideOther job={j} onStart={vi.fn()} allThemes={themes} />)

describe('InsideOther', () => {
  it('idle: heading, the Look inside button and one helper line; no step rail yet', () => {
    const html = render(null)
    expect(html).toContain('Inside Other')
    expect(html).toContain('Look inside')
    expect(html).not.toContain('Look inside again')
    expect(html).toContain('Each ribbon is a group of answers. Wider ribbon, more answers.')
    expect(html).not.toContain('io-steps')
  })

  it('running: live status and counts, no button, the four real steps', () => {
    const html = render(job({
      step: 'Matching answers to themes',
      progress: { done: 500, total: 1000, known: { Cost: 300 }, new: {}, still_other: 50 },
    }))
    expect(html).not.toContain('class="io-cta"')
    expect(html).toContain('Matching answers to themes... 500 of 1,000')
    expect(html).toContain('+300')
    for (const step of ['Finding patterns in Other', 'Naming new themes', 'Matching answers to themes', 'Updating the report']) {
      expect(html).toContain(step)
    }
    expect(html.match(/data-state="done"/g)).toHaveLength(2)
    expect(html).toContain('<animateMotion') // moving dots while running
  })

  it('done: banner, before/after, per-theme gains, and one chart per question with no tabs', () => {
    const html = render(job({ status: 'done', step: 'Done', result: done }))
    expect(html).toContain('Look inside again')
    expect(html).toContain('Done. 1 new theme found. Other went from 75.5% to 63.7%.')
    expect(html).toContain('It was 75.5% before this run.')
    expect(html).toContain('What each known theme gained')
    expect(html).toContain('New themes, biggest first')
    expect(html).toContain('62% negative') // coloured by its own tone, not an assumed average
    expect(html).not.toContain('RANK-CHART')
    expect(html).not.toContain('role="tablist"')
    expect(html).not.toContain('<animateMotion')
    for (const gone of ['Sankey', 'Arc', 'Sunburst']) expect(html).not.toContain(gone)
  })

  it('failed: shows the real error and offers the button again', () => {
    const html = render(job({ status: 'failed', error: 'Jev returned HTTP 401.' }))
    expect(html).toContain('Jev returned HTTP 401.')
    expect(html).toContain('Look inside')
  })
})

describe('InsideOtherFlow', () => {
  it('one ribbon per drawn theme plus Still in Other; widths follow counts with a 3.6 minimum', () => {
    const m = insideOtherModel(job({ status: 'done', step: 'Done', result: done }), themes)
    const ribbons = flowRibbons(m)
    expect(ribbons.map((r) => r.key)).toEqual(['Cost', 'Charging', 'Parking access', 'still'])
    const cost = ribbons[0]
    const parking = ribbons[2]
    expect(cost.w).toBeGreaterThanOrEqual(3.6)
    expect(parking.w).toBeGreaterThan(cost.w) // 122 answers vs 52
    expect(ribbons[3].w).toBeGreaterThan(parking.w) // Still in Other takes the rest
  })

  it('idle draws only the Still in Other ribbon', () => {
    expect(flowRibbons(insideOtherModel(null, themes)).map((r) => r.key)).toEqual(['still'])
  })

  it('reduced motion: no moving dots even while running', () => {
    const m = insideOtherModel(job({
      step: 'Matching answers to themes',
      progress: { done: 1, total: 10, known: { Cost: 1 }, new: {}, still_other: 0 },
    }), themes)
    expect(renderToStaticMarkup(<InsideOtherFlow model={m} reducedMotion />)).not.toContain('<animateMotion')
  })
})

describe('InsideOther with the report breakdown', () => {
  const breakdown = { noise_count: 3000, noise_share: 60, hidden_real_count: 500, hidden_real_share: 10, hidden_real_theme_count: 4, total_real_theme_count: 7 }

  it('idle: Still in Other shows the current count and share, and no empty status line text', () => {
    const html = renderToStaticMarkup(<InsideOther job={null} onStart={vi.fn()} allThemes={themes} breakdown={breakdown} />)
    expect(html).toContain('3,000')
    expect(html).toContain('60% of all answers.')
    expect(html).not.toContain('before this run')
    expect(html).toContain('See all 3 themes') // themes are folded into Other, so the full list adds something
  })

  it('no See all link when nothing is folded into Other', () => {
    const html = renderToStaticMarkup(
      <InsideOther job={null} onStart={vi.fn()} allThemes={themes} breakdown={{ ...breakdown, hidden_real_theme_count: 0 }} />,
    )
    expect(html).not.toContain('See all')
  })

  it('running: the live count replaces the report count', () => {
    const html = renderToStaticMarkup(<InsideOther job={job({ step: 'Naming new themes' })} onStart={vi.fn()} allThemes={themes} breakdown={breakdown} />)
    expect(html).not.toContain('3,000')
  })
})
