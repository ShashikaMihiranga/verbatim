import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import ReportView from './Report'
import type { ReportResponse } from './reportApi'
import type { Job } from './jobsApi'
import type { SampleReport } from './home/sampleReport'
import sampleJson from '../public/sample/report.json?raw'

// A page anyone can open (share link, sample report) cannot show answers (that needs sign-in) or the
// analyst explorations; the sample page also shows its own title and leaves out the column chips.
const report = {
  dataset_id: 0, column: 'Comment', question: 'Comment', summary: '3 themes found.', also_checked_nothing_notable: false,
  columns_used: [{ name: 'Real_Property_Use', role: 'segment' }], filter_options: { segment: null, score_band: null, date_range: null },
  filters_applied: {}, other_breakdown: null, all_themes: [], theme_chart_variants: {},
  explorations: [{ chart_id: 'binnedGrid', chart_title: 'Two numbers', chart_label: 'Cleanliness and Condition', chart_html: '<div>grid</div>', chart_width: 100, chart_height: 100 }],
  blocks: [{ kind: 'finding', chart_id: 'heatmap', chart_title: 'Heatmap', chart_html: '<div>chart</div>', chart_width: 100, chart_height: 100,
    priority: 1, finding_id: 1, finding: { id: 1, theme_id: 7, sentence: 'Hospitals raise privacy more often.', confidence: 'solid' } }],
} as unknown as ReportResponse

describe('report view on public pages', () => {
  it('signed-in view keeps See answers, explorations, title and chips', () => {
    const html = renderToStaticMarkup(<ReportView report={report} datasetId={1} />)
    expect(html).toContain('See answers')
    expect(html).toContain('Explore Cleanliness and Condition')
    expect(html).toContain('rp-title')
    expect(html).toContain('Real_Property_Use')
  })

  it('public view drops See answers and explorations but keeps the finding', () => {
    const html = renderToStaticMarkup(<ReportView report={report} datasetId={0} publicView />)
    expect(html).not.toContain('See answers')
    expect(html).not.toContain('Explore Cleanliness')
    expect(html).toContain('Hospitals raise privacy more often.')
    expect(html).toContain('Real_Property_Use')
  })

  it('bare view leaves the title, summary and column chips to the page', () => {
    const html = renderToStaticMarkup(<ReportView report={report} datasetId={0} publicView bare />)
    expect(html).not.toContain('rp-title')
    expect(html).not.toContain('3 themes found.')
    expect(html).not.toContain('Real_Property_Use')
  })

  it('the sample draws Inside Other and its answer map from the frozen data, without fetching', () => {
    const sample = JSON.parse(sampleJson) as SampleReport
    const job = { id: 0, dataset_id: 0, column: sample.column, kind: 'look_inside_other', status: 'done', step: 'Done', error: null,
      result: sample.sample_extras!.look_inside_other } as Job
    const html = renderToStaticMarkup(
      <ReportView report={sample} datasetId={0} publicView bare lookInsideOtherJob={job} answerMap={sample.sample_extras!.answer_map} />,
    )
    expect(html).toContain('Inside Other')
    expect(html).toContain('How all answers group')
    expect(html).toContain('Secondhand smoke near entrances')
    expect(html).toContain('Explore all themes')
    expect((html.match(/<circle/g) ?? []).length).toBeGreaterThan(1000)
  })
})
