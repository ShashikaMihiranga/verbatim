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

const handlers = () => ({
  onRename: vi.fn(() => Promise.resolve()), onMerge: vi.fn(() => Promise.resolve()), onSplit: vi.fn(() => Promise.resolve()),
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
    act(() => container.querySelector<HTMLButtonElement>('.te-selbar button')!.click())
    expect(container.textContent).toContain('2 themes become one')
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

  it('shows the error from a failed edit and keeps the panel open', async () => {
    const h = handlers()
    h.onSplit.mockRejectedValueOnce(new Error('Too few answers to split.'))
    mount(true, h)
    act(() => button('Split Desks').click())
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
