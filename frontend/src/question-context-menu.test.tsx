// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ContextData } from './questionContextData'
import type { ReportBlock } from './reportApi'

const api = vi.hoisted(() => ({
  getQuestionKind: vi.fn(),
  saveQuestionKind: vi.fn(),
}))
vi.mock('./reportApi', () => api)

import QuestionContext from './QuestionContext'

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  api.getQuestionKind.mockResolvedValue({ column: 'Why', kind: 'reasons', guessed_kind: 'reasons', corrected: false, options: [], themes_kind: 'reasons' })
  api.saveQuestionKind.mockResolvedValue({ column: 'Why', kind: 'facts', guessed_kind: 'reasons', corrected: true, options: [], themes_kind: 'reasons' })
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

const data: ContextData = {
  kind: 'reasons', options: ['reasons', 'improvements', 'facts'], guessed_kind: 'reasons', corrected: false,
  framing: 'neutrally', length: 'a sentence or two', answered_note: '9 of 10 answered.', columns_note: '',
}
const block = { kind: 'context', chart_id: 'context', chart_title: 'Question context', chart_html: '' } as ReportBlock

async function mount(onKindChange = vi.fn()) {
  await act(async () => {
    root.render(<QuestionContext datasetId={1} column="Why" block={block} data={data} onKindChange={onKindChange} />)
  })
  return onKindChange
}

const trigger = () => container.querySelector<HTMLButtonElement>('button[aria-haspopup="listbox"]')!

describe('question type menu', () => {
  it('opens a styled list, marks the current type, and closes on Escape', async () => {
    await mount()
    expect(container.querySelector('[role="listbox"]')).toBeNull()
    act(() => trigger().click())
    const options = Array.from(container.querySelectorAll('[role="option"]'))
    expect(options.map((o) => o.textContent)).toEqual(['✓reasons', 'improvements', 'facts'])
    expect(options[0].getAttribute('aria-selected')).toBe('true')
    const list = container.querySelector('[role="listbox"]')!
    act(() => list.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))
    expect(container.querySelector('[role="listbox"]')).toBeNull()
    expect(api.saveQuestionKind).not.toHaveBeenCalled()
  })

  it('saves a new type, tells the page, and says the themes need a rebuild', async () => {
    const onKindChange = await mount()
    act(() => trigger().click())
    const facts = Array.from(container.querySelectorAll<HTMLElement>('[role="option"]')).find((o) => o.textContent === 'facts')!
    await act(async () => facts.click())
    expect(api.saveQuestionKind).toHaveBeenCalledWith(1, 'Why', 'facts')
    expect(onKindChange).toHaveBeenCalledTimes(1)
    expect(trigger().textContent).toContain('facts')
    expect(container.textContent).toContain('The themes were named as reasons. Rebuild themes in Manage themes to name them as facts.')
  })

  it('picks with the keyboard', async () => {
    await mount()
    act(() => trigger().dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowDown', bubbles: true })))
    const list = container.querySelector('[role="listbox"]')!
    for (const key of ['ArrowDown', 'ArrowDown']) {
      act(() => list.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true })))
    }
    await act(async () => list.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true })))
    expect(api.saveQuestionKind).toHaveBeenCalledWith(1, 'Why', 'facts')
  })

  it('choosing the current type saves nothing', async () => {
    await mount()
    act(() => trigger().click())
    const reasons = container.querySelector<HTMLElement>('[role="option"]')!
    act(() => reasons.click())
    expect(api.saveQuestionKind).not.toHaveBeenCalled()
  })
})
