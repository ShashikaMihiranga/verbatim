import { useRef, useState } from 'react'
import type { DragEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { uploadFile } from './api'
import './upload.css'

export function Steps({ step }: { step: 1 | 2 | 3 }) {
  const items = ['Upload', 'Check columns', 'Report']
  return (
    <div className="steps">
      {items.map((t, i) => (
        <span key={t} className={step === i + 1 ? 'on' : ''}>
          <b>{i + 1}</b>
          {t}
        </span>
      ))}
    </div>
  )
}

const OK = /\.(csv|xlsx|xls)$/i

export default function Upload() {
  const nav = useNavigate()
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const [pct, setPct] = useState<number | null>(null)
  const [reading, setReading] = useState(false)
  const [error, setError] = useState('')
  const [name, setName] = useState('')
  const busy = pct !== null

  async function start(file: File | undefined) {
    if (!file || busy) return
    setError('')
    if (!OK.test(file.name)) {
      setError('That file type is not supported. Please choose a .xlsx, .xls or .csv file.')
      return
    }
    setName(file.name)
    setPct(0)
    setReading(false)
    try {
      const ds = await uploadFile(file, (p) => {
        setPct(p)
        if (p >= 100) setReading(true)
      })
      nav(`/check-columns?dataset=${ds.id}`)
    } catch (e) {
      setError((e as Error).message)
      setPct(null)
      setReading(false)
    }
  }

  function onDrop(e: DragEvent) {
    e.preventDefault()
    setOver(false)
    void start(e.dataTransfer.files[0])
  }

  return (
    <>
      <div className="head">
        <h1>New project</h1>
        <Steps step={1} />
      </div>
      <div
        className={`drop${over ? ' over' : ''}`}
        onDragOver={(e) => {
          e.preventDefault()
          setOver(true)
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
      >
        {busy ? (
          <>
            <div className="big">{reading ? 'Reading your columns...' : 'Uploading...'}</div>
            <div className="muted">{name}</div>
            <div className="bar" role="progressbar" aria-valuenow={pct ?? 0} aria-valuemin={0} aria-valuemax={100}>
              <div style={{ width: `${pct}%` }} />
            </div>
            <div className="muted">{pct}%</div>
          </>
        ) : (
          <>
            <div className="big">Drop your spreadsheet here</div>
            <div className="muted">or</div>
            <button className="btn" type="button" onClick={() => input.current?.click()}>
              Browse files
            </button>
            <div className="small">.xlsx, .xls or .csv. Built for large files.</div>
          </>
        )}
        <input
          ref={input}
          type="file"
          hidden
          accept=".csv,.xlsx,.xls"
          onChange={(e) => {
            void start(e.target.files?.[0])
            e.target.value = ''
          }}
        />
      </div>
      {error && (
        <div className="err" role="alert">
          {error}
        </div>
      )}
    </>
  )
}
