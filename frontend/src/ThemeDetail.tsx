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
//
// `onRename` (docs/TODO.md, fixed 2026-10-22): optional - only `Themes.tsx`'s own "Manage themes" mode
// passes it, so the rename affordance never shows up on the live report page's overview block (editing a
// theme belongs to Manage themes, not to the read-only report view that reuses this same component).
export default function ThemeDetail({
  id, theme, onRename,
}: {
  id: number
  theme: ThemeCard
  onRename?: (label: string, description: string | null) => void
}) {
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState(false)
  const [editLabel, setEditLabel] = useState('')
  const [editDesc, setEditDesc] = useState('')

  function startEditing() {
    setEditLabel(theme.label)
    setEditDesc(theme.description ?? '')
    setEditing(true)
  }

  function saveEdit() {
    const label = editLabel.trim()
    if (label && onRename) onRename(label, editDesc.trim() || null)
    setEditing(false)
  }
  // theme.size_pct and each sub-theme's size_pct are both "% of ALL answered" (the whole dataset), not
  // "% of this theme" - see app/chart_data.py's SubTheme.share docstring and app/api_themes.py's
  // _theme_dict, which compute both against the identical `total`. The remainder is therefore this
  // theme's own share minus its sub-themes' shares, not 100 minus them.
  const unassignedPct = Math.max(0, theme.size_pct - theme.sub_themes.reduce((sum, s) => sum + s.size_pct, 0))
  return (
    <div className="th-detail">
      {editing ? (
        <div className="th-edit">
          <input
            type="text"
            className="chip"
            aria-label="Theme label"
            value={editLabel}
            onChange={(e) => setEditLabel(e.target.value)}
            autoFocus
          />
          <textarea
            className="th-edit-desc"
            aria-label="Theme description"
            value={editDesc}
            onChange={(e) => setEditDesc(e.target.value)}
            placeholder="Description (optional)"
          />
          <div className="th-edit-actions">
            <button type="button" className="btn" onClick={saveEdit}>Save</button>
            <button type="button" className="btn quiet" onClick={() => setEditing(false)}>Cancel</button>
          </div>
        </div>
      ) : (
        <div className="th-top">
          <div className="th-label">{theme.label}</div>
          <span className={`th-badge ${theme.confidence}`}>{theme.confidence === 'solid' ? 'Solid' : 'Tentative'}</span>
          {onRename && (
            <button type="button" className="name-edit-btn" aria-label={`Rename ${theme.label}`} onClick={startEditing}>
              ✎
            </button>
          )}
        </div>
      )}
      {!editing && theme.description && <div className="th-desc">{theme.description}</div>}
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
