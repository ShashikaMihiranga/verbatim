export interface MergeEntry {
  from: string
  to: string
  count: number | null
  how: string
  enabled: boolean
}

export interface PlanStep {
  id: string
  key: string
  column: string | null
  title: string
  description: string
  enabled: boolean
  params: {
    merges?: MergeEntry[]
    table_notes?: string[]
    scale?: [number, number]
    min_count?: number
    day_first?: boolean | null
    basis?: string
    [k: string]: unknown
  }
}

export interface Example {
  before: string
  after: string
}

export interface StepReport {
  id: string
  key: string
  column: string | null
  title: string
  enabled: boolean
  status: 'applied' | 'no_change' | 'skipped' | 'failed'
  rows_affected: number
  cells_affected: number
  examples: Example[]
  details: Record<string, unknown>
  notes: string[]
}

export interface SuppressionInfo {
  min_group_size: number
  hidden_groups?: number
  groups: { label: string; count: number | null; hidden: boolean }[] | null
}

export interface CleaningReport {
  rows_in: number
  rows_out: number
  columns_in: number
  columns_out: number
  steps: StepReport[]
  removed_rows_total: number
  removed_by_step: Record<string, number>
  removed_rows: { row: number; step: string; reason: string }[]
  removed_rows_truncated: boolean
  removed_columns: { name: string; reason: string }[]
  excluded_columns: string[]
  flagged_rows: number
  pii: Record<string, number>
  suppression: Record<string, SuppressionInfo>
  warnings: string[]
  accounted_for: boolean
}

export interface PlanResponse {
  plan: { steps: PlanStep[]; settings: { min_group_size: number } }
  preview: CleaningReport
}

export interface StepEdit {
  id: string
  enabled?: boolean
  params?: Record<string, unknown>
  merges?: { from: string; to?: string; enabled?: boolean }[]
}

async function call<T>(url: string, method: string, body?: unknown): Promise<T> {
  const r = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!r.ok) {
    let msg = `Something went wrong (${r.status}).`
    try {
      const j = await r.json()
      if (typeof j.detail === 'string') msg = j.detail
    } catch {
      /* keep the default message */
    }
    throw new Error(msg)
  }
  return r.json() as Promise<T>
}

export const buildPlan = (id: number) => call<PlanResponse>(`/api/datasets/${id}/clean/plan`, 'POST')
export const editPlan = (id: number, steps: StepEdit[]) =>
  call<PlanResponse>(`/api/datasets/${id}/clean/plan`, 'PATCH', { steps })
export const applyCleaning = (id: number) =>
  call<{ report: CleaningReport }>(`/api/datasets/${id}/clean/apply`, 'POST')
