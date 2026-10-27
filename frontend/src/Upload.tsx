import { useEffect, useRef, useState } from 'react'
import type { DragEvent, KeyboardEvent, ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { getUploadLimits, uploadFile, UploadCancelled } from './api'
import type { DatasetView, UploadLimits } from './api'
import FlowSteps from './FlowSteps'
import { getProjects, linkFor } from './projectsApi'
import type { ProjectSummary } from './projectsApi'
import { fileSize, uploadedAgo, uploadedOn } from './uploadFormat'
import './upload.css'
import './uploads.css'

// The Uploads page (design/handoffs/Uploads_UIHandoff.md, design/gen_uploadpage.py): what to upload, the
// drop card in every state a file can be in (driven by the real upload: byte progress, then the server
// reading the columns, then its answer), what is private, what happens next, and earlier uploads.

type Phase =
  | { kind: 'empty' }
  | { kind: 'uploading'; file: File; pct: number; loaded: number }
  | { kind: 'reading'; file: File }
  | { kind: 'ready'; file: File; ds: DatasetView }
  | { kind: 'duplicate'; file: File; ds: DatasetView }
  | { kind: 'error'; title: string; text: string; retry: File | null }

const DEFAULT_LIMITS: UploadLimits = { max_mb: 50, extensions: ['.csv', '.xls', '.xlsx'] }

export default function Upload() {
  const nav = useNavigate()
  const input = useRef<HTMLInputElement>(null)
  const abort = useRef<AbortController | null>(null)
  const [phase, setPhase] = useState<Phase>({ kind: 'empty' })
  const [over, setOver] = useState(false)
  const [limits, setLimits] = useState<UploadLimits>(DEFAULT_LIMITS)
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null)
  const [announce, setAnnounce] = useState('')
  const busy = phase.kind === 'uploading' || phase.kind === 'reading'

  useEffect(() => {
    let live = true
    getUploadLimits().then((l) => { if (live) setLimits(l) }).catch(() => { /* keep the default */ })
    getProjects().then((p) => { if (live) setProjects(p) }).catch(() => { if (live) setProjects([]) })
    return () => { live = false; abort.current?.abort() }
  }, [])

  function fail(title: string, text: string, retry: File | null = null) {
    setPhase({ kind: 'error', title, text, retry })
    setAnnounce(`${title} ${text}`)
  }

  async function start(file: File | undefined, duplicate = false) {
    if (!file || busy) return
    const ext = (file.name.match(/\.[^.]+$/)?.[0] ?? '').toLowerCase()
    if (!limits.extensions.includes(ext)) {
      fail('That file type is not supported.',
        `Verbatim reads .xlsx, .xls and .csv files. ${ext ? `This one is a ${ext}.` : 'This one has no file type.'}`)
      return
    }
    if (file.size > limits.max_mb * 1024 * 1024) {
      fail(`This file is larger than ${limits.max_mb} MB.`,
        'Try saving it as .csv, or remove columns you do not need and upload it again.')
      return
    }
    const ctrl = new AbortController()
    abort.current = ctrl
    setPhase({ kind: 'uploading', file, pct: 0, loaded: 0 })
    setAnnounce(`Uploading ${file.name}, 0 percent`)
    let lastSaid = 0
    try {
      const ds = await uploadFile(file, (pct, loaded) => {
        if (pct >= 100) {
          setPhase({ kind: 'reading', file })
          setAnnounce('Reading the columns')
          return
        }
        setPhase({ kind: 'uploading', file, pct, loaded })
        if (pct - lastSaid >= 25) { lastSaid = pct - (pct % 25); setAnnounce(`Uploading ${file.name}, ${lastSaid} percent`) }
      }, { duplicate, signal: ctrl.signal })
      if (ds.reused) {
        setPhase({ kind: 'duplicate', file, ds })
        setAnnounce(`You already uploaded this file. ${ds.filename} is saved once.`)
        return
      }
      setPhase({ kind: 'ready', file, ds })
      setAnnounce(`Your file is ready. ${columnsText(ds)}, ${rowsText(ds)}.`)
      getProjects().then(setProjects).catch(() => {})
    } catch (e) {
      if (e instanceof UploadCancelled) { setPhase({ kind: 'empty' }); setAnnounce('Upload cancelled.'); return }
      const msg = (e as Error).message
      if (/too large/i.test(msg)) fail(`This file is larger than ${limits.max_mb} MB.`, 'Try saving it as .csv, or remove columns you do not need and upload it again.')
      else fail('That upload did not work.', msg, file)
    } finally {
      if (abort.current === ctrl) abort.current = null
    }
  }

  const pick = () => input.current?.click()
  const reset = () => { setPhase({ kind: 'empty' }); setAnnounce('') }
  const canDrop = phase.kind === 'empty' || phase.kind === 'error' || phase.kind === 'ready' || phase.kind === 'duplicate'

  function onDrop(e: DragEvent) {
    e.preventDefault()
    setOver(false)
    if (canDrop) void start(e.dataTransfer.files[0])
  }
  function onKey(e: KeyboardEvent) {
    if (e.target !== e.currentTarget || !canDrop) return
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); pick() }
  }

  const showDrop = phase.kind === 'empty' || phase.kind === 'error'
  return (
    <>
      <div className="head">
        <h1>Uploads</h1>
        <FlowSteps current={1} />
      </div>
      <p className="up-intro">
        Upload a spreadsheet with your survey answers. <b>One column of written answers is enough.</b> Columns like age,
        score or date make the report smarter.
      </p>

      <section
        className={`up-card${over && canDrop ? ' is-over' : ''}`} tabIndex={0} aria-label="Upload a spreadsheet"
        onKeyDown={onKey}
        onDragEnter={(e) => { e.preventDefault(); if (canDrop) setOver(true) }}
        onDragOver={(e) => { e.preventDefault(); if (canDrop) setOver(true) }}
        onDragLeave={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(false) }}
        onDrop={onDrop}
      >
        <span className="up-sr" aria-live="polite">{announce}</span>
        {showDrop && (
          <div className="up-state up-drop" key={over ? 'over' : 'drop'}>
            <span className="up-ico" aria-hidden="true">{ICON.up}</span>
            <div className="up-title">{over ? 'Drop to upload' : 'Drop your spreadsheet here'}</div>
            {!over && (
              <>
                <div className="up-or">or</div>
                <button type="button" className="up-btn" onClick={pick}>Browse files</button>
                <div className="up-hint">
                  .xlsx, .xls or .csv, up to {limits.max_mb} MB.{limits.max_mb >= 50 ? ' Built for large files.' : ''}
                </div>
              </>
            )}
          </div>
        )}

        {(phase.kind === 'uploading' || phase.kind === 'reading' || phase.kind === 'duplicate') && (
          <div className="up-state up-fileblock" key="file">
            <FileCard
              name={phase.file.name}
              sub={phase.kind === 'uploading' ? `${fileSize(phase.loaded)} of ${fileSize(phase.file.size)}` : fileSize(phase.file.size)}
              right={phase.kind === 'uploading' ? `${phase.pct}%` : 'Saved'}
              pct={phase.kind === 'uploading' ? phase.pct : 100}
              onCancel={phase.kind === 'uploading' ? () => abort.current?.abort() : undefined}
            />
            {phase.kind === 'reading' && (
              <ul className="up-reads">
                <li className="is-done"><Tick />File received and saved</li>
                <li className="is-running"><Spin />Reading the columns</li>
                <li><Ring />Guessing what each column is</li>
              </ul>
            )}
          </div>
        )}

        {phase.kind === 'ready' && (
          <div className="up-state up-ready" key="ready">
            <span className="up-ico is-done" aria-hidden="true">{ICON.check}</span>
            <div className="up-title">Your file is ready</div>
            <div className="up-chips">
              <span className="up-chip">{phase.ds.filename}</span>
              <span className="up-chip">{columnsText(phase.ds)}</span>
              <span className="up-chip">{rowsText(phase.ds)}</span>
            </div>
            <p className="up-next-line">Next, you confirm what each column is. It takes a minute.</p>
            <div className="up-btns">
              <button type="button" className="up-btn" onClick={() => nav(`/check-columns?dataset=${phase.ds.id}`)}>
                Check columns{ICON.arrow}
              </button>
              <button type="button" className="up-btn is-outline" onClick={reset}>Upload another file</button>
            </div>
          </div>
        )}

        {phase.kind === 'duplicate' && (
          <div className="up-note is-warn" key="dup">
            <div className="up-note-title">You already uploaded this file.</div>
            <div>
              {phase.ds.filename} was uploaded{phase.ds.uploaded_at ? ` on ${uploadedOn(phase.ds.uploaded_at)}` : ''} and is
              saved once. You can open it instead of uploading it again.
            </div>
            <div className="up-note-btns">
              <button type="button" className="up-pill" onClick={() => nav(openLink(phase.ds, projects))}>Open it</button>
              <button type="button" className="up-pill is-outline" onClick={() => void start(phase.file, true)}>Upload anyway</button>
            </div>
          </div>
        )}

        {phase.kind === 'error' && (
          <div className="up-note is-err" role="alert" key="err">
            <div className="up-note-title">{phase.title}</div>
            <div>{phase.text}</div>
            <div className="up-note-btns">
              {phase.retry && <button type="button" className="up-pill" onClick={() => void start(phase.retry ?? undefined)}>Try again</button>}
              <button type="button" className={`up-pill${phase.retry ? ' is-outline' : ''}`} onClick={pick}>Choose another file</button>
            </div>
          </div>
        )}

        <input
          ref={input}
          type="file"
          hidden
          accept={limits.extensions.join(',')}
          onChange={(e) => {
            void start(e.target.files?.[0])
            e.target.value = ''
          }}
        />
      </section>

      <div className="up-trust">
        {TRUST.map(([icon, title, text]) => (
          <div key={title} className="up-trust-card">
            <span className="up-trust-ico" aria-hidden="true">{icon}</span>
            <div><div className="up-trust-title">{title}</div><div className="up-trust-text">{text}</div></div>
          </div>
        ))}
      </div>

      <section className="up-steps-next" aria-labelledby="up-next-h">
        <h2 id="up-next-h" className="up-label">What happens next</h2>
        <ol>
          {NEXT.map(([title, text], i) => (
            <li key={title}>
              <span className="up-num" aria-hidden="true">{i + 2}</span>
              <div><div className="up-next-title">{title}</div><div className="up-next-text">{text}</div></div>
            </li>
          ))}
        </ol>
      </section>

      <section className="up-recent" aria-labelledby="up-recent-h">
        <div className="up-recent-head">
          <h2 id="up-recent-h">Your uploads</h2>
          {projects && projects.length > RECENT && <Link to="/projects">See all {projects.length}</Link>}
        </div>
        {projects === null && <p className="muted">Looking for your uploads...</p>}
        {projects !== null && projects.length === 0 && (
          <div className="up-empty-list">
            <div className="up-next-title">No uploads yet</div>
            <div className="muted">Your files will appear here, so you can pick up where you left off.</div>
          </div>
        )}
        {projects !== null && projects.length > 0 && (
          <ul className="up-list">
            {projects.slice(0, RECENT).map((p) => {
              const s = STATUS[p.status]
              return (
                <li key={p.id}>
                  <Link to={linkFor(p)} className="up-row">
                    <span className="up-row-ico" aria-hidden="true">{ICON.file}</span>
                    <span className="up-row-main">
                      <span className="up-row-name">{p.filename}</span>
                      <span className="up-row-sub">Uploaded {uploadedAgo(p.created_at)}</span>
                    </span>
                    <span className={`up-status is-${s.tone}`}>{s.label}</span>
                    <span className="up-action">{s.action}</span>
                  </Link>
                </li>
              )
            })}
          </ul>
        )}
      </section>
    </>
  )
}

