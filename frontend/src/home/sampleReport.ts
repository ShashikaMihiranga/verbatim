import type { ReportBlock, ReportResponse } from '../reportApi'
import type { ChartFragmentData } from '../ThemeChart'

// The sample report: a frozen copy of what a share link returns for the 10k workplace survey
// (tss_fy19_comments_10k.csv), saved at public/sample/report.json. The public pages read this file, never
// the database, so the home page and /sample work the same on every environment. Regenerate with
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

export interface SampleTab {
  name: string
  chapter: string
  sentence: string
  needs: string
  pick: (r: ReportResponse) => ChartFragmentData | undefined
}

const variant = (r: ReportResponse, id: string): ChartFragmentData | undefined => r.theme_chart_variants?.[id]
const block = (r: ReportResponse, test: (b: ReportBlock) => boolean): ChartFragmentData | undefined => r.blocks.find(test)

// One idea per tab, each with the real chart and a sentence that report supports (no figures, per the
// product rules). The survey has no date column, so the design's "Over time" tab is left out.
export const SAMPLE_TABS: SampleTab[] = [
  { name: 'Theme map', chapter: 'The big picture', sentence: 'Noise and privacy is what people raise most, ahead of facility layout and design.', needs: 'Any written answers',
    pick: (r) => block(r, (b) => b.kind === 'overview') },
  { name: 'Tone by theme', chapter: 'What matters most', sentence: 'Overall workspace satisfaction sounds the most positive. Building cleanliness, pests and air quality sounds the most negative.', needs: 'Any written answers',
    pick: (r) => variant(r, 'diverge') },
  { name: 'Themes by group', chapter: 'Who sees it differently', sentence: 'Hospital sites raise space for patient privacy and care far more often than comments overall.', needs: 'A group column, like property type',
    pick: (r) => block(r, (b) => b.kind === 'finding' && /patient privacy/i.test(b.finding?.sentence ?? '') && /more often/i.test(b.finding?.sentence ?? '')) },
  { name: 'Scores by theme', chapter: 'Who sees it differently', sentence: 'People who raise space for patient privacy and care score workspace design lower than anyone else.', needs: 'A score column',
    pick: (r) => variant(r, 'themeScores') },
  { name: 'In their own words', chapter: 'In their own words', sentence: 'Real answers, so the numbers are believable.', needs: 'Any written answers',
    pick: (r) => block(r, (b) => b.kind === 'quotes') },
  { name: 'Key phrases', chapter: 'In their own words', sentence: 'People keep coming back to "not enough", "too small" and "no privacy".', needs: 'Any written answers',
    pick: (r) => block(r, (b) => b.kind === 'phrases') },
]
