// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ProjectSummary } from './projectsApi'

const getProjects = vi.fn<() => Promise<ProjectSummary[]>>()
vi.mock('./projectsApi', () => ({ getProjects: () => getProjects() }))
const { default: ReportsIndex } = await import('./ReportsIndex')

const p = (id: number, status: ProjectSummary['status'], question: string | null = `Question ${id}`): ProjectSummary =>
  ({ id, filename: `file${id}.csv`, question, row_count: 10000, created_at: '2026-10-01T00:00:00Z', status })

let container: HTMLDivElement
let root: Root
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

async function render() {
  await act(async () => { root.render(<MemoryRouter><ReportsIndex /></MemoryRouter>) })
}

describe('Reports with no project picked (BUG-062)', () => {
  it('lists projects with a report, then the ones still waiting, each linking to its report', async () => {
    getProjects.mockResolvedValue([p(3, 'report ready'), p(2, 'themes built'), p(1, 'uploaded'), p(4, 'report ready', null)])
    await render()
    const links = Array.from(container.querySelectorAll('a.pr-link')).map((a) => [a.getAttribute('href'), a.textContent])
    expect(links.map((l) => l[0])).toEqual(['/report?dataset=3', '/report?dataset=4', '/report?dataset=2'])
    expect(links[1][1]?.match(/file4\.csv/g)).toHaveLength(1) // no question confirmed: the file name, once
    expect(container.textContent).toContain('No report yet')
    expect(container.textContent).not.toContain('Nothing to report yet')
  })

  it('says to upload when nothing has reached a report', async () => {
    getProjects.mockResolvedValue([p(1, 'uploaded')])
    await render()
    expect(container.textContent).toContain('Nothing to report yet')
  })
})
