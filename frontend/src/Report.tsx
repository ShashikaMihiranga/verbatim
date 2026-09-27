import { useState } from 'react'
import { AnswerList } from './Themes'
import type { ReportBlock, ReportResponse } from './reportApi'
import './themes.css'
import './report.css'

// Matches the fixed pixel heights app/charts.py's own frame() helper bakes into each chart's HTML
// (overview 680, rank 860, treemap/sentsun 800, quality 880 - see app/charts.py), plus a small margin so
// the iframe never clips the chart. The chart HTML itself is not responsive (SPEC.md/CLAUDE.md's charts
// were designed desktop-first); a horizontal scrollbar on narrow screens is the accepted fallback, not a
// silent clip - see docs/DECISIONS.md.
const CHART_HEIGHTS: Record<string, number> = {
  overview: 720, rank: 900, treemap: 840, sentsun: 840, quality: 920,
}

function Badge({ confidence }: { confidence: 'solid' | 'tentative' }) {
  return <span className={`th-badge ${confidence}`}>{confidence === 'solid' ? 'Solid' : 'Tentative'}</span>
}

// Charts arrive as a full, already-rendered HTML document (app.charts.render()'s own shape: <!doctype
// html>...) built server-side from stored numbers, never from anything a viewer typed. It is never dropped
// into the page with dangerouslySetInnerHTML (no code in this app does that - see Cleaning.tsx's own
// comment to that effect); an iframe with a fully-locked-down sandbox keeps it isolated even though the
// content here is trusted, matching this project's general "never trust rendered HTML" habit rather than
// carving out an exception for this one case.
function ChartFrame({ block }: { block: ReportBlock }) {
  const height = CHART_HEIGHTS[block.chart_id] ?? 800
  return (
    <div className="rp-frame">
      <iframe title={block.chart_title} srcDoc={block.chart_html} sandbox="" loading="lazy" style={{ height }} />
    </div>
  )
}

function FindingBlock({ datasetId, block }: { datasetId: number; block: ReportBlock }) {
  const [open, setOpen] = useState(false)
  const finding = block.finding
  if (!finding) return null
  return (
    <div className="rp-block">
      <div className="rp-head">
        <p className="rp-sentence">{finding.sentence}</p>
        <Badge confidence={finding.confidence} />
      </div>
      <ChartFrame block={block} />
      {finding.theme_id != null && (
        <>
          <button type="button" className="th-see" onClick={() => setOpen(!open)}>
            {open ? 'Hide answers' : 'See answers'}
          </button>
          {open && <AnswerList id={datasetId} themeId={finding.theme_id} />}
        </>
      )}
    </div>
  )
}

export default function ReportView({ report, datasetId }: { report: ReportResponse; datasetId: number }) {
  const overview = report.blocks.find((b) => b.kind === 'overview')
  const quality = report.blocks.find((b) => b.kind === 'quality')
  const findings = report.blocks.filter((b) => b.kind === 'finding')

  return (
    <div className="rp">
      <div className="rp-header">
        <div className="rp-question">{report.question}</div>
        <div className="rp-summary">{report.summary}</div>
      </div>

      {overview && (
        <div className="rp-block rp-overview">
          <ChartFrame block={overview} />
        </div>
      )}

      {findings.length > 0
        ? findings.map((b) => <FindingBlock key={b.finding_id ?? b.chart_id} datasetId={datasetId} block={b} />)
        : report.also_checked_nothing_notable && (
            <div className="rp-nothing">Also checked, nothing notable.</div>
          )}

      {quality && (
        <div className="rp-block rp-quality">
          <ChartFrame block={quality} />
        </div>
      )}
    </div>
  )
}
