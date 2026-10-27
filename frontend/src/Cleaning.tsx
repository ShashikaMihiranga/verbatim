import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { applyCleaning, buildPlan, editPlan } from './cleaningApi'
import type { PlanResponse, PlanStep, StepEdit, StepReport } from './cleaningApi'
import FlowSteps from './FlowSteps'
import './upload.css'
import './cleaning.css'

// Everything below renders user text as React text nodes only. Nothing here uses dangerouslySetInnerHTML.

type Pending = {
  enabled: Record<string, boolean>
  merges: Record<string, Record<string, { to?: string; enabled?: boolean }>>
  params: Record<string, Record<string, unknown>>
}
const empty = (): Pending => ({ enabled: {}, merges: {}, params: {} })
const MAX_ROWS_SHOWN = 100

function Blankable({ text, className }: { text: string; className: string }) {
  return text === '' ? <div className={`${className} blank`}>(blank)</div> : <div className={className}>{text}</div>
}

function countText(r: StepReport | undefined): string {
  if (!r) return ''
  if (r.status === 'skipped') return 'Switched off. Nothing will change.'
  if (r.status === 'failed') return 'This step could not run on your data, so it was skipped.'
  if (r.status === 'no_change') return 'Nothing to change here.'
  const n = r.rows_affected || r.cells_affected
  return `${n.toLocaleString()} ${n === 1 ? 'row' : 'rows'} affected`
}

