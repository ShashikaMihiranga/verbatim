import { renderToStaticMarkup } from 'react-dom/server'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { ProjectsList, roundedRowCount } from './Projects'
import type { ProjectSummary } from './projectsApi'

// `ProjectsList`/`ProjectRow` are pure presentational components (the list comes in as a prop; nothing is
// fetched inside them), so they render safely with `renderToStaticMarkup` - the same style
// `report.test.tsx` and `home/home.test.tsx` already use for presentational components, the only style this
// repo's vitest config (`environment: 'node'`, no jsdom) supports. `Projects.tsx`'s default export (the
// stateful wrapper that calls `getProjects()`) has no test of its own, matching `report.test.tsx`'s own
// documented precedent for `Themes.tsx` - see docs/DECISIONS.md.
//
// `ProjectRow` renders react-router `Link`s, which need a router context - `MemoryRouter` is this repo's
// own precedent for that (see `home/home.test.tsx`), not a new pattern introduced here.
function renderList(projects: ProjectSummary[], onDelete: (p: ProjectSummary) => void = () => {}): string {
  return renderToStaticMarkup(
    <MemoryRouter>
      <ProjectsList projects={projects} onDelete={onDelete} />
    </MemoryRouter>,
  )
}

function project(overrides: Partial<ProjectSummary> = {}): ProjectSummary {
  return {
    id: 1,
    filename: 'ev-survey.csv',
    question: "Why haven't you bought an electric vehicle yet?",
    row_count: 50000,
    created_at: '2026-09-20T12:00:00Z',
    status: 'report ready',
    ...overrides,
  }
}

describe('ProjectsList', () => {
  it('shows the empty state with a link to Upload when there are no projects', () => {
    const html = renderList([])
    expect(html).toContain('No projects yet')
    expect(html).toContain('href="/upload"')
  })

  it('shows the question when present, and falls back to the filename otherwise', () => {
    const withQuestion = renderList([project()])
    expect(withQuestion).toContain('bought an electric vehicle yet?')
    expect(withQuestion).not.toContain('ev-survey.csv')

    const withoutQuestion = renderList([project({ question: null })])
    expect(withoutQuestion).toContain('ev-survey.csv')
  })

  it('shows a plain-English status for every stage, not the raw backend value', () => {
    const statuses: ProjectSummary['status'][] = [
      'uploaded',
      'columns confirmed',
      'cleaned',
      'themes built',
      'report ready',
    ]
    const html = renderList(statuses.map((status, i) => project({ id: i, status })))
    expect(html).toContain('Uploaded')
    expect(html).toContain('Columns confirmed')
    expect(html).toContain('Cleaned')
    expect(html).toContain('Themes built')
    expect(html).toContain('Report ready')
  })

  it('links each row to the screen that matches its status, using the same ?dataset= convention as Themes.tsx', () => {
    const html = renderList([
      project({ id: 11, status: 'uploaded' }),
      project({ id: 22, status: 'columns confirmed' }),
      project({ id: 33, status: 'cleaned' }),
      project({ id: 44, status: 'themes built' }),
      project({ id: 55, status: 'report ready' }),
    ])
    expect(html).toContain('href="/check-columns?dataset=11"')
    expect(html).toContain('href="/cleaning?dataset=22"')
    expect(html).toContain('href="/report?dataset=33"')
    expect(html).toContain('href="/report?dataset=44"')
    expect(html).toContain('href="/report?dataset=55"')
  })

  it('rounds the row count instead of printing the exact number', () => {
    const html = renderList([project({ row_count: 47973 })])
    expect(html).not.toContain('47973')
    expect(html).not.toContain('47,973')
    expect(html).toContain('about ') // approximate, never presented as a precise figure
  })

  it('renders a Delete button per row, accessibly labelled and not nested inside the row link', () => {
    const html = renderList([project({ id: 7, question: 'Why did you churn?' })])
    expect(html).toContain('aria-label="Delete Why did you churn?"')
    // the delete button is a <button>, siblings with (not nested inside) the row's own <a href="...">
    // link - a <button> inside an <a> would be invalid HTML and would also trigger navigation on click.
    const anchorEnd = html.indexOf('</a>')
    const buttonStart = html.indexOf('<button')
    expect(anchorEnd).toBeGreaterThan(-1)
    expect(buttonStart).toBeGreaterThan(anchorEnd)
  })
})

describe('roundedRowCount', () => {
  it('rounds instead of printing an exact count', () => {
    expect(roundedRowCount(47973)).not.toContain('47973')
    expect(roundedRowCount(47973)).not.toContain('47,973')
    expect(roundedRowCount(50000)).toBe('about 50,000 rows')
    expect(roundedRowCount(0)).toBe('0 rows')
  })
})
