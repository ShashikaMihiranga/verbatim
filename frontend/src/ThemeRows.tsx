import { ArrowUpRight, Check, ChevronDown, ICON, Pencil, Split } from './icons'
import { formatTone, fmt, isOther, NAME_BOLD_SHARE, shareBarWidth, type ColorToken } from './themeEditorModel'
import type { ThemeCard } from './themesApi'

// One row per theme (theme editor hand-off, "Row"): select box, colour dot and name, share bar with the
// printed %, answer count, tone, and three icon actions. Viewers get the same row with no controls but
// the sub-theme toggle, which only shows more.
export default function ThemeRow({
  theme, color, canEdit, selected, expanded, edited, busy = false, onToggleSelect, onToggleExpand, onRename, onSplit,
  onPromote,
}: {
  theme: ThemeCard
  color: ColorToken
  canEdit: boolean
  selected: boolean
  expanded: boolean
  edited: boolean
  onToggleSelect: () => void
  onToggleExpand: () => void
  onRename: () => void
  onSplit: () => void
  onPromote: (index: number, label: string) => void // "Make its own theme" for a sub-theme
  busy?: boolean
}) {
  const other = isOther(theme)
  const name = theme.label
  const subs = theme.sub_themes.length
  return (
    <li className={`te-row${other ? ' is-other' : ''}${selected ? ' is-selected' : ''}`}>
      <div className="te-grid">
        <span className="te-cell">
          {canEdit && (
            other ? (
              <span className="te-check is-locked" title="Other holds answers that fit no theme. It cannot be merged." aria-hidden="true" />
            ) : (
              <button
                type="button" className={`te-check${selected ? ' is-on' : ''}`} aria-pressed={selected}
                aria-label={`${selected ? 'Deselect' : 'Select'} ${name}`} onClick={onToggleSelect}
              >
                {selected && <Check size={16} {...ICON} />}
              </button>
            )
          )}
        </span>
        <span className="te-name">
          <span className="te-dot" style={{ background: `var(--${color})` }} aria-hidden="true" />
          <span className={theme.size_pct >= NAME_BOLD_SHARE ? 'te-label is-big' : 'te-label'}>{name}</span>
          {edited && <span className="te-edited">edited</span>}
        </span>
        <span className="te-share">
          <span className="te-bar" aria-hidden="true"><span style={{ width: `${shareBarWidth(theme.size_pct)}%` }} /></span>
          <span className="te-num">{theme.size_pct.toFixed(1)}%</span>
        </span>
        <span className="te-num te-answers">{fmt(theme.size)}</span>
        <span className="te-num te-tone" title="Average tone, -1 to +1">{formatTone(theme.sentiment)}</span>
        <span className="te-actions">
          {canEdit && (
            <>
              <button type="button" className="te-icon" disabled={other} onClick={onRename}
                aria-label={`Rename ${name}`} title={`Rename ${name}`}>
                <Pencil size={18} {...ICON} />
              </button>
              <button type="button" className="te-icon" disabled={other} onClick={onSplit}
                aria-label={`Split ${name}`} title={other ? 'Other cannot be split. Use Look inside Other.' : `Split ${name}`}>
                <Split size={18} {...ICON} />
              </button>
            </>
          )}
          <button
            type="button" className={`te-icon te-subs${subs === 0 ? ' is-empty' : ''}`} disabled={subs === 0}
            aria-expanded={expanded} onClick={onToggleExpand}
            aria-label={`${expanded ? 'Hide' : 'Show'} ${subs} sub-theme${subs === 1 ? '' : 's'} of ${name}`}
            title={`${expanded ? 'Hide' : 'Show'} ${subs} sub-theme${subs === 1 ? '' : 's'} of ${name}`}
          >
            <ChevronDown size={16} {...ICON} className={expanded ? 'is-flipped' : undefined} />
            <span className="te-num">{subs}</span>
          </button>
        </span>
      </div>
      {expanded && subs > 0 && (
        <ul className="te-subs-list" aria-label={`Sub-themes of ${name}`}>
          {theme.sub_themes.map((s) => (
            <li key={s.index}>
              <span>{s.label}</span>
              <span className="te-num">{s.size_pct.toFixed(1)}% of all answers</span>
              {canEdit && (
                <button type="button" className="te-btn is-small" disabled={busy} onClick={() => onPromote(s.index, s.label)}
                  aria-label={`Make ${s.label} its own theme`} title={`Make ${s.label} its own theme`}>
                  <ArrowUpRight size={14} {...ICON} />Own theme
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </li>
  )
}
