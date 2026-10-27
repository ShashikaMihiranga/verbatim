// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import QuotesBlock from './QuotesBlock'
import { parseQuotesData, type QuotesData } from './quotesData'

let host: HTMLDivElement
let root: Root
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  host = document.createElement('div')
  document.body.append(host)
  root = createRoot(host)
})
afterEach(() => { act(() => root.unmount()); host.remove(); vi.unstubAllGlobals() })

const data: QuotesData = {
  themes: [{ name: 'Parking', color: 't1' }, { name: 'Noise', color: 't2' }],
  quotes: [
    { text: 'Parking is fine most days', theme: 'Parking', tone: 'neutral', score: 0, ranks: { typical: 0, random: 1 } },
    { text: 'Parking is awful and unsafe', theme: 'Parking', tone: 'negative', score: -0.6, ranks: { negative: 0, random: 0 } },
    { text: 'Too loud to think', theme: 'Noise', tone: 'negative', score: -0.3, ranks: { typical: 0, negative: 0 } },
    { text: 'Quiet rooms are great', theme: 'Noise', tone: 'positive', score: 0.5, ranks: { positive: 0 } },
  ],
}
const rows = () => Array.from(host.querySelectorAll('.qb-text')).map((e) => e.textContent)
const click = (label: string) => act(() => {
  Array.from(host.querySelectorAll('button')).find((b) => b.textContent === label)!.click()
})

it('reads the payload html.escape wrote', () => {
  const html = `<div data-quotes="${JSON.stringify(data).replace(/&/g, '&amp;').replace(/"/g, '&quot;')}"></div>`
  expect(parseQuotesData(html)).toEqual(data)
  expect(parseQuotesData('<div></div>')).toBeNull()
})

it('the tabs change which answers are shown', () => {
  act(() => root.render(<QuotesBlock data={data} />))
  expect(rows()).toEqual(['Parking is fine most days', 'Too loud to think'])
  click('Most negative')
  expect(rows()).toEqual(['Parking is awful and unsafe', 'Too loud to think'])
  click('Most positive')
  expect(rows()).toEqual(['Quiet rooms are great'])
  click('Random')
  expect(rows()).toEqual(['Parking is awful and unsafe', 'Parking is fine most days'])
  expect(host.querySelector('[aria-pressed="true"]')!.textContent).toBe('Random')
})

it('a theme chip keeps only that theme, and says so when a tab has nothing', () => {
  act(() => root.render(<QuotesBlock data={data} />))
  click('Noise')
  expect(rows()).toEqual(['Too loud to think'])
  click('Most positive')
  expect(rows()).toEqual(['Quiet rooms are great'])
  click('Parking')
  expect(rows()).toEqual([])
  expect(host.textContent).toContain('No clearly positive answers here.')
  click('All')
  expect(rows()).toEqual(['Quiet rooms are great'])
})
