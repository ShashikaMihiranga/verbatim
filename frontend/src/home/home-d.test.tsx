// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ReportResponse } from '../reportApi'
import sampleJson from '../../public/sample/report.json?raw'

// anime.js needs a real layout engine; the tests check structure, text and behaviour, not motion.
vi.mock('animejs', () => {
  const chain = (): Record<string, unknown> => {
    const t: Record<string, unknown> = {}
    for (const k of ['add', 'call', 'seek', 'pause', 'play', 'revert']) t[k] = () => t
    t.completed = true
    return t
  }
  return {
    animate: () => chain(), createTimeline: () => chain(), stagger: () => 0,
    splitText: () => ({ words: [] }), createScope: () => ({ add: (fn: () => void) => { fn(); return { revert: () => {} } }, revert: () => {} }),
    utils: { set: () => {}, remove: () => {} }, svg: { createDrawable: () => ({}), createMotionPath: () => ({}) },
  }
})

const SAMPLE = JSON.parse(sampleJson) as ReportResponse

import HomePage from './HomePage'
import { MAP_STAGES } from './howItWorksData'
import { SAMPLE_TABS } from './sampleReport'

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  // Reduced motion: no loops or auto-advance, finished states.
  vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduce'), media: q, addEventListener: () => {}, removeEventListener: () => {} }))
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => SAMPLE })))
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

async function mount() {
  await act(async () => { root.render(<MemoryRouter><HomePage /></MemoryRouter>) })
  // the report tabs load the sample once the section is in view, or after the fallback
  await act(async () => { await new Promise((r) => setTimeout(r, 0)) })
}

describe('home page D', () => {
  it('has one h1, the sections in order, and anchors the top bar links to', async () => {
    await mount()
    expect(container.querySelectorAll('h1')).toHaveLength(1)
    expect(container.querySelector('h1')!.textContent).toBe('From a messy sheet to a clear report.')
    const heads = Array.from(container.querySelectorAll('h2')).map((h) => h.textContent)
    expect(heads).toEqual([
      'Five steps. You stay in control.', 'Small blocks. One idea each.', 'Your answers stay yours.',
      'Turn your next survey into a clear report.', 'From your spreadsheet to a report, and what leaves your data on the way.',
    ])
    const nav = Array.from(container.querySelectorAll('.hd-links a')).map((a) => [a.textContent, a.getAttribute('href')])
    expect(nav).toEqual([['How it works', '#how-it-works'], ['What you get', '#what-you-get'], ['Privacy', '#privacy'], ['Sign in', '/sign-in'], ['Get started', '/sign-up']])
    for (const id of ['how-it-works', 'what-you-get', 'privacy']) expect(container.querySelector(`#${id}`)?.classList.contains('hd-anchor')).toBe(true)
  })

  it('sends Get started to sign-up and See a sample report to /sample', async () => {
    await mount()
    const links = Array.from(container.querySelectorAll('a'))
    expect(links.filter((a) => a.textContent?.startsWith('Get started')).every((a) => a.getAttribute('href') === '/sign-up')).toBe(true)
    const samples = links.filter((a) => a.textContent === 'See a sample report')
    expect(samples.length).toBeGreaterThanOrEqual(2)
    expect(samples.every((a) => a.getAttribute('href') === '/sample')).toBe(true)
  })

  it('tells the truth about what Claude and the embeddings service see', async () => {
    await mount()
    const text = container.textContent!
    expect(text).toContain('Claude reads a few sample answers and totals, never your whole file.')
    expect(text).toContain('An embeddings service reads the masked answers to find their meaning.')
    expect(text).not.toContain('Claude reads the topics') // Voyage embeds; Claude only names groups from samples
  })

  it('shows no pause controls and no looping under reduced motion', async () => {
    await mount()
    expect(Array.from(container.querySelectorAll('button')).some((b) => /^(Pause|Play) /.test(b.getAttribute('aria-label') ?? ''))).toBe(false)
  })

  it('has real tabs with arrow keys, each showing its sample chart and sentence', async () => {
    await mount()
    const tabs = Array.from(container.querySelectorAll<HTMLButtonElement>('[role="tab"]'))
    expect(tabs.map((t) => t.textContent)).toEqual(SAMPLE_TABS.map((t) => t.name))
    expect(container.querySelector('[role="tablist"]')).not.toBeNull()
    expect(tabs[0].getAttribute('aria-selected')).toBe('true')
    expect(container.querySelector('.hd-chartbox-in')?.innerHTML).toContain('What are the themes?')
    await act(async () => { tabs[0].dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true })) })
    expect(tabs[1].getAttribute('aria-selected')).toBe('true')
    expect(document.activeElement).toBe(tabs[1])
    expect(container.querySelector('[role="tabpanel"]')!.textContent).toContain(SAMPLE_TABS[1].sentence)
  })

  it('lists the six map steps with the exact "what leaves your data" text for small screens', async () => {
    await mount()
    const items = Array.from(container.querySelectorAll('.hd-maplist li'))
    expect(items).toHaveLength(6)
    expect(items.map((li) => li.querySelector('.hd-ml-leave')!.textContent)).toEqual(MAP_STAGES.map((s) => `What leaves your data: ${s.leaves}`))
  })
})

