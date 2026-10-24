import { useState } from 'react'
import type { ContextData } from './questionContextData'
import { saveQuestionKind, type ReportBlock } from './reportApi'

export default function QuestionContext({
  datasetId, column, block, data,
}: {
  datasetId: number
  column: string
  block: ReportBlock
  data: ContextData
}) {
  const [ctx, setCtx] = useState(data)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save(kind: string | null) {
    setSaving(true)
    setError(null)
    try {
      const s = await saveQuestionKind(datasetId, column, kind)
      setCtx({ ...ctx, kind: s.kind, guessed_kind: s.guessed_kind, corrected: s.corrected })
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
        <select
          className="qc-select"
          aria-label="What the question asks for"
          value={ctx.kind}
          disabled={saving}
          onChange={(e) => save(e.target.value)}
        >
          {ctx.options.map((o) => (
            <option key={o} value={o}>{o}</option>
          ))}
        </select>
        , framed <span className="qc-fact">{ctx.framing}</span>, and answers run{' '}
        <span className="qc-fact">{ctx.length}</span>.
      </p>
      {ctx.corrected && (
        <p className="qc-note">
          You changed this from Verbatim's guess, <strong>{ctx.guessed_kind}</strong>.{' '}
          <button type="button" className="qc-reset" disabled={saving} onClick={() => save(null)}>
            Use Verbatim's guess
          </button>
        </p>
      )}
      {error && <p className="qc-error" role="alert">{error}</p>}
      <p className="qc-meta">{ctx.answered_note} {ctx.columns_note}</p>
      <p className="qc-meta">Framing and answer length are measured from the answers, so only the question type can be changed.</p>
    </div>
  )
}
