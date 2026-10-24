import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import QuestionContext from './QuestionContext'
import { parseContextData } from './questionContextData'
import ReportView from './Report'
import type { ReportBlock, ReportResponse } from './reportApi'

// Exact fragment app/charts.py context_report produces (copied from a real render), including a
// columns note with quotes, & and angle brackets, so the parser is tested against real escaping.
const SERVER_FRAGMENT = "<div style=\"padding:56px 48px\" data-context=\"{&quot;kind&quot;: &quot;opinions&quot;, &quot;options&quot;: [&quot;reasons&quot;, &quot;improvements&quot;, &quot;experiences&quot;, &quot;facts&quot;, &quot;anything else&quot;, &quot;opinions&quot;], &quot;guessed_kind&quot;: &quot;reasons&quot;, &quot;corrected&quot;: true, &quot;framing&quot;: &quot;negatively&quot;, &quot;length&quot;: &quot;a sentence or two&quot;, &quot;answered_note&quot;: &quot;47,525 of 50,000 responses had an answer to analyse.&quot;, &quot;columns_note&quot;: &quot;Age \\&quot;group\\&quot; &amp; &lt;score&gt; also cross-cut this report.&quot;}\"><div style=\"font-size:36px;font-weight:300;line-height:1.3;max-width:1020px\">This question asks for <span style=\"color:var(--accent);font-weight:400\">opinions</span>, framed <span style=\"color:var(--accent);font-weight:400\">negatively</span>, and answers run <span style=\"color:var(--accent);font-weight:400\">a sentence or two</span>.</div><div style=\"margin-top:20px;font-size:17px;line-height:1.55;max-width:820px;color:var(--muted)\">47,525 of 50,000 responses had an answer to analyse. Age &quot;group&quot; &amp; &lt;score&gt; also cross-cut this report. You changed this from Verbatim's guess, reasons.</div></div>"

const block = (html: string): ReportBlock => ({
  kind: 'context', chart_id: 'context', chart_title: 'Question context', chart_html: html,
  chart_width: 1180, chart_height: 300, priority: 1, finding_id: null, finding: null,
})

describe('question context', () => {
  it('reads the real server payload, decoding html entities', () => {
    const d = parseContextData(SERVER_FRAGMENT)
    expect(d?.kind).toBe('opinions')
    expect(d?.guessed_kind).toBe('reasons')
    expect(d?.corrected).toBe(true)
    expect(d?.columns_note).toBe('Age "group" & <score> also cross-cut this report.')
    expect(d?.options).toContain('facts')
  })

  it('returns null for fragments without a payload or with broken JSON', () => {
    expect(parseContextData('<div>plain</div>')).toBeNull()
    expect(parseContextData('<div data-context="{not json">x</div>')).toBeNull()
  })

  it('renders a real dropdown, never a permanently open menu', () => {
    const data = parseContextData(SERVER_FRAGMENT)!
    const html = renderToStaticMarkup(
      <QuestionContext datasetId={1} column="Why" block={block(SERVER_FRAGMENT)} data={data} />,
    )
    expect(html).toContain('<select')
    expect(html).toMatch(/<option value="opinions" selected="">opinions<\/option>/)
    expect(html).toContain('Use Verbatim')
    expect(html).toContain('negatively')
  })

  it('the report uses the control when the payload exists, and the plain fragment otherwise', () => {
    const base = {
      dataset_id: 1, column: 'Why', question: 'Q', summary: '', also_checked_nothing_notable: false,
      columns_used: [], filter_options: { segment: null, score_band: null, date_range: null },
      filters_applied: {}, other_breakdown: null, all_themes: [], theme_chart_variants: {},
    } as unknown as ReportResponse
    const withPayload = renderToStaticMarkup(<ReportView datasetId={1} report={{ ...base, blocks: [block(SERVER_FRAGMENT)] }} />)
    expect(withPayload).toContain('<select')
    const legacy = renderToStaticMarkup(<ReportView datasetId={1} report={{ ...base, blocks: [block('<div>LEGACY-CONTEXT</div>')] }} />)
    expect(legacy).toContain('LEGACY-CONTEXT')
    expect(legacy).not.toContain('<select')
  })
})
