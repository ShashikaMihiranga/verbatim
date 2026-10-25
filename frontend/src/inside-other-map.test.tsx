// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Job, LookInsideOtherResult } from './jobsApi'

const api = vi.hoisted(() => ({ getAnswerMap: vi.fn() }))
vi.mock('./themesApi', () => api)

import InsideOther from './InsideOther'

let container: HTMLDivElement
let root: Root
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  vi.stubGlobal('ResizeObserver', class { observe() {} disconnect() {} unobserve() {} })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

const done: LookInsideOtherResult = {
  known_added: 52, still_other_count: 300, failed_classification_count: 0, other_before_count: 474, answered_total: 1000,
  new_themes: [{ label: 'Parking access', count: 122, sentiment: -0.3, tone: { neg: 62, neu: 26, pos: 12 } }],
  known_gains: [{ label: 'Cost', count: 52 }],
}
const job: Job = { id: 7, dataset_id: 3, column: 'Why', kind: 'look_inside_other', status: 'done', step: 'Done', error: null, result: done }
const themes = ['Cost', 'Charging'].map((name, i) => ({ name, share: 30 - i, count: 300, sentiment: 0 }))

describe('Inside Other answer map', () => {
  it('maps every theme, not only Other, and highlights a group from the legend', async () => {
    api.getAnswerMap.mockResolvedValue({
      answers: 1000,
      groups: [{ label: 'Cost', other: false }, { label: 'Charging', other: false }, { label: 'Other', other: true }, { label: 'Parking access', other: false }],
      points: [[0.1, 0.1, 0], [0.2, 0.2, 0], [0.8, 0.8, 1], [0.5, 0.5, 2], [0.9, 0.1, 3]],
    })
    await act(async () => { root.render(<InsideOther job={job} allThemes={themes} />) })
    expect(api.getAnswerMap).toHaveBeenCalledWith(3, 'Why')
    expect(container.textContent).toContain('How all answers group')
    expect(container.querySelectorAll('.io-map-svg circle')).toHaveLength(5)
    const keys = Array.from(container.querySelectorAll<HTMLButtonElement>('.io-map-key'))
    expect(keys.map((k) => k.textContent)).toEqual(['newParking access', 'Cost', 'Charging', 'Still in Other'])
    act(() => keys[1].click())
    const groups = Array.from(container.querySelectorAll('.io-map-svg g'))
    const opacity = (label: string) => groups.find((g) => g.querySelector('title')!.textContent!.startsWith(label))!.getAttribute('opacity')
    expect(opacity('Cost')).toBe('0.9')
    expect(opacity('Charging')).toBe('0.08')
    expect(keys[1].getAttribute('aria-pressed')).toBe('true')
  })

  it('shows nothing when the themes have no stored positions', async () => {
    api.getAnswerMap.mockResolvedValue({ answers: 1000, groups: [], points: [] })
    await act(async () => { root.render(<InsideOther job={job} allThemes={themes} />) })
    expect(container.querySelector('.io-map')).toBeNull()
  })
})
