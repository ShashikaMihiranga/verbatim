import { useState } from 'react'
import { AnswerList, ToneBar } from './Themes'
import type { SubThemeCard, ThemeCard } from './themesApi'

// One sub-theme's row inside the parent theme's "Sub-themes" list: label, rounded share, and its own
// "See answers" toggle mounting AnswerList against that sub-theme's own answers route. No color swatch -
// the API exposes no color data for sub-themes (ThemeNode.color is a chart-rendering-only concept, never
// serialized here - see themesApi.ts::SubThemeCard's own comment).
function SubThemeRow({ id, themeId, sub }: { id: number; themeId: number; sub: SubThemeCard }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="th-sub-row">
      <div className="th-sub-top">
        <div className="th-sub-label">{sub.label}</div>
        <span className="th-sub-pct">{Math.round(sub.size_pct)}%</span>
      </div>
      {sub.description && <div className="th-sub-desc">{sub.description}</div>}
      <button type="button" className="th-see" onClick={() => setOpen(!open)}>
        {open ? 'Hide answers' : 'See answers'}
      </button>
      {open && <AnswerList id={id} themeId={themeId} subIndex={sub.index} />}
    </div>
  )
}

// One theme's full detail: label, description, size, tone split, an optional sub-themes list, and a
// "See answers" drill-down. Extracted from Themes.tsx's old `Card` component (removed - it rendered this
// same content once per theme, in a grid) so the same content can render once, for whichever theme is
// currently selected, below the shared treemap chart - on both the Themes screen's browse view and the
// report page's overview block.
export default function ThemeDetail({ id, theme }: { id: number; theme: ThemeCard }) {
  const [open, setOpen] = useState(false)
  const unassignedPct = Math.max(0, 100 - theme.sub_themes.reduce((sum, s) => sum + s.size_pct, 0))
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
      {theme.sub_themes.length > 0 && (
        <div className="th-subs">
          <div className="th-subs-h">Sub-themes</div>
          {theme.sub_themes.map((s) => (
            <SubThemeRow key={s.index} id={id} themeId={theme.id} sub={s} />
          ))}
          {unassignedPct > 0 && (
            <div className="th-subs-note muted">{Math.round(unassignedPct)}% of this theme's answers fit no sub-theme</div>
          )}
        </div>
      )}
      <button type="button" className="th-see" onClick={() => setOpen(!open)}>
        {open ? 'Hide answers' : 'See answers'}
      </button>
      {open && <AnswerList id={id} themeId={theme.id} />}
    </div>
  )
}
