import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { KIND_LABELS, confirmColumns, getProfile } from './api'
import type { DatasetView, Kind } from './api'
import { Steps } from './Upload'
import './upload.css'

const KINDS = Object.keys(KIND_LABELS) as Kind[]

export default function CheckColumns() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const id = Number(params.get('dataset'))
  const [ds, setDs] = useState<DatasetView | null>(null)
  const [kinds, setKinds] = useState<Record<string, Kind>>({})
  const [off, setOff] = useState<Record<string, boolean>>({})
  const [names, setNames] = useState<Record<string, string>>({})
  const [question, setQuestion] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (!id) return
    getProfile(id)
      .then((d) => {
        setDs(d)
        const conf = d.profile.confirmed
        const k: Record<string, Kind> = {}
        const o: Record<string, boolean> = {}
        const n: Record<string, string> = {}
        for (const c of d.profile.columns) {
          k[c.name] = conf?.columns[c.name]?.kind ?? c.kind
          o[c.name] = conf?.columns[c.name]?.off ?? false
          n[c.name] = c.looks_headerless ? (c.suggested_name ?? c.name) : c.name
        }
        setKinds(k)
        setOff(o)
        setNames(n)
        setQuestion(conf?.question ?? d.profile.question?.text ?? '')
      })
      .catch((e: Error) => setError(e.message))
  }, [id])

  if (!id) {
    return (
      <>
        <h1>Check columns</h1>
        <p className="muted">
          Nothing to check yet. <Link to="/upload">Upload a spreadsheet</Link> first.
        </p>
      </>
    )
  }
  if (error && !ds) {
    return (
      <>
        <h1>Check columns</h1>
        <p className="err" role="alert">{error}</p>
        <Link to="/upload">Back to upload</Link>
      </>
    )
  }
  if (!ds) return <p className="muted">Loading...</p>

  const { profile } = ds
  const textCol = profile.columns.find(
    (c) => (kinds[c.name] ?? c.kind) === 'open_text' && !c.sensitive,
  )

  async function save() {
    setSaving(true)
    setError('')
    try {
      await confirmColumns(
        id,
        profile.columns.map((c) => ({
          position: c.position,
          name: (names[c.name] ?? c.name).trim() || c.name,
          kind: kinds[c.name],
          off: !!off[c.name],
        })),
        question.trim() || null,
      )
      nav(`/cleaning?dataset=${id}`)
    } catch (e) {
      setError((e as Error).message)
      setSaving(false)
    }
  }

  return (
    <>
      <div className="head">
        <h1>Check columns</h1>
        <Steps step={2} />
      </div>
      <div className="muted" style={{ marginTop: -20, marginBottom: 28 }}>
        <b style={{ color: 'var(--ink)', fontWeight: 600 }}>{ds.filename}</b>{' '}
        {profile.row_count.toLocaleString()} rows, {profile.column_count} columns
      </div>

      <div className="cols">
        <div className="left">
          <div className="hint">We guessed each column type. Change any that look wrong.</div>
          {profile.columns.map((c) => {
            const kind = kinds[c.name] ?? c.kind
            const ignored = kind === 'id_or_junk'
            return (
              <div key={c.name} className={`row${ignored ? ' ignored' : ''}`}>
                <span className="nm">
                  {c.name}
                  {c.sensitive && <span className="badge sens">Sensitive</span>}
                  {c.confidence < 0.7 && !ignored && <span className="badge unsure">Not sure</span>}
                  {c.looks_headerless && <span className="badge unsure">No header found - check this name</span>}
                </span>
                <input
                  type="text"
                  className="chip"
                  aria-label={`Column name for ${c.name}`}
                  value={names[c.name] ?? c.name}
                  onChange={(e) => setNames({ ...names, [c.name]: e.target.value })}
                />
                <select
                  className={`chip${kind === 'open_text' ? ' active' : ''}`}
                  aria-label={`Type of ${c.name}`}
                  value={kind}
                  onChange={(e) => setKinds({ ...kinds, [c.name]: e.target.value as Kind })}
                >
                  {KINDS.map((k) => (
                    <option key={k} value={k}>
                      {KIND_LABELS[k]}
                    </option>
                  ))}
                </select>
                {c.sensitive && (
                  <label className="off">
                    <input
                      type="checkbox"
                      checked={!!off[c.name]}
                      onChange={(e) => setOff({ ...off, [c.name]: e.target.checked })}
                    />
                    Switch off in shared reports
                  </label>
                )}
                <span className="why">
                  {c.reason}
                  {c.unit ? ` Unit: ${c.unit}.` : ''}
                  {c.sensitive
                    ? ` ${c.sensitive_reason ?? ''} Groups are shown, never individual rows, and small groups are hidden.`
                    : ''}
                  {c.missing ? ` ${c.missing.toLocaleString()} blank.` : ''}
                </span>
              </div>
            )
          })}
        </div>

        <div className="right">
          <label htmlFor="q" style={{ fontSize: 14, fontWeight: 500, display: 'block', marginBottom: 6 }}>
            Question asked
          </label>
          <textarea
            id="q"
            className="qbox"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Type the question people were answering"
          />
          <div className="qnote">
            {profile.question
              ? profile.question.source === 'header'
                ? 'Taken from the column heading. Edit it if it is not the exact wording.'
                : 'Taken from the file. Edit it if it is not the exact wording.'
              : 'We could not find the question in the file. Add it so the report can use it.'}
          </div>
          {textCol && textCol.samples.length > 0 && (
            <>
              <div className="hint">First answers</div>
              {textCol.samples.slice(0, 3).map((s) => (
                <div key={s} className="ans">{s}</div>
              ))}
            </>
          )}
          {profile.notes.length > 0 && (
            <ul className="notes">
              <li style={{ fontWeight: 500 }}>What we did while reading your file</li>
              {profile.notes.map((n) => (
                <li key={n}>{n}</li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {error && <div className="err" role="alert">{error}</div>}
      <div className="foot">
        <span className="muted" style={{ fontSize: 15 }}>Your file stays private to your workspace.</span>
        <Link to="/upload" className="btn quiet" style={{ textDecoration: 'none' }}>Back</Link>
        <button className="btn" type="button" onClick={save} disabled={saving}>
          {saving ? 'Saving...' : 'Continue'}
        </button>
      </div>
    </>
  )
}
