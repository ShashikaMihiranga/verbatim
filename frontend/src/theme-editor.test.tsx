// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ThemeEditor from './ThemeEditor'
import type { ThemeCard } from './themesApi'

const t = (id: number, label: string, size: number, subs = 0): ThemeCard => ({
  id, label, description: null, size, size_pct: Math.round((size / 600) * 1000) / 10, sentiment: -0.1,
  tone: { neg: 0, neu: 100, pos: 0 } as ThemeCard['tone'], confidence: 'solid',
  sub_themes: Array.from({ length: subs }, (_, i) => ({
    index: i, label: `Sub ${i}`, description: null, size: 10, size_pct: 1.7, sentiment: 0, tone: { neg: 0, neu: 100, pos: 0 } as ThemeCard['tone'],
  })),
})
const THEMES = [t(1, 'Desks', 40), t(2, 'Other', 300), t(3, 'Noise and privacy', 200, 2), t(4, 'Light', 60)]

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

const MERGE_PREVIEW = {
  answers: 100, share: 16.7, tone: { neg: 0, neu: 100, pos: 0 }, sentiment: -0.12, sub_themes: 0, label: 'Light',
  themes: [{ id: 4, label: 'Light', size: 60, samples: ['The lights flicker all day', 'Too dim by the window'] },
    { id: 1, label: 'Desks', size: 40, samples: ['My desk is too small'] }],
}
const SPLIT_PREVIEW = (parts = 2) => ({
  theme_id: 3, label: 'Noise and privacy', size: 200, share: 33.3, sub_themes: 2, by_wording: false,
  choices: [2, 3], parts_chosen: parts,
  parts: [{ label: 'Noise and privacy', answers: 150, share: 25, keeps_theme: true, sample: 'People talk loudly' },
    { label: 'Sub 0', answers: 50, share: 8.3, keeps_theme: false, sample: 'Phones ring' }].slice(0, parts),
})
const handlers = () => ({
  onRename: vi.fn(() => Promise.resolve()), onMerge: vi.fn(() => Promise.resolve()), onSplit: vi.fn(() => Promise.resolve()),
  onSplitParts: vi.fn(() => Promise.resolve()),
  loadMergePreview: vi.fn(() => Promise.resolve(MERGE_PREVIEW)),
  loadSplitPreview: vi.fn((_id: number, parts?: number) => Promise.resolve(SPLIT_PREVIEW(parts ?? 2))),
})
function mount(canEdit = true, h = handlers()) {
  act(() => { root.render(<ThemeEditor themes={THEMES} totalAnswers={600} canEdit={canEdit} {...h} />) })
  return h
}
const button = (label: string) => container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`)!
const byText = (text: string) => Array.from(container.querySelectorAll('button')).find((b) => b.textContent?.includes(text))!
function type(input: HTMLInputElement, value: string) {
  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, value)
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

describe('ThemeEditor', () => {
  it('lists themes largest first, Other last, with share, answers and tone printed', () => {
    mount()
    const names = Array.from(container.querySelectorAll('.te-label')).map((n) => n.textContent)
    expect(names).toEqual(['Noise and privacy', 'Light', 'Desks', 'Other'])
    expect(container.textContent).toContain('33.3%')
    expect(container.textContent).toContain('-0.10')
    expect(container.textContent).toContain('4 of 4 themes')
  })

  it('selection bar: disabled until two themes are ticked, then says what they become', () => {
    mount()
    const merge = () => container.querySelector<HTMLButtonElement>('.te-selbar button')!
    expect(container.textContent).toContain('Nothing selected')
    expect(merge().disabled).toBe(true)
    act(() => button('Select Desks').click())
    expect(container.textContent).toContain('1 selected')
    expect(merge().disabled).toBe(true)
    act(() => button('Select Light').click())
    expect(container.textContent).toContain('100 answers, 16.7% of all, would become one theme.')
    expect(merge().disabled).toBe(false)
    expect(merge().textContent).toContain('Merge 2 themes…')
    expect(button('Deselect Light').getAttribute('aria-pressed')).toBe('true')
  })

  it('Other cannot be ticked, split or renamed', () => {
    mount()
    expect(container.querySelector('button[aria-label="Select Other"]')).toBeNull()
    expect(button('Split Other').disabled).toBe(true)
    expect(button('Rename Other').disabled).toBe(true)
  })

  it('icon buttons name their theme in the label and the title', () => {
    mount()
    expect(button('Rename Desks').title).toBe('Rename Desks')
    expect(button('Split Desks').title).toBe('Split Desks')
    const subs = button('Show 2 sub-themes of Noise and privacy')
    expect(subs.getAttribute('aria-expanded')).toBe('false')
    act(() => subs.click())
    expect(button('Hide 2 sub-themes of Noise and privacy').getAttribute('aria-expanded')).toBe('true')
    expect(container.textContent).toContain('Sub 0')
    expect(container.textContent).toContain('1.7% of all answers')
  })

  it('merge preview defaults the name to the largest theme and sends the ids', async () => {
    const h = mount()
    act(() => button('Select Desks').click())
    act(() => button('Select Light').click())
    await act(async () => container.querySelector<HTMLButtonElement>('.te-selbar button')!.click())
    expect(container.textContent).toContain('2 themes become one')
    expect(h.loadMergePreview).toHaveBeenCalledWith([1, 4])
    expect(container.textContent).toContain('What people said in each')
    expect(container.querySelectorAll('.te-samples blockquote')).toHaveLength(3)
    expect(container.textContent).toContain('-0.12') // the server's weighted tone
    const name = container.querySelector<HTMLInputElement>('.te-field input')!
    expect(name.value).toBe('Light')
    await act(async () => byText('Merge themes').click())
    expect(h.onMerge).toHaveBeenCalledWith([1, 4], 'Light')
    expect(container.querySelector('.te-toast')?.textContent).toContain('Merged 2 themes into “Light”.')
  })

  it('rename saves the new name and ignores an empty one', async () => {
    const h = mount()
    act(() => button('Rename Desks').click())
    const input = container.querySelector<HTMLInputElement>('.te-field input')!
    act(() => type(input, '  '))
    expect(byText('Save name').disabled).toBe(true)
    act(() => type(input, 'Desk space'))
    await act(async () => byText('Save name').click())
    expect(h.onRename).toHaveBeenCalledWith(1, 'Desk space')
    expect(container.textContent).toContain('Renamed “Desks” to “Desk space”.')
  })

  it('split preview: parts from sub-themes, a part count to choose, and the split it shows', async () => {
    const h = mount()
    await act(async () => button('Split Noise and privacy').click())
    expect(container.textContent).toContain('(keeps the theme)')
    expect(container.querySelectorAll('.te-parts li')).toHaveLength(2)
    const three = container.querySelector<HTMLButtonElement>('.te-seg button:nth-of-type(2)')!
    expect(three.textContent).toBe('3')
    await act(async () => three.click())
    expect(h.loadSplitPreview).toHaveBeenLastCalledWith(3, 3)
    await act(async () => byText('Split theme').click())
    expect(h.onSplitParts).toHaveBeenCalledWith(3, 3)
    expect(h.onSplit).not.toHaveBeenCalled()
    expect(container.textContent).toContain('Split “Noise and privacy” into 3 themes.')
  })

  it('split with no sub-themes runs the by-wording job', async () => {
    const h = handlers()
    h.loadSplitPreview.mockResolvedValueOnce({ ...SPLIT_PREVIEW(), by_wording: true, choices: [], parts: [] })
    mount(true, h)
    await act(async () => button('Split Desks').click())
    expect(container.textContent).toContain('grouped by wording in the background')
    await act(async () => byText('Split theme').click())
    expect(h.onSplit).toHaveBeenCalledWith(1)
  })

  it('shows the error from a failed edit and keeps the panel open', async () => {
    const h = handlers()
    h.onSplitParts.mockRejectedValueOnce(new Error('Too few answers to split.'))
    mount(true, h)
    await act(async () => button('Split Noise and privacy').click())
    await act(async () => byText('Split theme').click())
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Too few answers to split.')
    expect(byText('Split theme')).toBeTruthy()
  })

  it('filter: live by name, with an empty state that clears it', () => {
    mount()
    const filter = container.querySelector<HTMLInputElement>('input[type="search"]')!
    act(() => type(filter, 'zzz'))
    expect(container.textContent).toContain('No themes match.')
    act(() => byText('Clear the filter').click())
    expect(container.textContent).toContain('4 of 4 themes')
  })

  it('viewers see the list with no edit controls', () => {
    mount(false)
    expect(container.querySelector('button[aria-label^="Select"]')).toBeNull()
    expect(container.querySelector('button[aria-label^="Rename"]')).toBeNull()
    expect(container.querySelector('.te-selbar')).toBeNull()
    expect(container.querySelector('.te-side')).toBeNull()
    expect(container.querySelector('button[aria-label^="Show 2 sub-themes"]')).not.toBeNull()
  })
})
