// @vitest-environment jsdom
//
// BUG-047: on a big dataset `GET /report` takes about 6 s. Until it answers, the page must show one
// loading line, not the theme-editing view (treemap, merge list, "Build report"). The API modules are
// mocked so the real Themes page runs its page-load effect against controlled promises.
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DatasetView } from './api'
import type { ThemeCard } from './themesApi'

vi.mock('./api', async (orig) => ({ ...(await orig<typeof import('./api')>()), getProfile: vi.fn() }))
vi.mock('./themesApi', async (orig) => ({
  ...(await orig<typeof import('./themesApi')>()),
  getThemes: vi.fn(), getThemesChart: vi.fn(), getThemeAnswers: vi.fn(() => new Promise(() => {})),
}))
vi.mock('./reportApi', async (orig) => ({ ...(await orig<typeof import('./reportApi')>()), getReport: vi.fn() }))
vi.mock('./jobsApi', async (orig) => ({ ...(await orig<typeof import('./jobsApi')>()), getLatestJob: vi.fn() }))

const api = await import('./api')
const themesApi = await import('./themesApi')
const reportApi = await import('./reportApi')
const jobsApi = await import('./jobsApi')
const { default: Themes } = await import('./Themes')

const theme = (id: number, label: string): ThemeCard => ({
  id, label, description: null, size: 10, size_pct: 1, sentiment: 0,
  tone: { neg: 0, neu: 100, pos: 0 } as ThemeCard['tone'], confidence: 'solid', sub_themes: [],
})
const THEMES = ['Cost', 'Charging', 'Range', 'Parking', 'Noise', 'Seats', 'Doors', 'Lights', 'Windows', 'Office layout'].map((l, i) => theme(i + 1, l))

const dataset = {
  id: 1, filename: 'x.csv', row_count: 100, confirmed: true,
  profile: {
    row_count: 100,
    columns: [{
      name: 'Why', position: 0, kind: 'open_text', confidence: 0.9, reason: '', unit: null, distinct: 95, missing: 0,
      median_words: 10, samples: [], sensitive: false, sensitive_reason: null, is_question: false, looks_headerless: false,
    }],
  },
} as unknown as DatasetView

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} unobserve() {} })
  vi.mocked(api.getProfile).mockResolvedValue(dataset)
  vi.mocked(themesApi.getThemes).mockResolvedValue({ themes: THEMES, role: 'owner' } as Awaited<ReturnType<typeof themesApi.getThemes>>)
  vi.mocked(themesApi.getThemesChart).mockResolvedValue({ chart_html: '<div>TREEMAP</div>', chart_width: 100, chart_height: 100 } as Awaited<ReturnType<typeof themesApi.getThemesChart>>)
  vi.mocked(jobsApi.getLatestJob).mockResolvedValue(null)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

async function renderPage() {
  await act(async () => {
    root.render(<MemoryRouter initialEntries={['/report?dataset=1']}><Themes /></MemoryRouter>)
  })
  // Let the chained page-load awaits settle.
  for (let i = 0; i < 5; i++) await act(async () => { await Promise.resolve() })
}

describe('Themes page while the report loads (BUG-047)', () => {
  it('shows one loading line, not the theme-editing view or "Build report"', async () => {
    vi.mocked(reportApi.getReport).mockReturnValue(new Promise(() => {})) // still loading
    await renderPage()
    const text = container.textContent ?? ''
    expect(text).toContain('Loading the report...')
    expect(text).not.toContain('Build report')
    expect(container.querySelector('[aria-label="Theme editor"]')).toBeNull()
    expect(text).not.toContain('Ready to find themes')
    expect(container.querySelectorAll('input[type="checkbox"]')).toHaveLength(0)
  })

  it('shows the editing view and "Build report" once the report turns out not to exist', async () => {
    vi.mocked(reportApi.getReport).mockRejectedValue(new Error('No report built yet.'))
    await renderPage()
    const text = container.textContent ?? ''
    expect(text).not.toContain('Loading the report...')
    expect(text).toContain('Build report')
    expect(container.querySelector('[aria-label="Theme editor"]')).not.toBeNull()
    expect(text).toContain('Nothing selected')
  })
})
