// What the server's quotes fragment carries in its `data-quotes` attribute (app/charts.py f_quotes,
// app/text_pipeline/quotes.py build_quote_pool). The fragment itself stays the static picture exports draw.
export type QuoteView = 'typical' | 'random' | 'negative' | 'positive'

export interface PoolQuote {
  text: string
  theme: string
  tone: 'negative' | 'neutral' | 'positive'
  score: number
  ranks: Partial<Record<QuoteView, number>>
}

export interface QuotesData {
  themes: { name: string; color: string }[]
  quotes: PoolQuote[]
}

export const VIEWS: { key: QuoteView; label: string }[] = [
  { key: 'typical', label: 'Most typical' },
  { key: 'random', label: 'Random' },
  { key: 'negative', label: 'Most negative' },
  { key: 'positive', label: 'Most positive' },
]

// Rows shown: All themes mixes them, one theme shows its own few.
export const ALL_ROWS = 8
export const THEME_ROWS = 4

const ENTITIES: Record<string, string> = { '&quot;': '"', '&#x27;': "'", '&#39;': "'", '&lt;': '<', '&gt;': '>', '&amp;': '&' }

// Same reading as questionContextData.ts: the value was written by html.escape, so these entities are the
// only ones that can appear; &amp; is decoded last.
export function parseQuotesData(html: string): QuotesData | null {
  const m = /data-quotes="([^"]*)"/.exec(html)
  if (!m) return null
  const raw = m[1].replace(/&(quot|#x27|#39|lt|gt);/g, (e) => ENTITIES[e]).replace(/&amp;/g, '&')
  try {
    const d = JSON.parse(raw)
    return Array.isArray(d.themes) && Array.isArray(d.quotes) ? d : null
  } catch {
    return null
  }
}

// Typical and Random take each theme's first pick in turn (largest theme first), so All shows the spread;
// Most negative and Most positive sort by the answer's own score.
export function pickQuotes(data: QuotesData, view: QuoteView, theme: string | null): PoolQuote[] {
  const order = new Map(data.themes.map((t, i) => [t.name, i]))
  const inView = data.quotes.filter((q) => q.ranks[view] !== undefined && (theme === null || q.theme === theme))
  const sorted = view === 'negative' ? inView.sort((a, b) => a.score - b.score)
    : view === 'positive' ? inView.sort((a, b) => b.score - a.score)
      : inView.sort((a, b) => (a.ranks[view]! - b.ranks[view]!) || ((order.get(a.theme) ?? 0) - (order.get(b.theme) ?? 0)))
  return sorted.slice(0, theme === null ? ALL_ROWS : THEME_ROWS)
}
