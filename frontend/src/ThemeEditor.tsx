import { useEffect, useMemo, useRef, useState } from 'react'
import './theme-editor.css'
import { ChevronDown, ICON, Info, List, Merge, Pencil, Quote, Search, Split, Undo2 } from './icons'
import JobProgress from './JobProgress'
import type { MergePreview, SplitPreview } from './themeEditorApi'
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
  onSplitParts, loadMergePreview, loadSplitPreview,
}: {
  themes: ThemeCard[]
  totalAnswers: number
  canEdit: boolean // owners and editors; viewers get the list with no edit controls
  edited?: Set<number>
  splitJob?: Job | null
  onRename: (themeId: number, label: string) => Promise<void>
  onMerge: (themeIds: number[], label: string) => Promise<void>
  onSplit: (themeId: number) => Promise<void> // re-read by wording: a background job
  onSplitParts: (themeId: number, parts: number) => Promise<void> // along stored sub-themes, applied at once
  loadMergePreview: (themeIds: number[]) => Promise<MergePreview>
  loadSplitPreview: (themeId: number, parts?: number) => Promise<SplitPreview>
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
              themes={selected} totalAnswers={totalAnswers} busy={busy} load={loadMergePreview}
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
              theme={byId(panel.id) as ThemeCard} busy={busy} job={splitJob} load={loadSplitPreview}
              onCancel={() => setPanel({ kind: 'idle' })}
              onSplit={(parts) => {
                const name = (byId(panel.id) as ThemeCard).label
                if (parts === null) void run(() => onSplit(panel.id), `Splitting “${name}” by wording. The new themes appear when it finishes.`)
                else void run(() => onSplitParts(panel.id, parts), `Split “${name}” into ${parts} themes.`)
              }}
            />
          )}
        </aside>
      )}
    </section>
    </div>
  )
}

function MergePanel({ themes, totalAnswers, busy, load, onCancel, onMerge }: {
  themes: ThemeCard[]
  totalAnswers: number
  busy: boolean
  load: (ids: number[]) => Promise<MergePreview>
  onCancel: () => void
  onMerge: (name: string) => void
}) {
  const fallback = largestName(themes)
  const [name, setName] = useState(fallback)
  const [preview, setPreview] = useState<MergePreview | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const ids = themes.map((t) => t.id).join(',')
  useEffect(() => {
    let live = true
    load(ids.split(',').map(Number))
      .then((p) => { if (live) setPreview(p) })
      .catch((e) => { if (live) setFailed(e instanceof Error ? e.message : 'Could not load the preview.') })
    return () => { live = false }
  }, [ids, load])
  // Until the server answers, the same sums from the list (the server's merge uses the same weighting).
  const c = combine(themes, totalAnswers)
  const figures = preview ? { share: preview.share, answers: preview.answers, tone: preview.sentiment } : c
  return (
    <div className="te-panel">
      <h3 className="te-panel-title"><Merge size={20} {...ICON} />{themes.length} themes become one</h3>
      <label className="te-field">
        <span>Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} />
      </label>
      <p className="te-note">Left empty, it keeps the largest theme's name, {fallback}.</p>
      <dl className="te-figures">
        <div><dt>Share of all answers</dt><dd>{figures.share}%</dd></div>
        <div><dt>Answers</dt><dd>{fmt(figures.answers)}</dd></div>
        <div><dt>Tone</dt><dd>{formatTone(figures.tone)}</dd></div>
      </dl>
      <h4 className="te-sub-title"><Quote size={16} {...ICON} />What people said in each</h4>
      {failed && <p className="te-error" role="alert">{failed}</p>}
      {!preview && !failed && <p className="te-note" role="status">Loading answers…</p>}
      {preview && (
        <ul className="te-samples">
          {preview.themes.map((t) => (
            <li key={t.id}>
              <div className="te-samples-name">{t.label}</div>
              {t.samples.length ? t.samples.map((a, i) => <blockquote key={i}>{a}</blockquote>)
                : <p className="te-note">No readable answers.</p>}
            </li>
          ))}
        </ul>
      )}
      <p className="te-note"><Info size={14} {...ICON} />
        {preview && preview.sub_themes > 0
          ? `Sub-themes of every merged theme carry over (${preview.sub_themes}).`
          : 'Sub-themes of every merged theme carry over.'}
      </p>
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

function SplitPanel({ theme, busy, job, load, onCancel, onSplit }: {
  theme: ThemeCard
  busy: boolean
  job: Job | null
  load: (id: number, parts?: number) => Promise<SplitPreview>
  onCancel: () => void
  onSplit: (parts: number | null) => void // a number: along sub-themes; null: re-read by wording (a job)
}) {
  const [parts, setParts] = useState<number | undefined>(undefined)
  const [preview, setPreview] = useState<SplitPreview | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    load(theme.id, parts)
      .then((p) => { if (live) setPreview(p) })
      .catch((e) => { if (live) setFailed(e instanceof Error ? e.message : 'Could not load the preview.') })
    return () => { live = false }
  }, [theme.id, parts, load])
  const running = job !== null && job.status === 'running'
  const largest = Math.max(1, ...(preview?.parts.map((p) => p.answers) ?? [1]))
  return (
    <div className="te-panel">
      <h3 className="te-panel-title"><Split size={20} {...ICON} />{theme.label}</h3>
      <p className="te-note">
        {theme.size_pct.toFixed(1)}% of answers, {theme.sub_themes.length} sub-theme{theme.sub_themes.length === 1 ? '' : 's'} found.
      </p>
      {failed && <p className="te-error" role="alert">{failed}</p>}
      {!preview && !failed && <p className="te-note" role="status">Loading the preview…</p>}
      {preview && !preview.by_wording && (
        <>
          <div className="te-seg" role="radiogroup" aria-label="Split into">
            <span className="te-seg-label">Split into</span>
            {preview.choices.map((n) => (
              <button key={n} type="button" role="radio" aria-checked={preview.parts_chosen === n}
                className="te-seg-btn" onClick={() => setParts(n)}>{n}</button>
            ))}
          </div>
          <ul className="te-parts">
            {preview.parts.map((p) => (
              <li key={p.label}>
                <div className="te-part-head">
                  <span className="te-part-name">{p.label}{p.keeps_theme && <span className="te-note"> (keeps the theme)</span>}</span>
                  <span className="te-num">{p.share}% · {fmt(p.answers)}</span>
                </div>
                <span className="te-bar" aria-hidden="true"><span style={{ width: `${(p.answers / largest) * 100}%` }} /></span>
                {p.sample && <blockquote>{p.sample}</blockquote>}
              </li>
            ))}
          </ul>
          <p className="te-note"><Info size={14} {...ICON} />Each part is one of the sub-themes found when the themes were built. The rest stays as {theme.label}.</p>
        </>
      )}
      {preview?.by_wording && (
        <p className="te-note"><Info size={14} {...ICON} />{theme.label} has no sub-themes, so its answers are grouped by wording in the background. The new themes appear when that finishes.</p>
      )}
      {running && job ? <JobProgress job={job} /> : (
        <div className="te-buttons">
          <button type="button" className="te-btn is-primary" disabled={busy || !preview || isOther(theme)}
            onClick={() => preview && onSplit(preview.by_wording ? null : preview.parts_chosen ?? null)}>
            <Split size={18} {...ICON} />Split theme
          </button>
          <button type="button" className="te-btn" onClick={onCancel}>Cancel</button>
        </div>
      )}
    </div>
  )
}
