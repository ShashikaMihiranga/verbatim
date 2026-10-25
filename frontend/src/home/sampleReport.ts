import type { ReportResponse } from '../reportApi'
import type { AnswerMapResponse } from '../themesApi'

// The sample report (/sample): a frozen copy of what a share link returns for the 10k workplace survey
// (tss_fy19_comments_10k.csv), saved at public/sample/report.json. The public page reads this file, never
// the database, so /sample works the same on every environment. Regenerate with
// tools/snapshot_sample_report.py when the report changes.
export const SAMPLE_REPORT_URL = '/sample/report.json'

// What the report page fetches with sign-in, frozen alongside the report (tools/snapshot_sample_report.py):
// the latest Look inside Other result and the answer map's dot positions.
export interface SampleReport extends ReportResponse {
  sample_extras?: { look_inside_other: Record<string, unknown> | null; answer_map: AnswerMapResponse | null }
}

let cached: Promise<SampleReport> | null = null

export function loadSampleReport(): Promise<SampleReport> {
  if (!cached) {
    cached = fetch(SAMPLE_REPORT_URL).then((r) => {
      if (!r.ok) throw new Error('The sample report could not be loaded.')
      return r.json() as Promise<SampleReport>
    })
    cached.catch(() => { cached = null }) // let a later visit try again
  }
  return cached
}
