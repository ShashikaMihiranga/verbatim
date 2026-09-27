import { useState } from 'react'
import { AnswerList, ToneBar } from './Themes'
import type { ThemeCard } from './themesApi'

// One theme's full detail: label, description, size, tone split and a "See answers" drill-down. Extracted
// from Themes.tsx's old `Card` component (removed - it rendered this same content once per theme, in a
// grid) so the same content can render once, for whichever theme is currently selected, below the shared
// treemap chart - on both the Themes screen's browse view and the report page's overview block.
export default function ThemeDetail({ id, theme }: { id: number; theme: ThemeCard }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="th-detail">
      <div className="th-top">
        <div className="th-label">{theme.label}</div>
        <span className={`th-badge ${theme.confidence}`}>{theme.confidence === 'solid' ? 'Solid' : 'Tentative'}</span>
      </div>
      {theme.description && <div className="th-desc">{theme.description}</div>}
      <div className="th-pct">
        {Math.round(theme.size_pct)}%<span>of answers</span>
      </div>
      <ToneBar tone={theme.tone} />
      <button type="button" className="th-see" onClick={() => setOpen(!open)}>
        {open ? 'Hide answers' : 'See answers'}
      </button>
      {open && <AnswerList id={id} themeId={theme.id} />}
    </div>
  )
}
