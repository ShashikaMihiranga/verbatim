import { useEffect, useId, useRef, useState } from 'react'
import type { ContextData } from './questionContextData'
import { getQuestionKind, saveQuestionKind, type ReportBlock } from './reportApi'

// The question type is a styled menu, not a native <select>: the sentence is set at 36px, and a native
// menu opens at that size in the system's own font (macOS draws a huge grey popup). The menu keeps the
// listbox keyboard model: arrows move, Enter or Space picks, Escape closes.
function KindMenu({
  value, options, disabled, onPick,
}: {
  value: string
  options: string[]
  disabled: boolean
  onPick: (kind: string) => void
}) {
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(Math.max(0, options.indexOf(value)))
  const root = useRef<HTMLSpanElement>(null)
  const list = useRef<HTMLSpanElement>(null)
  const id = useId()

  useEffect(() => {
    if (!open) return
    list.current?.focus()
    const close = (e: MouseEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  function show() {
    setActive(Math.max(0, options.indexOf(value)))
    setOpen(true)
  }

  function pick(i: number) {
    setOpen(false)
    root.current?.querySelector('button')?.focus()
    if (options[i] !== value) onPick(options[i])
  }

  function onListKey(e: React.KeyboardEvent) {
    if (e.key === 'ArrowDown') setActive((a) => Math.min(options.length - 1, a + 1))
    else if (e.key === 'ArrowUp') setActive((a) => Math.max(0, a - 1))
    else if (e.key === 'Home') setActive(0)
    else if (e.key === 'End') setActive(options.length - 1)
    else if (e.key === 'Enter' || e.key === ' ') pick(active)
    else if (e.key === 'Escape' || e.key === 'Tab') {
      setOpen(false)
      if (e.key === 'Escape') root.current?.querySelector('button')?.focus()
      return
    } else return
    e.preventDefault()
  }

  return (
    <span className="qc-kind" ref={root}>
      <button
        type="button"
        className="qc-select"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`What the question asks for: ${value}`}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : show())}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault()
            show()
          }
        }}
      >
        {value}
        <span className="qc-caret" aria-hidden="true">▾</span>
      </button>
      {open && (
        // Spans, not <ul>/<li>: the menu sits inside the sentence's <p>, which may not hold a list.
        <span
          ref={list}
          className="qc-menu"
          role="listbox"
          tabIndex={-1}
          aria-label="What the question asks for"
          aria-activedescendant={`${id}-${active}`}
          onKeyDown={onListKey}
        >
          {options.map((o, i) => (
            <span
              key={o}
              id={`${id}-${i}`}
              role="option"
              aria-selected={o === value}
              className={`qc-option${i === active ? ' is-active' : ''}`}
              onMouseEnter={() => setActive(i)}
              onClick={() => pick(i)}
            >
              <span className="qc-check" aria-hidden="true">{o === value ? '✓' : ''}</span>
              {o}
            </span>
          ))}
        </span>
      )}
    </span>
  )
}

export default function QuestionContext({
  datasetId, column, block, data, onKindChange,
}: {
  datasetId: number
  column: string
  block: ReportBlock
  data: ContextData
  // Called after a change is saved, so the page can reload the report (it is now out of date).
  onKindChange?: () => void
}) {
  const [ctx, setCtx] = useState(data)
  // The type the current themes were named for; when it differs, the themes need a rebuild too.
  const [themesKind, setThemesKind] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Without onKindChange the page cannot save (a share link, the sample report): show the type as text.
  const readOnly = !onKindChange

  useEffect(() => {
    if (readOnly) return
    let live = true
    getQuestionKind(datasetId, column)
      .then((s) => { if (live) setThemesKind(s.themes_kind ?? null) })
      .catch(() => { /* the note is optional; the sentence still works */ })
    return () => { live = false }
  }, [datasetId, column, readOnly])

  async function save(kind: string | null) {
    setSaving(true)
    setError(null)
    try {
      const s = await saveQuestionKind(datasetId, column, kind)
      setCtx({ ...ctx, kind: s.kind, guessed_kind: s.guessed_kind, corrected: s.corrected })
      setThemesKind(s.themes_kind ?? null)
      onKindChange?.()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not save the change.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="rp-section qc" aria-label={block.chart_title}>
      <p className="qc-sentence">
        This question asks for{' '}
        {readOnly
          ? <span className="qc-fact">{ctx.kind}</span>
          : <KindMenu value={ctx.kind} options={ctx.options} disabled={saving} onPick={(k) => void save(k)} />}
        , framed <span className="qc-fact">{ctx.framing}</span>, and answers run{' '}
        <span className="qc-fact">{ctx.length}</span>.
      </p>
      {ctx.corrected && !readOnly && (
        <p className="qc-note">
          You changed this from Verbatim's guess, <strong>{ctx.guessed_kind}</strong>.{' '}
          <button type="button" className="qc-reset" disabled={saving} onClick={() => save(null)}>
            Use Verbatim's guess
          </button>
        </p>
      )}
      {themesKind && themesKind !== ctx.kind && (
        <p className="qc-note" role="status">
          The themes were named as {themesKind}. Rebuild themes in Manage themes to name them as {ctx.kind}.
        </p>
      )}
      {error && <p className="qc-error" role="alert">{error}</p>}
      {/* The columns note repeats the chips right below, so only the answered count stays. */}
      <p className="qc-meta">{ctx.answered_note}</p>
    </div>
  )
}
