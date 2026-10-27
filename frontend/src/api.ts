import { authFetch, authHeaders, handleUnauthorized } from './authFetch'

export type Kind =
  | 'open_text'
  | 'short_text'
  | 'score'
  | 'date'
  | 'segment'
  | 'numeric'
  | 'yes_no'
  | 'id_or_junk'

export const KIND_LABELS: Record<Kind, string> = {
  open_text: 'Open-ended text',
  short_text: 'Short text',
  score: 'Score',
  date: 'Date',
  segment: 'Segment',
  numeric: 'Number',
  yes_no: 'Yes / no',
  id_or_junk: 'Ignored',
}

export interface ColumnProfile {
  name: string
  position: number
  kind: Kind
  confidence: number
  reason: string
  unit: string | null
  distinct: number
  missing: number
  median_words: number
  samples: string[]
  sensitive: boolean
  sensitive_reason: string | null
  is_question: boolean
  looks_headerless: boolean
  suggested_name?: string | null
}

export interface Profile {
  row_count: number
  column_count: number
  columns: ColumnProfile[]
  question: { text: string; source: string; column: string | null } | null
  notes: string[]
  headerless_suspected?: boolean
  confirmed?: {
    columns: Record<string, { kind: Kind; off: boolean }>
    renames?: Record<string, string>
    question: string | null
    // docs/TODO.md (fixed 2026-10-22): which open_text column is the report's subject, when the user
    // explicitly overrode the automatic pick (`pickOpenTextColumn` in Themes.tsx). `null`/absent means
    // "no override - keep picking automatically", the only behaviour that existed before this field.
    primary_open_text?: string | null
  }
}

export interface DatasetView {
  id: number
  filename: string
  row_count: number
  confirmed: boolean
  reused?: boolean // the same file was already uploaded: this is that earlier project
  uploaded_at?: string | null
  profile: Profile
}

export interface UploadLimits {
  max_mb: number
  extensions: string[]
}

export async function getUploadLimits(): Promise<UploadLimits> {
  const r = await authFetch('/api/upload/limits')
  if (!r.ok) throw await asError(r)
  return r.json()
}

// Thrown when the person cancels an upload, so the page can go back to the empty box without a message.
export class UploadCancelled extends Error {}

async function asError(r: Response): Promise<Error> {
  let msg = `Something went wrong (${r.status}).`
  try {
    const j = await r.json()
    if (typeof j.detail === 'string') msg = j.detail
  } catch {
    /* keep the default message */
  }
  return new Error(msg)
}

// `duplicate`: the Uploads page's "Upload anyway" (a second project from a file uploaded before).
// `signal`: aborting it cancels the upload (rejects with `UploadCancelled`).
export async function uploadFile(
  file: File,
  onProgress: (pct: number, loaded: number, total: number) => void,
  opts: { duplicate?: boolean; signal?: AbortSignal } = {},
): Promise<DatasetView> {
  const headers = await authHeaders()
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/upload')
    headers.forEach((value, key) => xhr.setRequestHeader(key, value))
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100), e.loaded, e.total)
    }
    xhr.onerror = () => reject(new Error('Could not reach the server. Check your connection and try again.'))
    xhr.onabort = () => reject(new UploadCancelled('Upload cancelled.'))
    xhr.onload = () => {
      handleUnauthorized(xhr.status)
      let body: any = null
      try {
        body = JSON.parse(xhr.responseText)
      } catch {
        /* not JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300 && body) resolve(body as DatasetView)
      else reject(new Error(typeof body?.detail === 'string' ? body.detail : `Upload failed (${xhr.status}).`))
    }
    opts.signal?.addEventListener('abort', () => xhr.abort(), { once: true })
    const form = new FormData()
    form.append('file', file)
    if (opts.duplicate) form.append('duplicate', 'true')
    xhr.send(form)
  })
}

export async function getProfile(id: number): Promise<DatasetView> {
  const r = await authFetch(`/api/datasets/${id}/profile`)
  if (!r.ok) throw await asError(r)
  return r.json()
}

export async function confirmColumns(
  id: number,
  columns: { position: number; name: string; kind: Kind; off: boolean }[],
  question: string | null,
  primaryOpenText?: string | null,
): Promise<DatasetView> {
  const r = await authFetch(`/api/datasets/${id}/columns`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ columns, question, primary_open_text: primaryOpenText ?? null }),
  })
  if (!r.ok) throw await asError(r)
  return r.json()
}
