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
