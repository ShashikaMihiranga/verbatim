import { useEffect, useRef, useState } from 'react'

export function useReducedMotion(): boolean {
  const [reduce, setReduce] = useState(
    () => typeof window !== 'undefined' && !!window.matchMedia?.('(prefers-reduced-motion: reduce)').matches,
  )
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-reduced-motion: reduce)')
    if (!mq) return
    const on = () => setReduce(mq.matches)
    mq.addEventListener('change', on)
    return () => mq.removeEventListener('change', on)
  }, [])
  return reduce
}

// True once the element has scrolled into view (and stays true). Without IntersectionObserver it is true at once.
export function useInView<T extends Element>() {
  const ref = useRef<T | null>(null)
  const [seen, setSeen] = useState(false)
  useEffect(() => {
    const el = ref.current
    if (!el || typeof IntersectionObserver === 'undefined') {
      setSeen(true)
      return
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setSeen(true)
          io.disconnect()
        }
      },
      { threshold: 0.25 },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [])
  return { ref, seen }
}

// True a moment after `active` becomes true, so CSS transitions start from the "hidden" state.
// Changing `key` replays it. With reduced motion the finished state shows immediately.
export function useRevealed(active: boolean, key: unknown = 0): boolean {
  const reduce = useReducedMotion()
  const token = String(key)
  const [doneFor, setDoneFor] = useState<string | null>(null)
  useEffect(() => {
    if (reduce || !active) return
    let r2 = 0
    const r1 = requestAnimationFrame(() => {
      r2 = requestAnimationFrame(() => setDoneFor(token))
    })
    return () => {
      cancelAnimationFrame(r1)
      cancelAnimationFrame(r2)
    }
  }, [active, token, reduce])
  return reduce || (active && doneFor === token)
}