const SVG = { width: 22, height: 22, viewBox: '0 0 24 24', fill: 'none', stroke: 'currentColor', strokeWidth: 2, strokeLinecap: 'round' as const, strokeLinejoin: 'round' as const, 'aria-hidden': true }
const ICON = {
  up: <svg {...SVG} width={34} height={34}><path d="M12 16V5M7 10l5-5 5 5" /><path d="M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3" /></svg>,
  check: <svg {...SVG} width={36} height={36} strokeWidth={3}><path d="M5 12l5 5 9-10" /></svg>,
  file: <svg {...SVG}><path d="M7 3h7l5 5v12a1 1 0 01-1 1H7a1 1 0 01-1-1V4a1 1 0 011-1z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></svg>,
  arrow: <svg {...SVG} width={20} height={20}><path d="M5 12h14M13 6l6 6-6 6" /></svg>,
}
const RECENT = 6

// Checked against the code (app/cleaning/redact.py, app/cleaning/payload.py, app/api_upload.py, sharing).
const TRUST: Array<[ReactNode, string, string]> = [
  [<svg key="l" {...SVG}><rect x="5" y="11" width="14" height="9" rx="2" /><path d="M8 11V8a4 4 0 018 0v3" /></svg>,
    'Masked first', 'Emails, phone numbers, links and ID numbers are masked before Voyage or Claude read your answers.'],
  [<svg key="d" {...SVG}><ellipse cx="12" cy="6" rx="7" ry="3" /><path d="M5 6v12c0 1.7 3 3 7 3s7-1.3 7-3V6" /><path d="M5 12c0 1.7 3 3 7 3s7-1.3 7-3" /></svg>,
    'Private to you', 'Your file is stored once. Only you, and people you invite, can open it.'],
  [<svg key="s" {...SVG}><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z" /></svg>,
    'Claude sees samples only', 'A few masked sample answers, never your whole file.'],
]

