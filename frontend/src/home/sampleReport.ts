import type { ReportResponse } from '../reportApi'

// The sample report (/sample): a frozen copy of what a share link returns for the 10k workplace survey
// (tss_fy19_comments_10k.csv), saved at public/sample/report.json. The public page reads this file, never
// the database, so /sample works the same on every environment. Regenerate with
// tools/snapshot_sample_report.py when the report changes.
export const SAMPLE_REPORT_URL = '/sample/report.json'

let cached: Promise<ReportResponse> | null = null

export function loadSampleReport(): Promise<ReportResponse> {
  if (!cached) {
    cached = fetch(SAMPLE_REPORT_URL).then((r) => {
      if (!r.ok) throw new Error('The sample report could not be loaded.')
      return r.json() as Promise<ReportResponse>
    })
    cached.catch(() => { cached = null }) // let a later visit try again
  }
  return cached
}
