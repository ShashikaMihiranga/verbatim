import { useState } from 'react'
import { pickQuotes, VIEWS, type QuoteView, type QuotesData } from './quotesData'

const EMPTY: Record<QuoteView, string> = {
  typical: 'No answers to show.',
  random: 'No answers to show.',
  negative: 'No clearly negative answers here.',
  positive: 'No clearly positive answers here.',
}

// "What does it sound like?" with working tabs and theme chips. The server's fragment drew them as a
// static picture (spans, no click), so on the report page this replaces it; exports keep the picture.
export default function QuotesBlock({ data }: { data: QuotesData }) {
  const [view, setView] = useState<QuoteView>('typical')
  const [theme, setTheme] = useState<string | null>(null)
  const color = new Map(data.themes.map((t) => [t.name, t.color]))
  const rows = pickQuotes(data, view, theme)

  return (
    <section className="rp-section qb">
      <h2 className="qb-title">What does it sound like?</h2>
      <p className="qb-sub">Verbatim answers, with their theme and tone.</p>

      <div className="qb-tabs" role="group" aria-label="Which answers">
        {VIEWS.map((v) => (
          <button key={v.key} type="button" className="qb-tab" aria-pressed={view === v.key} onClick={() => setView(v.key)}>
            {v.label}
          </button>
        ))}
      </div>

      <div className="qb-chips" role="group" aria-label="Theme">
        <button type="button" className="qb-chip" aria-pressed={theme === null} onClick={() => setTheme(null)}>All</button>
        {data.themes.map((t) => (
          <button key={t.name} type="button" className="qb-chip" aria-pressed={theme === t.name}
            onClick={() => setTheme(theme === t.name ? null : t.name)}>
            <span className="qb-dot" style={{ background: `var(--${t.color})` }} />
            {t.name}
          </button>
        ))}
      </div>

      <div className="qb-rows" aria-live="polite">
        {rows.length === 0 && <p className="qb-empty">{EMPTY[view]}</p>}
        {rows.map((q) => (
          <div className="qb-row" key={`${q.theme}:${q.text}`}>
            <div className="qb-tone"><span className={`qb-tonedot ${q.tone}`} />{q.tone}</div>
            <div className="qb-text">{q.text}</div>
            <div className="qb-theme">
              <span className="qb-dot" style={{ background: `var(--${color.get(q.theme) ?? 'other'})` }} />
              {q.theme}
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