const NEXT: Array<[string, string]> = [
  ['Check columns', 'You confirm what each column is.'],
  ['Cleaning review', 'Emails, phone numbers and IDs are masked. You review the cleaning.'],
  ['Report', 'Verbatim finds the themes and builds your report.'],
]

const STATUS: Record<ProjectSummary['status'], { label: string; action: string; tone: 'accent' | 'green' | 'muted' }> = {
  uploaded: { label: 'Check columns', action: 'Continue', tone: 'accent' },
  'columns confirmed': { label: 'Cleaning review', action: 'Continue', tone: 'accent' },
  cleaned: { label: 'Ready for themes', action: 'Continue', tone: 'accent' },
  'finding themes': { label: 'Finding themes', action: 'See progress', tone: 'accent' },
  'themes built': { label: 'Themes built', action: 'Open', tone: 'muted' },
  'report ready': { label: 'Report ready', action: 'Open report', tone: 'green' },
}

function columnsText(ds: DatasetView) {
  const n = ds.profile?.columns?.length ?? 0
  return `${n} column${n === 1 ? '' : 's'}`
}
function rowsText(ds: DatasetView) {
  return `${ds.row_count.toLocaleString()} row${ds.row_count === 1 ? '' : 's'}`
}

// "Open it" on a duplicate: wherever that earlier project is up to, same as the Projects page.
function openLink(ds: DatasetView, projects: ProjectSummary[] | null) {
  const p = projects?.find((x) => x.id === ds.id)
  return p ? linkFor(p) : ds.confirmed ? `/report?dataset=${ds.id}` : `/check-columns?dataset=${ds.id}`
}

