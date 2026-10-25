import { useEffect, useMemo, useRef, useState } from 'react'
import './theme-editor.css'
import { ChevronDown, ICON, List, Merge, Pencil, Search, Split, Undo2 } from './icons'
import JobProgress from './JobProgress'
import type { Job } from './jobsApi'
import ThemeRow from './ThemeRows'
import {
  colorTokens, combine, fmt, formatTone, isOther, largestName, selectionText, SMALL_SHARE, visibleThemes, type Chip,
} from './themeEditorModel'
import type { ThemeCard } from './themesApi'

// The theme editor (design/handoffs/ThemeEditor_UIHandoff.md): one list that merges, splits and renames,
// replacing the old "Merge themes" checklist. Left: toolbar, icon key, the list and the sticky selection
// bar. Right: one panel at a time and the toast. Edits call the existing endpoints through the callbacks.
type Panel = { kind: 'idle' } | { kind: 'merge' } | { kind: 'split'; id: number } | { kind: 'rename'; id: number }

export default function ThemeEditor({
  themes, totalAnswers, canEdit, edited = new Set<number>(), splitJob = null, onRename, onMerge, onSplit,
}: {
  themes: ThemeCard[]
  totalAnswers: number
  canEdit: boolean // owners and editors; viewers get the list with no edit controls
  edited?: Set<number>
  splitJob?: Job | null
  onRename: (themeId: number, label: string) => Promise<void>
  onMerge: (themeIds: number[], label: string) => Promise<void>
  onSplit: (themeId: number) => Promise<void>
}) {
  const [query, setQuery] = useState('')
  const [chip, setChip] = useState<Chip>('all')
  const [selection, setSelection] = useState<Set<number>>(new Set())
  const [expanded, setExpanded] = useState<Set<number>>(new Set())
  const [panel, setPanel] = useState<Panel>({ kind: 'idle' })
  const [toast, setToast] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const side = useRef<HTMLElement>(null)
  // In the one-column layout the panel sits above the list: bring it into view when it opens.
  useEffect(() => {
    if (panel.kind === 'idle' || !side.current || getComputedStyle(side.current).position === 'sticky') return
    const smooth = !window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    side.current.scrollIntoView?.({ block: 'start', behavior: smooth ? 'smooth' : 'auto' })
  }, [panel])

  const colors = useMemo(() => colorTokens(themes), [themes])
  const shown = visibleThemes(themes, query, chip, edited)
  // A theme that was merged away or rebuilt drops out of the selection on its own.
  const selected = themes.filter((t) => selection.has(t.id))
  const bar = selectionText(selected, totalAnswers)
  const byId = (id: number) => themes.find((t) => t.id === id)

  async function run(action: () => Promise<void>, done: string) {
    setBusy(true)
    setError(null)
    try {
      await action()
      setToast(done)
      setPanel({ kind: 'idle' })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That edit did not go through.')
    } finally {
      setBusy(false)
    }
  }

  const toggle = (set: Set<number>, id: number) => {
    const next = new Set(set)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  }

  return (
    <div className="te-wrap">
    <section className="te" aria-label="Theme editor">
      <div className="te-main">
        <div className="te-toolbar">
          <label className="te-filter">
            <Search size={16} {...ICON} />
            <input type="search" placeholder="Filter themes" aria-label="Filter themes" value={query}
              onChange={(e) => setQuery(e.target.value)} />
          </label>
          <div className="te-chips" role="group" aria-label="Show">
            {([['all', 'All themes'], ['small', `Small (under ${SMALL_SHARE}%)`], ['edited', 'Edited']] as const).map(([key, label]) => (
              <button key={key} type="button" className="te-chip" aria-pressed={chip === key} onClick={() => setChip(key)}>
                {key === 'all' && <List size={14} {...ICON} />}
                {key === 'edited' && <Pencil size={14} {...ICON} />}
                {label}
              </button>
            ))}
          </div>
          <span className="te-count">{shown.length} of {themes.length} themes</span>
        </div>

        {canEdit && (
          <>
            <p className="te-intro">Tick themes to merge them, or use a row's buttons. Edits apply right away.</p>
            <ul className="te-key" aria-label="Icon key">
              <li><Merge size={16} {...ICON} />Merge</li>
              <li><Split size={16} {...ICON} />Split</li>
              <li><Pencil size={16} {...ICON} />Rename</li>
              <li><ChevronDown size={16} {...ICON} />Sub-themes</li>
              <li><Undo2 size={16} {...ICON} />Undo</li>
            </ul>
          </>
        )}

        <div className="te-head" aria-hidden="true">
          <span /><span>Theme</span><span>Share of answers</span><span>Answers</span><span>Tone</span><span />
        </div>
        <ul className="te-list">
          {shown.map((t) => (
            <ThemeRow
              key={t.id} theme={t} color={colors.get(t.id) ?? 'other'} canEdit={canEdit}
              selected={selection.has(t.id)} expanded={expanded.has(t.id)} edited={edited.has(t.id)}
              onToggleSelect={() => setSelection(toggle(selection, t.id))}
              onToggleExpand={() => setExpanded(toggle(expanded, t.id))}
              onRename={() => setPanel({ kind: 'rename', id: t.id })}
              onSplit={() => setPanel({ kind: 'split', id: t.id })}
            />
          ))}
        </ul>
        {shown.length === 0 && (
          <p className="te-empty">
            No themes match.{' '}
            <button type="button" className="te-link" onClick={() => { setQuery(''); setChip('all') }}>
              Clear the filter to see all {themes.length}.
            </button>
          </p>
        )}

        {canEdit && (
          <div className={`te-selbar${bar.ready ? ' is-ready' : ''}`} role="status">
            <div>
              <div className="te-selbar-title">{bar.title}</div>
              <div className="te-selbar-detail">{bar.detail}</div>
            </div>
            <button type="button" className="te-btn is-primary" disabled={!bar.ready || busy}
              onClick={() => setPanel({ kind: 'merge' })}>
              <Merge size={18} {...ICON} />
              {bar.ready ? `Merge ${selected.length} themes…` : 'Merge…'}
            </button>
          </div>
        )}
      </div>

      {canEdit && (
        <aside className="te-side" ref={side}>
          {toast && (
            <div className="te-toast" aria-live="polite">
              <span>{toast}</span>
              <button type="button" className="te-toast-btn" onClick={() => setToast(null)}>Dismiss</button>
            </div>
          )}
          {error && <p className="te-error" role="alert">{error}</p>}
          {panel.kind === 'idle' && (
            <div className="te-panel">
              <h3 className="te-panel-title">Edit themes</h3>
              <p className="te-note">Tick two or more themes to merge them. Rename and split are on each row.</p>
            </div>
          )}
          {panel.kind === 'merge' && selected.length >= 2 && (
            <MergePanel
              themes={selected} totalAnswers={totalAnswers} busy={busy}
              onCancel={() => setPanel({ kind: 'idle' })}
              onMerge={(name) => void run(async () => {
                await onMerge(selected.map((t) => t.id), name)
                setSelection(new Set())
              }, `Merged ${selected.length} themes into “${name}”.`)}
            />
          )}
          {panel.kind === 'rename' && byId(panel.id) && (
            <RenamePanel
              theme={byId(panel.id) as ThemeCard} busy={busy} onCancel={() => setPanel({ kind: 'idle' })}
              onSave={(name) => {
                const before = (byId(panel.id) as ThemeCard).label
                void run(() => onRename(panel.id, name), `Renamed “${before}” to “${name}”.`)
              }}
            />
          )}
          {panel.kind === 'split' && byId(panel.id) && (
            <SplitPanel
              theme={byId(panel.id) as ThemeCard} busy={busy} job={splitJob}
              onCancel={() => setPanel({ kind: 'idle' })}
              onSplit={() => void run(() => onSplit(panel.id), `Splitting “${(byId(panel.id) as ThemeCard).label}”. The new themes appear when it finishes.`)}
            />
          )}
        </aside>
      )}
    </section>
    </div>
  )
}