describe('the map\'s privacy promise', () => {
  it('keeps the hand-off\'s exact text per step', () => {
    expect(MAP_STAGES.map((s) => [s.title, s.leaves])).toEqual([
      ['Upload', 'Optional: headers and up to 30 sample values per column go to Claude. Sensitive columns send the header only.'],
      ['Check columns', 'Nothing.'],
      ['Clean and mask', 'Nothing. Only the masked copy is used for text analysis. Groups under 30 are hidden in sensitive columns.'],
      ['Find themes', "To Voyage: every masked answer in the chosen column. To Claude: about 15 to 25 masked samples per group. Look inside Other: to Voyage, Other's masked samples; to Jev, each masked Other answer plus the list of theme names."],
      ['Build the report', 'To Claude: aggregate numbers only, no answers.'],
      ['Edit, share, export', 'Only if grouping is asked: theme names, counts, shares and 3 masked samples per theme.'],
    ])
  })

  it('never says Claude receives full or every answer', () => {
    for (const s of MAP_STAGES) {
      for (const text of [s.leaves, s.plain, s.tech]) {
        expect(text).not.toMatch(/claude[^.]*\b(every|all|full|whole)\b[^.]*answers?/i)
        expect(text).not.toMatch(/to claude:\s*(every|all)\b/i)
      }
    }
  })

  it('every wire a step uses exists, and no step clears the report on an edit', async () => {
    const { WIRES } = await import('./howItWorksData')
    for (const s of MAP_STAGES) for (const [wire] of s.conns) expect(WIRES[wire]).toBeDefined()
    const edit = MAP_STAGES[5]
    expect(edit.plain).toContain('marks the report out of date')
    expect(edit.plain).not.toMatch(/clears the report/i)
  })
})

describe('the sample report', () => {
  it('has a chart for every tab, and tab sentences carry no figures', () => {
    for (const t of SAMPLE_TABS) {
      const f = t.pick(SAMPLE)
      expect(f, t.name).toBeDefined()
      expect(f!.chart_html.length).toBeGreaterThan(100)
      expect(t.sentence).not.toMatch(/\d/)
    }
  })

  it('is current, anonymous and has no email addresses or links in it', () => {
    expect(SAMPLE.stale).toBeFalsy()
    expect(SAMPLE.dataset_id).toBe(0)
    const raw = JSON.stringify(SAMPLE)
    expect(raw).not.toMatch(/[\w.+-]+@[\w-]+\.[a-z]{2,}/i)
    expect(raw).not.toMatch(/https?:\/\//)
  })
})
