import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import type { JobListEntry } from './jobsApi'
import { JobsView } from './Jobs'

// Pure, props-driven component - same `renderToStaticMarkup` + `MemoryRouter` precedent as
// projects.test.tsx (needed here too: rows link to each dataset's report via react-router `Link`).

const NOW = new Date('2026-10-23T12:00:00Z').getTime()

function job(overrides: Partial<JobListEntry> = {}): JobListEntry {
  return {
    id: 1, dataset_id: 12, dataset_name: 'office-survey.csv', column: 'Comment',
    kind: 'look_inside_other', status: 'running', step: 'Finalizing', error: null, result: null,
    created_at: '2026-10-23T11:58:00Z', updated_at: '2026-10-23T11:59:30Z',
    ...overrides,
  }
}

function render(jobs: JobListEntry[] | null, extra: Partial<Parameters<typeof JobsView>[0]> = {}): string {
  return renderToStaticMarkup(
    <MemoryRouter>
      <JobsView jobs={jobs} filter="all" onFilterChange={vi.fn()} error="" now={NOW} {...extra} />
    </MemoryRouter>,
  )
}

describe('JobsView', () => {
  it('shows a loading state before the first fetch resolves', () => {
    const html = render(null)
    expect(html).toContain('Loading')
  })

  it('shows an empty state scoped to the active filter', () => {
    const html = render([], { filter: 'failed' })
    expect(html).toContain('No failed jobs')
  })

  it('renders the dataset, column, kind and status for each job, linking to its report', () => {
    const html = render([job()])
    expect(html).toContain('office-survey.csv')
    expect(html).toContain('href="/report?dataset=12"')
    expect(html).toContain('Comment')
    expect(html).toContain('Look inside Other')
    expect(html).toContain('jb-status-running')
  })

  it('shows the real error message instead of the step for a failed job', () => {
    const html = render([job({ status: 'failed', error: 'Jev returned HTTP 401.', step: 'Finalizing' })])
    expect(html).toContain('Jev returned HTTP 401.')
  })

  it('shows relative ages for started/updated, falling back to a dash when missing', () => {
    const withTimes = render([job()])
    expect(withTimes).toContain('2m ago') // created_at: 2 min before NOW
    expect(withTimes).toContain('30s ago') // updated_at: 30s before NOW

    const withoutTimes = render([job({ created_at: undefined, updated_at: undefined })])
    expect(withoutTimes).toContain('—')
  })

  it('surfaces a fetch error without crashing', () => {
    const html = render(null, { error: 'Something went wrong (500).' })
    expect(html).toContain('Something went wrong (500).')
  })
})
