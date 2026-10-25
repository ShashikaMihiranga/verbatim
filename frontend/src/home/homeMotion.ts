export { useReducedMotion } from './motion'

// Runs `fn` once, when `el` is about 25% visible, or after `fallbackMs` so thumbnails and headless renders
// still show the finished section (the design's reveal pattern). Returns a cleanup.
export function onView(el: Element | null, fn: () => void, fallbackMs = 8000, threshold = 0.25): () => void {
  let done = false
  const run = () => { if (!done) { done = true; fn() } }
  const timer = window.setTimeout(run, fallbackMs)
  let io: IntersectionObserver | null = null
  if (el && typeof IntersectionObserver !== 'undefined') {
    io = new IntersectionObserver((entries) => { if (entries.some((e) => e.isIntersecting)) run() }, { threshold })
    io.observe(el)
  } else {
    run()
  }
  return () => { window.clearTimeout(timer); io?.disconnect() }
}

// Calls `onChange(true|false)` as `el` enters or leaves the screen, so loops pause off screen.
export function watchVisible(el: Element | null, onChange: (visible: boolean) => void, threshold = 0.1): () => void {
  if (!el || typeof IntersectionObserver === 'undefined') return () => {}
  const io = new IntersectionObserver((entries) => entries.forEach((e) => onChange(e.isIntersecting)), { threshold })
  io.observe(el)
  return () => io.disconnect()
}

// How much an element is scaled on screen (by <Fit>): positions measured with getBoundingClientRect are
// divided by this so they land in the element's own, unscaled coordinates.
export function screenScale(el: HTMLElement): number {
  const w = el.offsetWidth
  return w ? el.getBoundingClientRect().width / w || 1 : 1
}