function MergePanel({ themes, totalAnswers, busy, onCancel, onMerge }: {
  themes: ThemeCard[]
  totalAnswers: number
  busy: boolean
  onCancel: () => void
  onMerge: (name: string) => void
}) {
  const fallback = largestName(themes)
  const [name, setName] = useState(fallback)
  const c = combine(themes, totalAnswers)
  return (
    <div className="te-panel">
      <h3 className="te-panel-title"><Merge size={20} {...ICON} />{themes.length} themes become one</h3>
      <label className="te-field">
        <span>Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <p className="te-note">Left empty, it keeps the largest theme's name, {fallback}.</p>
      <dl className="te-figures">
        <div><dt>Share of all answers</dt><dd>{c.share}%</dd></div>
        <div><dt>Answers</dt><dd>{fmt(c.answers)}</dd></div>
        <div><dt>Tone</dt><dd>{formatTone(c.tone)}</dd></div>
      </dl>
      <p className="te-note">Sub-themes of every merged theme carry over.</p>
      <div className="te-buttons">
        <button type="button" className="te-btn is-primary" disabled={busy} onClick={() => onMerge(name.trim() || fallback)}>
          <Merge size={18} {...ICON} />Merge themes
        </button>
        <button type="button" className="te-btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  )
}

function RenamePanel({ theme, busy, onCancel, onSave }: {
  theme: ThemeCard
  busy: boolean
  onCancel: () => void
  onSave: (name: string) => void
}) {
  const [name, setName] = useState(theme.label)
  const clean = name.trim()
  return (
    <form className="te-panel" onSubmit={(e) => { e.preventDefault(); if (clean && clean !== theme.label) onSave(clean) }}>
      <h3 className="te-panel-title"><Pencil size={20} {...ICON} />Rename</h3>
      <label className="te-field">
        <span>New name for {theme.label}</span>
        <input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
      </label>
      <div className="te-buttons">
        <button type="submit" className="te-btn is-primary" disabled={busy || !clean || clean === theme.label}>Save name</button>
        <button type="button" className="te-btn" onClick={onCancel}>Cancel</button>
      </div>
    </form>
  )
}

function SplitPanel({ theme, busy, job, onCancel, onSplit }: {
  theme: ThemeCard
  busy: boolean
  job: Job | null
  onCancel: () => void
  onSplit: () => void
}) {
  const running = job !== null && job.status === 'running'
  return (
    <div className="te-panel">
      <h3 className="te-panel-title"><Split size={20} {...ICON} />{theme.label}</h3>
      <p className="te-note">
        {theme.size_pct.toFixed(1)}% of answers, {theme.sub_themes.length} sub-theme{theme.sub_themes.length === 1 ? '' : 's'} found.
      </p>
      <p className="te-note">Splitting re-reads this theme's answers in the background and names the parts it finds.</p>
      {running && job ? <JobProgress job={job} /> : (
        <div className="te-buttons">
          <button type="button" className="te-btn is-primary" disabled={busy || isOther(theme)} onClick={onSplit}>
            <Split size={18} {...ICON} />Split theme
          </button>
          <button type="button" className="te-btn" onClick={onCancel}>Cancel</button>
        </div>
      )}
    </div>
  )
}
