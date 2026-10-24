// What the server's context fragment carries in its `data-context` attribute (app/charts.py
// context_report). The fragment itself stays the plain-text fallback and is what exports draw.
export interface ContextData {
  kind: string
  options: string[]
  guessed_kind: string
  corrected: boolean
  framing: string
  length: string
  answered_note: string
  columns_note: string
}

const ENTITIES: Record<string, string> = { '&quot;': '"', '&#x27;': "'", '&#39;': "'", '&lt;': '<', '&gt;': '>', '&amp;': '&' }

// No DOM in the test runner, so read the one attribute directly. The value was written by html.escape,
// so these entities are the only ones that can appear; &amp; is decoded last.
export function parseContextData(html: string): ContextData | null {
  const m = /data-context="([^"]*)"/.exec(html)
  if (!m) return null
  const raw = m[1].replace(/&(quot|#x27|#39|lt|gt);/g, (e) => ENTITIES[e]).replace(/&amp;/g, '&')
  try {
    const d = JSON.parse(raw)
    return typeof d.kind === 'string' && Array.isArray(d.options) ? d : null
  } catch {
    return null
  }
}
