import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { Job } from './jobsApi'
import LookInsideOther from './LookInsideOther'

// Static-markup only (node environment, no jsdom - same precedent as other-exploration.test.tsx and
// themechart-tabs.test.tsx). Covers each of the 4 states the component renders based on `job` alone.

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: 9, dataset_id: 1, column: 'Why', kind: 'look_inside_other',
    status: 'running', step: 'Checking known themes', error: null, result: null,
    ...overrides,
  }
}

describe('LookInsideOther', () => {
  it('idle: shows the "Look inside" CTA, no step tracker or results', () => {
    const html = renderToStaticMarkup(<LookInsideOther job={null} onStart={vi.fn()} />)
    expect(html).toContain('Look inside')
    expect(html).not.toContain('Look inside again')
    expect(html).not.toContain('Checking known themes')
  })

  it('running: shows the live step tracker and the current step, no CTA button', () => {
    const job = makeJob({ status: 'running', step: 'Grouping new themes into sub-themes' })
    const html = renderToStaticMarkup(<LookInsideOther job={job} onStart={vi.fn()} />)
    expect(html).toContain('Grouping new themes into sub-themes')
    expect(html).not.toContain('class="lio-cta"')
  })

  it('done: shows the real Known/New/Still-in-Other counts from job.result, and a re-run CTA', () => {
    const job = makeJob({
      status: 'done', step: 'Done',
      result: {
        known_added: 42,
        new_themes: [
          { label: 'Shipping delays', count: 12, sentiment: -0.4, tone: { neg: 70, neu: 20, pos: 10 } },
          { label: 'Packaging damage', count: 8, sentiment: -0.6, tone: { neg: 80, neu: 15, pos: 5 } },
        ],
        still_other_count: 30,
        charts: {
          othergrowth: { chart_title: 'New themes found', chart_html: '<svg/>', chart_width: 100, chart_height: 50 },
        },
      },
    })
    const html = renderToStaticMarkup(<LookInsideOther job={job} onStart={vi.fn()} />)
    expect(html).toContain('Look inside again')
    expect(html).toContain('42')
    expect(html).toContain('Shipping delays')
    expect(html).toContain('12')
    expect(html).toContain('Packaging damage')
    expect(html).toContain('30')
    // Stage 3c: the second tab switcher renders once result.charts exists.
    expect(html).toContain('lio-charts')
  })

  it('failed: shows the real job error, not a generic message', () => {
    const job = makeJob({ status: 'failed', error: 'Jev classification failed: simulated failure' })
    const html = renderToStaticMarkup(<LookInsideOther job={job} onStart={vi.fn()} />)
    expect(html).toContain('Jev classification failed: simulated failure')
  })
})
