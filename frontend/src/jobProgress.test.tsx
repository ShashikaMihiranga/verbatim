import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import JobProgress from './JobProgress'
import type { Job } from './jobsApi'

// `JobProgress` is a pure presentational component (the job comes in as a prop; nothing is fetched or
// polled inside it - that lives in `Themes.tsx`, via `app/jobsApi.ts:pollJob`), so it renders safely with
// `renderToStaticMarkup` - the same style `frontend/src/report.test.tsx` already uses for `ReportView`,
// and this repo's only supported style since vitest here runs with `environment: 'node'` (no jsdom). The
// stateful poller itself has no test of its own, matching `report.test.tsx`'s own documented precedent for
// `Themes.tsx` (a data-fetching wrapper needs jsdom plus fetch mocking, new test infrastructure outside
// this stream's scope) - see docs/DECISIONS.md.

function makeJob(overrides: Partial<Job> = {}): Job {
  return {
    id: 7,
    dataset_id: 1,
    column: 'Why',
    kind: 'themes',
    status: 'running',
    step: 'Naming each group',
    error: null,
    ...overrides,
  }
}

describe('JobProgress', () => {
  it('shows the current step in plain English', () => {
    const html = renderToStaticMarkup(<JobProgress job={makeJob({ step: 'Scoring tone' })} />)
    expect(html).toContain('Scoring tone')
  })

  it('names the right build for themes vs report jobs', () => {
    const themes = renderToStaticMarkup(<JobProgress job={makeJob({ kind: 'themes' })} />)
    expect(themes).toContain('Finding themes')

    const report = renderToStaticMarkup(<JobProgress job={makeJob({ kind: 'report' })} />)
    expect(report).toContain('Building your report')
  })

  it('shows a real-work indicator, never a percentage or invented count', () => {
    const html = renderToStaticMarkup(<JobProgress job={makeJob()} />)
    expect(html).toContain('jp-spinner')
    expect(html).not.toMatch(/%|\d+\s*(of|\/)\s*\d+/)
  })

  it('never claims an exact record count in its copy', () => {
    const html = renderToStaticMarkup(<JobProgress job={makeJob()} />)
    expect(html).not.toMatch(/\b\d{2,3},\d{3}\b|\b\d{4,6} (responses|answers|rows)\b/i)
  })
})
