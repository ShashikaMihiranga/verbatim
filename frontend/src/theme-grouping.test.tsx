// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Job } from './jobsApi'
import ThemeGrouping from './ThemeGrouping'
import type { GroupingResult } from './themeEditorApi'

const member = (id: number, label: string, share: number) => ({ id, label, size: share * 10, share, samples: [`${label} answer one`, `${label} answer two`] })
const RESULT: GroupingResult = {
  groups: [
    { id: 'g1', name: 'Cleanliness', member_ids: [1, 2], confidence: 94, band: 'High', similarity: 0.9, reason: 'Both are about cleaning.', share: 9.3,
      members: [member(1, 'Cleaning', 6.1), member(2, 'Janitors', 3.2)] },
    { id: 'g2', name: 'Getting there', member_ids: [3, 4, 5], confidence: 72, band: 'Medium', similarity: null, reason: 'All about arriving.', share: 6,
      members: [member(3, 'Parking', 3), member(4, 'Buses', 2), member(5, 'Bikes', 1)] },
    { id: 'g3', name: 'Air', member_ids: [6, 7], confidence: 51, band: 'Low', similarity: 0.4, reason: 'Maybe.', share: 2, members: [member(6, 'Heat', 1), member(7, 'Air', 1)] },
  ],
  kept_apart: [{ names: ['Noise', 'Privacy'], reason: 'Different fixes.' }], dropped: 0, cached: false, themes: 20, words: 900,
}
const PAYLOAD = { payload: { themes: [{ id: 1, name: 'Cleaning', answers: 61, share: 6.1, samples: ['a', 'b', 'c'] }] }, themes: 20, words: 900 }

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

function props(job: Partial<Job> = { status: 'done', result: RESULT as unknown as Job['result'] }) {
  return {
    themeIds: new Set([1, 2, 3, 4, 5, 6, 7, 8]), totalThemes: 22, undoneToken: null as number | null,
    loadPayload: vi.fn(() => Promise.resolve(PAYLOAD)),
    start: vi.fn(() => Promise.resolve({ job_id: 5 })),
    poll: vi.fn((_id: number, onUpdate: (j: Job) => void) => {
      onUpdate({ id: 5, dataset_id: 1, column: 'Why', kind: 'theme_groups', step: 'Done', error: null, result: null, status: 'done', ...job } as Job)
      return () => {}
    }),
    onApply: vi.fn(() => Promise.resolve(77)),
  }
}
const btn = (text: string) => Array.from(container.querySelectorAll('button')).find((b) => b.textContent?.trim().startsWith(text))!
async function render(p = props()) {
  await act(async () => { root.render(<ThemeGrouping {...p} />) })
  return p
}
async function toReview(p = props()) {
  await render(p)
  await act(async () => btn('Find matches').click())
  return p
}

describe('ThemeGrouping', () => {
  it('idle: shows the steps and, on request, the real payload with its word count', async () => {
    const p = await render()
    expect(container.textContent).toContain('Claude reads the topics')
    expect(btn('What Claude sees').getAttribute('aria-expanded')).toBe('false')
    await act(async () => btn('What Claude sees').click())
    expect(p.loadPayload).toHaveBeenCalled()
    expect(container.textContent).toContain('About 900 words in all')
    expect(container.querySelector('.tg-pre')?.textContent).toContain('"name": "Cleaning"')
    expect(btn('Hide what Claude sees')).toBeTruthy()
  })

  it('review: badges keep word and number, strongest first, with the near-misses', async () => {
    await toReview()
    expect(Array.from(container.querySelectorAll('.tg-badge')).map((b) => b.textContent)).toEqual(['High 94%', 'Medium 72%', 'Low 51%'])
    expect(container.textContent).toContain('3 groups found. 3 still to check.')
    expect(container.textContent).toContain('Left apart on purpose.')
    expect(container.textContent).toContain('Noise and Privacy: Different fixes.')
    expect(container.textContent).toContain('Similarity not checked')
  })

  it('Accept all High, then Apply sends the accepted groups with their (edited) names', async () => {
    const p = await toReview()
    const apply = () => container.querySelector<HTMLButtonElement>('.tg-apply button')!
    expect(apply().disabled).toBe(true)
    expect(container.textContent).toContain('Accept the groups you agree with, then apply them together.')
    await act(async () => btn('Accept all High (1)').click())
    expect(btn('High groups accepted').disabled).toBe(true)
    const name = container.querySelector<HTMLInputElement>('.tg-name')!
    await act(async () => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(name, 'Cleaning and cleanliness')
      name.dispatchEvent(new Event('input', { bubbles: true }))
    })
    expect(container.textContent).toContain('1 group accepted. 2 themes become 1. The list goes from 22 to 21 themes.')
    await act(async () => apply().click())
    expect(p.onApply).toHaveBeenCalledWith([{ name: 'Cleaning and cleanliness', theme_ids: [1, 2] }], 'Merged 2 themes into 1 group.')
    expect(container.textContent).toContain('Done: 2 themes became 1 group, so the list now has 21 themes. One Undo reverses them all.')
  })

  it('undo of the Apply returns to the review with the choices kept', async () => {
    const p = await toReview()
    await act(async () => btn('Accept all High').click())
    await act(async () => container.querySelector<HTMLButtonElement>('.tg-apply button')!.click())
    await act(async () => { root.render(<ThemeGrouping {...p} undoneToken={77} />) })
    expect(container.querySelector('.tg-group.is-accepted')).not.toBeNull()
    expect(container.textContent).toContain('1 group accepted.')
  })

  it('skip toggles, and taking members out drops a group under two', async () => {
    await toReview()
    const skip = container.querySelectorAll<HTMLButtonElement>('.tg-group')[1].querySelector<HTMLButtonElement>('button[title="Not a match"]')!
    await act(async () => skip.click())
    expect(skip.getAttribute('aria-pressed')).toBe('true')
    expect(container.querySelectorAll('.tg-group.is-skipped')).toHaveLength(1)
    await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="Take Heat out of this group"]')!.click())
    expect(container.textContent).not.toContain('Low 51%') // Air had two members; one left is not a group
  })

  it('See answers shows two samples per member', async () => {
    await toReview()
    await act(async () => btn('Answers').click())
    expect(container.querySelectorAll('.tg-answers blockquote')).toHaveLength(4)
  })

  it('a failed run says why and offers to try again', async () => {
    await toReview(props({ status: 'failed', error: 'Could not reach Claude. Try again.' }))
    expect(container.querySelector('[role="alert"]')?.textContent).toBe('Could not reach Claude. Try again.')
    expect(btn('Try again')).toBeTruthy()
  })
})
