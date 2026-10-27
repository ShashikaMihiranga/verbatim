// @vitest-environment jsdom
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Job } from './jobsApi'
import ReportWaiting from './ReportWaiting'
import { formatElapsed, stepIndex } from './reportWaitingModel'

const NOW = Date.parse('2026-10-28T10:00:00Z')
const ago = (ms: number) => new Date(NOW - ms).toISOString()
const job = (over: Partial<Job> = {}): Job => ({
  id: 1, dataset_id: 1, column: 'Comment', kind: 'themes', status: 'running', step: 'Naming each group',
  error: null, result: null, created_at: ago(42_000), ...over,
})

let container: HTMLDivElement
let root: Root
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  vi.useFakeTimers({ now: NOW, toFake: ['Date', 'setInterval', 'clearInterval', 'setTimeout', 'clearTimeout'] })
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
})
afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

async function render(j: Job, extra: { resumed?: boolean; onRetry?: () => void; onSeeThemes?: () => void } = {}) {
  await act(async () => {
    root.render(<MemoryRouter><ReportWaiting job={j} resumed={extra.resumed ?? false} onRetry={extra.onRetry ?? (() => {})}
      onSeeThemes={extra.onSeeThemes} /></MemoryRouter>)
  })
}
const text = () => container.textContent ?? ''
const btn = (t: string) => Array.from(container.querySelectorAll('button, a')).find((b) => b.textContent?.trim() === t) as HTMLElement

describe('ReportWaiting', () => {
  it('shows the real step, the server elapsed time and the step list, announcing only the step', async () => {
    await render(job())
    expect(text()).toContain('Step 2 of 5')
    expect(container.querySelector('h2')?.textContent).toBe('Naming each group')
    expect(text()).toContain('0:42 elapsed')
    expect(container.querySelector('[role="status"]')?.textContent).toBe('Step 2 of 5: Naming each group')
    const bar = container.querySelector('[role="progressbar"]')!
    expect([bar.getAttribute('aria-valuenow'), bar.getAttribute('aria-valuetext')]).toEqual(['1', 'Naming each group'])
    expect(Array.from(container.querySelectorAll('.rw-row')).map((r) => r.className.replace('rw-row is-', '')))
      .toEqual(['done', 'running', 'todo', 'todo', 'todo'])
    await act(async () => { vi.advanceTimersByTime(3000) })
    expect(text()).toContain('0:45 elapsed')
  })

  it('fills step 1 from real counts', async () => {
    await render(job({ step: 'Turning answers into vectors', progress: { step: 'Turning answers into vectors', done: 300, total: 1200 } as unknown as Job['progress'] }))
    expect(container.querySelector<HTMLElement>('.rw-seg i')!.style.width).toBe('25%')
    expect(container.querySelector('.rw-row.is-running')?.textContent).toContain('25%')
  })

  it('after two minutes says it is taking longer; after five offers to leave, and Keep waiting hides that', async () => {
    await render(job({ created_at: ago(150_000) }))
    expect(text()).toContain('Taking a little longer than usual.')
    await render(job({ created_at: ago(310_000) }))
    expect(text()).toContain('This is taking much longer than expected.')
    await act(async () => btn('Leave and come back later').click())
    expect(text()).toContain('We will keep working on it')
    expect(btn('Go to my files').getAttribute('href')).toBe('/projects')
    await act(async () => btn('Stay on this page').click())
    await act(async () => btn('Keep waiting').click())
    expect(text()).not.toContain('This is taking much longer')
    expect(text()).toContain('Taking a little longer than usual.')
  })

  it('welcomes someone back to a build that is still running', async () => {
    await render(job({ step: 'Naming sub-themes', created_at: ago(12 * 60_000 + 4000) }), { resumed: true })
    expect(text()).toContain('12:04 elapsed')
    expect(text()).toContain('Step 4 of 5')
    // past five minutes the leave offer wins; once dismissed, the welcome note shows
    await act(async () => btn('Keep waiting').click())
    expect(text()).toContain('Welcome back. Your themes are still being found. It started 12 minutes ago.')
  })

  it('failed: red cross on the step it stopped at, the reason, and Try again', async () => {
    const onRetry = vi.fn()
    await render(job({ status: 'failed', step: 'Finding sub-themes', error: 'The server restarted while this was running.' }), { onRetry })
    expect(container.querySelector('.rw-row.is-failed')?.textContent).toContain('Finding sub-themes')
    expect(container.querySelectorAll('.rw-seg i')[2].getAttribute('style')).toContain('rgb(192, 97, 74)')
    expect(container.querySelector('[role="alert"]')?.textContent).toContain('We could not finish finding themes. Nothing was lost.')
    expect(text()).toContain('The server restarted while this was running.')
    await act(async () => btn('Try again').click())
    expect(onRetry).toHaveBeenCalled()
  })

  it('done while away: every step ticked and the ready overlay', async () => {
    const onSeeThemes = vi.fn()
    await render(job({ status: 'done', step: 'Done', updated_at: ago(0) }), { resumed: true, onSeeThemes })
    expect(container.querySelectorAll('.rw-row.is-done')).toHaveLength(5)
    expect(text()).toContain('Welcome back. Your themes are ready')
    await act(async () => btn('See your themes').click())
    expect(onSeeThemes).toHaveBeenCalled()
  })

  it('maps steps and formats time', () => {
    expect(stepIndex(job({ step: 'Starting' }))).toBe(0)
    expect(stepIndex(job({ step: 'Scoring tone' }))).toBe(4)
    expect(stepIndex(job({ status: 'done' }))).toBe(5)
    expect(formatElapsed(754_000)).toBe('12:34')
  })
})
