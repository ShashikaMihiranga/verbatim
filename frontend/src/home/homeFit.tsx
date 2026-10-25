import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'

// Shows a fixed-size design (the hero stage, the map) at full size when there is room, scaled down
// evenly when there is not, so its absolute positions and wires stay exact.
export function Fit({ w, h, className, children }: { w: number; h: number; className?: string; children: ReactNode }) {
  const outer = useRef<HTMLDivElement | null>(null)
  const [k, setK] = useState(1)
  useLayoutEffect(() => {
    const el = outer.current
    if (!el) return
    const measure = () => { const cw = el.clientWidth; setK(cw > 0 ? Math.min(1, cw / w) : 1) }
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [w])
  return (
    <div ref={outer} className={`hd-fit ${className ?? ''}`} style={{ width: w, height: h * k }}>
      <div className="hd-fit-in" style={{ width: w, height: h, transform: k === 1 ? undefined : `scale(${k})` }}>{children}</div>
    </div>
  )
}

// The visible pause/play control every looping section has (WCAG 2.2.2).
export function PauseButton({ playing, onToggle, label }: { playing: boolean; onToggle: () => void; label: string }) {
  return (
    <button type="button" className="hd-ctl" onClick={onToggle} aria-label={`${playing ? 'Pause' : 'Play'} ${label}`}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        {playing ? <path d="M7 5h3v14H7zM14 5h3v14h-3z" /> : <path d="M8 5l11 7-11 7z" />}
      </svg>
      {playing ? 'Pause' : 'Play'}
    </button>
  )
}