function FileCard({ name, sub, right, pct, onCancel }: { name: string; sub: string; right: string; pct: number; onCancel?: () => void }) {
  return (
    <div className="up-file">
      <span className="up-file-ico" aria-hidden="true">{ICON.file}</span>
      <div className="up-file-main">
        <div className="up-file-top"><span className="up-file-name">{name}</span><span className="up-file-pct">{right}</span></div>
        <div className="up-file-sub">{sub}</div>
        <span className="up-prog" role="progressbar" aria-label={`Uploading ${name}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct}>
          <i style={{ width: `${pct}%` }} />
        </span>
      </div>
      {onCancel && <button type="button" className="up-cancel" onClick={onCancel}>Cancel</button>}
    </div>
  )
}

const Tick = () => <svg className="up-li-ico" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="11" fill="#3f8a57" /><path d="M7 12.5l3.2 3.2L17 9" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" /></svg>
const Spin = () => <svg className="up-li-ico up-spin" viewBox="0 0 24 24" fill="none" strokeWidth="3" strokeLinecap="round" aria-hidden="true"><circle cx="12" cy="12" r="9" stroke="var(--line)" /><path d="M12 3a9 9 0 019 9" stroke="var(--accent)" /></svg>
const Ring = () => <svg className="up-li-ico" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9" fill="none" stroke="var(--line)" strokeWidth="2" /></svg>
