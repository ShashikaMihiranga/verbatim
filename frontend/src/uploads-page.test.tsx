// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DatasetView } from './api'
import type { ProjectSummary } from './projectsApi'
import { uploadedAgo } from './uploadFormat'

class UploadCancelled extends Error {}
const uploadFile = vi.fn()
const getProjects = vi.fn<() => Promise<ProjectSummary[]>>()
vi.mock('./api', () => ({
  UploadCancelled,
  getUploadLimits: () => Promise.resolve({ max_mb: 50, extensions: ['.csv', '.xls', '.xlsx'] }),
  uploadFile: (...a: unknown[]) => uploadFile(...a),
}))
vi.mock('./projectsApi', async (orig) => ({ ...(await orig<typeof import('./projectsApi')>()), getProjects: () => getProjects() }))
const { default: Upload } = await import('./Upload')

const DS: DatasetView = {
  id: 9, filename: 'Comment survey.xlsx', row_count: 4820, confirmed: false, reused: false, uploaded_at: '2026-10-12T03:00:00+00:00',
  profile: { columns: [{}, {}, {}, {}, {}, {}] } as unknown as DatasetView['profile'],
}
const project = (over: Partial<ProjectSummary>): ProjectSummary =>
  ({ id: 1, filename: 'Staff pulse.csv', question: null, row_count: 100, created_at: new Date().toISOString(), status: 'uploaded', ...over })

let container: HTMLDivElement
let root: Root
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  uploadFile.mockReset()
  getProjects.mockResolvedValue([project({ id: 3, filename: 'Exit interviews.xlsx', status: 'report ready' }), project({ id: 4, status: 'columns confirmed' })])
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
  await act(async () => {
    root.render(<MemoryRouter initialEntries={['/upload']}><Routes>
      <Route path="/upload" element={<Upload />} />
      <Route path="/check-columns" element={<p>Check columns page</p>} />
    </Routes></MemoryRouter>)
  })
}
const text = () => container.textContent ?? ''
const btn = (t: string) => Array.from(container.querySelectorAll('button')).find((b) => b.textContent?.trim() === t)!
async function choose(file: File) {
  const input = container.querySelector<HTMLInputElement>('input[type=file]')!
  Object.defineProperty(input, 'files', { value: [file], configurable: true })
  await act(async () => { input.dispatchEvent(new Event('change', { bubbles: true })) })
}
const csv = (name = 'Comment survey.csv', size = 4) => new File(['x'.repeat(size)], name)

describe('Uploads page', () => {
  it('empty: drop box with the real limit, the four steps, trust cards and earlier uploads', async () => {
    await render()
    expect(text()).toContain('Drop your spreadsheet here')
    expect(text()).toContain('.xlsx, .xls or .csv, up to 50 MB. Built for large files.')
    expect(container.querySelector('.steps')?.getAttribute('aria-label')).toBe('Step 1 of 4: Upload')
    expect(text()).toContain('Masked first')
    const rows = Array.from(container.querySelectorAll('.up-row')).map((r) => [r.getAttribute('href'), r.textContent])
    expect(rows[0][0]).toBe('/report?dataset=3')
    expect(rows[0][1]).toContain('Report ready')
    expect(rows[1][1]).toContain('Cleaning review')
  })

  it('first visit: says there are no uploads yet', async () => {
    getProjects.mockResolvedValue([])
    await render()
    expect(text()).toContain('No uploads yet')
  })

  it('wrong type and too large are caught before anything is sent, with the real extension and limit', async () => {
    await render()
    await choose(new File(['x'], 'notes.pdf'))
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('That file type is not supported.')
    expect(text()).toContain('This one is a .pdf.')
    const big = csv()
    Object.defineProperty(big, 'size', { value: 51 * 1024 * 1024 })
    await choose(big)
    expect(text()).toContain('This file is larger than 50 MB.')
    expect(uploadFile).not.toHaveBeenCalled()
  })

  it('uploads with progress, reads the columns, then shows the file is ready', async () => {
    let finish: (d: DatasetView) => void = () => {}
    let progress: (pct: number, loaded: number, total: number) => void = () => {}
    uploadFile.mockImplementation((_f: File, onProgress: typeof progress) => { progress = onProgress; return new Promise((r) => { finish = r }) })
    await render()
    await choose(csv())
    await act(async () => progress(40, 1_800_000, 4_200_000))
    expect(container.querySelector('[role="progressbar"]')?.getAttribute('aria-valuenow')).toBe('40')
    expect(text()).toContain('40%')
    await act(async () => progress(100, 4_200_000, 4_200_000))
    expect(text()).toContain('Reading the columns')
    expect(text()).toContain('Saved')
    await act(async () => finish(DS))
    expect(text()).toContain('Your file is ready')
    expect(text()).toContain('6 columns')
    expect(text()).toContain('4,820 rows')
    await act(async () => btn('Check columns').click())
    expect(text()).toContain('Check columns page')
  })

  it('a file uploaded before offers Open it, or Upload anyway as a second project', async () => {
    uploadFile.mockResolvedValueOnce({ ...DS, reused: true }).mockResolvedValueOnce({ ...DS, id: 10 })
    await render()
    const file = csv()
    await choose(file)
    expect(text()).toContain('You already uploaded this file.')
    expect(text()).toMatch(/Comment survey\.xlsx was uploaded on \d+ October 2026/)
    await act(async () => btn('Upload anyway').click())
    expect(uploadFile.mock.calls[1][0]).toBe(file)
    expect(uploadFile.mock.calls[1][2]).toMatchObject({ duplicate: true })
    expect(text()).toContain('Your file is ready')
  })

  it('Cancel goes back to the empty box with no message; a server error offers Try again', async () => {
    uploadFile.mockImplementationOnce((_f: File, _p: unknown, opts: { signal: AbortSignal }) => new Promise((_r, reject) => {
      opts.signal.addEventListener('abort', () => reject(new UploadCancelled('cancelled')))
    }))
    await render()
    await choose(csv())
    await act(async () => btn('Cancel').click())
    expect(text()).toContain('Drop your spreadsheet here')
    expect(container.querySelector('[role="alert"]')).toBeNull()
    uploadFile.mockRejectedValueOnce(new Error('We could not read that file. Check it opens in Excel and try again.'))
    await choose(csv())
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('We could not read that file.')
    uploadFile.mockResolvedValueOnce(DS)
    await act(async () => btn('Try again').click())
    expect(text()).toContain('Your file is ready')
  })

  it('says how long ago a file was uploaded', () => {
    const now = Date.parse('2026-10-28T12:00:00Z')
    expect(uploadedAgo('2026-10-26T12:00:00Z', now)).toBe('2 days ago')
    expect(uploadedAgo('2026-10-28T11:59:40Z', now)).toBe('just now')
    expect(uploadedAgo('2026-10-07T12:00:00Z', now)).toBe('3 weeks ago')
  })
})