export default function Cleaning() {
  const [params] = useSearchParams()
  const nav = useNavigate()
  const id = Number(params.get('dataset'))
  const [resp, setResp] = useState<PlanResponse | null>(null)
  const [pending, setPending] = useState<Pending>(empty())
  const [error, setError] = useState('')
  const [busy, setBusy] = useState<'' | 'preview' | 'apply'>('')

  useEffect(() => {
    if (!id) return
    buildPlan(id)
      .then(setResp)
      .catch((e: Error) => setError(e.message))
  }, [id])

  const reports = useMemo(() => {
    const m: Record<string, StepReport> = {}
    for (const s of resp?.preview.steps ?? []) m[s.id] = s
    return m
  }, [resp])

  const groups = useMemo(() => {
    const out: { name: string | null; steps: PlanStep[] }[] = []
    const steps = resp?.plan.steps ?? []
    for (const s of steps) {
      const g = out.find((x) => x.name === s.column)
      if (g) g.steps.push(s)
      else out.push({ name: s.column, steps: [s] })
    }
    return out.sort((a, b) => Number(b.name === null) - Number(a.name === null))
  }, [resp])

  if (!id) {
    return (
      <>
        <h1>Cleaning review</h1>
        <p className="muted">
          Nothing to review yet. <Link to="/upload">Upload a spreadsheet</Link> first.
        </p>
      </>
    )
  }
  if (!resp) {
    return error ? (
      <>
        <h1>Cleaning review</h1>
        <p className="err" role="alert">{error}</p>
        <Link to={`/check-columns?dataset=${id}`}>Back to Check columns</Link>
      </>
    ) : (
      <p className="muted">Looking at your data...</p>
    )
  }

  const dirty =
    Object.keys(pending.enabled).length + Object.keys(pending.merges).length + Object.keys(pending.params).length > 0

  function edits(): StepEdit[] {
    const ids = new Set([...Object.keys(pending.enabled), ...Object.keys(pending.merges), ...Object.keys(pending.params)])
    return [...ids].map((sid) => ({
      id: sid,
      enabled: pending.enabled[sid],
      params: pending.params[sid],
      merges: Object.entries(pending.merges[sid] ?? {}).map(([from, v]) => ({ from, ...v })),
    }))
  }

  async function refresh() {
    setBusy('preview')
    setError('')
    try {
      setResp(await editPlan(id, edits()))
      setPending(empty())
    } catch (e) {
      setError((e as Error).message)
    }
    setBusy('')
  }

  async function next() {
    setBusy('apply')
    setError('')
    try {
      if (dirty) await editPlan(id, edits())
      await applyCleaning(id)
      nav(`/report?dataset=${id}`)
    } catch (e) {
      setError((e as Error).message)
      setBusy('')
    }
  }

  const setEnabled = (sid: string, v: boolean) => setPending({ ...pending, enabled: { ...pending.enabled, [sid]: v } })
  const setMerge = (sid: string, from: string, v: { to?: string; enabled?: boolean }) =>
    setPending({
      ...pending,
      merges: { ...pending.merges, [sid]: { ...pending.merges[sid], [from]: { ...pending.merges[sid]?.[from], ...v } } },
    })
  const setParam = (sid: string, k: string, v: unknown) =>
    setPending({ ...pending, params: { ...pending.params, [sid]: { ...pending.params[sid], [k]: v } } })

  const p = resp.preview
  const removed = p.rows_in - p.rows_out
  const sens = Object.entries(p.suppression)

  return (
    <>
      <div className="head">
        <h1>Cleaning review</h1>
        <FlowSteps current={3} />
      </div>
      <div className="cl-summary">
        <b>{p.rows_in.toLocaleString()}</b> rows in, <b>{p.rows_out.toLocaleString()}</b> rows after cleaning
        {removed > 0 ? `; ${removed.toLocaleString()} removed and listed below` : '; none removed'}. Your original file is never
        changed. Untick any step you do not want.
      </div>

      {p.warnings.length > 0 && (
        <div className="cl-warn" role="note">
          <b>Worth a look</b>
          <ul>{p.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </div>
      )}
      {removed > 0 && (
        <div className="cl-note">
          <b>Rows removed</b>
          <ul>
            {Object.entries(p.removed_by_step).map(([sid, n]) => (
              <li key={sid}>{n.toLocaleString()} by "{reports[sid]?.title ?? sid}"</li>
            ))}
          </ul>
          {p.removed_rows.slice(0, 5).map((r) => (
            <div key={r.row} className="muted" style={{ fontSize: 14 }}>Row {r.row}: {r.reason}</div>
          ))}
          {p.removed_rows_truncated || p.removed_rows.length > 5 ? (
            <div className="muted" style={{ fontSize: 14 }}>Every removed row is listed in the saved report.</div>
          ) : null}
        </div>
      )}

      {groups.map((g) => (
        <section key={g.name ?? '_file'} className="cl-group">
          <h2>{g.name ?? 'Whole file'}</h2>
          <div className="sub">{g.name ? '' : 'Steps that look at every row and column.'}</div>
          {g.steps.map((s) => {
            const r = reports[s.id]
            const on = pending.enabled[s.id] ?? s.enabled
            const pv = pending.params[s.id] ?? {}
            const merges = s.params.merges ?? []
            return (
              <div key={`${s.id}|${JSON.stringify([s.params.scale, s.params.min_count, s.params.day_first])}`} className="cl-step">
                <div className="cl-top">
                  <input type="checkbox" id={`en-${s.id}`} checked={on} onChange={(e) => setEnabled(s.id, e.target.checked)} />
                  <label htmlFor={`en-${s.id}`}>{s.title}</label>
                </div>
                <div className="cl-desc">{s.description}</div>
                <div className={`cl-count${on ? '' : ' off'}`}>{on ? countText(r) : 'Switched off. Nothing will change.'}</div>
                {on && typeof r?.details.summary === 'string' && <div className="cl-desc" style={{ marginTop: 4 }}>{r.details.summary}</div>}
                {on && r?.notes.map((n) => <div key={n} className="cl-desc" style={{ marginTop: 4 }}>{n}</div>)}

                {s.key === 'check_score_range' && s.params.scale && (
                  <div className="cl-param">
                    <span>Scale from</span>
                    <input type="number" aria-label="Scale low" defaultValue={s.params.scale[0]}
                      onChange={(e) => setParam(s.id, 'scale', [Number(e.target.value), (pv.scale as number[] | undefined)?.[1] ?? s.params.scale![1]])} />
                    <span>to</span>
                    <input type="number" aria-label="Scale high" defaultValue={s.params.scale[1]}
                      onChange={(e) => setParam(s.id, 'scale', [(pv.scale as number[] | undefined)?.[0] ?? s.params.scale![0], Number(e.target.value)])} />
                    <span className="muted">then choose Update preview.</span>
                  </div>
                )}
                {s.key === 'merge_small_groups' && typeof s.params.min_count === 'number' && (
                  <div className="cl-param">
                    <span>Merge groups with fewer than</span>
                    <input type="number" min={2} aria-label="Smallest group size" defaultValue={s.params.min_count}
                      onChange={(e) => setParam(s.id, 'min_count', Math.max(2, Math.floor(Number(e.target.value)) || 2))} />
                    <span>answers. Choose Update preview after changing it.</span>
                  </div>
                )}
                {s.key === 'parse_dates' && (
                  <div className="cl-param">
                    <label htmlFor={`df-${s.id}`}>Dates like 03/04/2025 are</label>
                    <select id={`df-${s.id}`} defaultValue={String(s.params.day_first ?? 'null')}
                      onChange={(e) => setParam(s.id, 'day_first', e.target.value === 'null' ? null : e.target.value === 'true')}>
                      <option value="true">day first (3 April)</option>
                      <option value="false">month first (4 March)</option>
                      <option value="null">not sure (read as month first)</option>
                    </select>
                  </div>
                )}

                {on && r && r.examples.length > 0 && (
                  <div className="cl-ex" aria-label="Before and after examples">
                    {r.examples.map((e, i) => (
                      <div key={i} style={{ display: 'contents' }}>
                        <Blankable text={e.before} className="b" />
                        <div className="arrow" aria-hidden="true">{'→'}</div>
                        <Blankable text={e.after} className="a" />
                      </div>
                    ))}
                  </div>
                )}

                {merges.length > 0 && (
                  <div className="cl-table" role="group" aria-label={`Merge table for ${g.name ?? 'file'}`}>
                    <div className="r h"><span /><span>Answer in your file</span><span>Becomes</span><span className="n">Rows</span></div>
                    {merges.slice(0, MAX_ROWS_SHOWN).map((m) => {
                      const pm = pending.merges[s.id]?.[m.from] ?? {}
                      return (
                        <div key={m.from} className="r">
                          <input type="checkbox" aria-label={`Merge ${m.from}`} checked={pm.enabled ?? m.enabled}
                            onChange={(e) => setMerge(s.id, m.from, { enabled: e.target.checked })} />
                          <span className="from">{m.from}</span>
                          <input type="text" maxLength={200} aria-label={`New label for ${m.from}`} value={pm.to ?? m.to}
                            onChange={(e) => setMerge(s.id, m.from, { to: e.target.value })} />
                          <span className="n">{m.count === null ? 'hidden' : m.count.toLocaleString()}</span>
                          <span className="how">{m.how}</span>
                        </div>
                      )
                    })}
                    {merges.length > MAX_ROWS_SHOWN && (
                      <div className="muted">Showing {MAX_ROWS_SHOWN} of {merges.length}. The rest are merged as listed in the saved plan.</div>
                    )}
                    {s.params.table_notes?.map((n) => <div key={n} className="muted">{n}</div>)}
                  </div>
                )}
              </div>
            )
          })}
        </section>
      ))}

      {sens.length > 0 && (
        <div className="cl-note">
          <b>Sensitive columns</b>
          <ul>
            {sens.map(([name, info]) => (
              <li key={name}>
                {name}: groups smaller than {info.min_group_size} are hidden
                {info.hidden_groups ? ` (${info.hidden_groups} hidden)` : ''}, and individual rows are never shown.
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && <div className="err" role="alert">{error}</div>}
      <div className="foot">
        <Link to={`/check-columns?dataset=${id}`} className="btn quiet" style={{ textDecoration: 'none' }}>Back</Link>
        <button className="btn quiet" type="button" onClick={refresh} disabled={!dirty || busy !== ''}>
          {busy === 'preview' ? 'Updating...' : 'Update preview'}
        </button>
        <button className="btn" type="button" onClick={next} disabled={busy !== ''}>
          {busy === 'apply' ? 'Cleaning...' : 'Continue'}
        </button>
      </div>
    </>
  )
}
