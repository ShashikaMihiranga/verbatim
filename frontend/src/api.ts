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
  }
}

export interface DatasetView {
  id: number
  filename: string
  row_count: number
  confirmed: boolean
  reused?: boolean
  profile: Profile
}

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

export async function uploadFile(file: File, onProgress: (pct: number) => void): Promise<DatasetView> {
  const headers = await authHeaders()
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', '/api/upload')
    headers.forEach((value, key) => xhr.setRequestHeader(key, value))
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100))
    }
    xhr.onerror = () => reject(new Error('Could not reach the server. Check your connection and try again.'))
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
    const form = new FormData()
    form.append('file', file)
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
): Promise<DatasetView> {
  const r = await authFetch(`/api/datasets/${id}/columns`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ columns, question }),
  })
  if (!r.ok) throw await asError(r)
  return r.json()
}
