import { useState, type ReactNode } from 'react'
import { AnswerList } from './Themes'
import type { ReportBlock, ReportResponse } from './reportApi'
import './themes.css'
import './report.css'

function Badge({ confidence }: { confidence: 'solid' | 'tentative' }) {
  return <span className={`th-badge ${confidence}`}>{confidence === 'solid' ? 'Solid' : 'Tentative'}</span>
}

// Chart fragments arrive as a raw SVG/HTML BODY FRAGMENT (app.charts.render_parts's shape - no
// <!doctype html>, no own background, no own font load), built server-side from stored numbers and run
// through app.charts.py's own esc() escaping - never from anything a viewer typed. That is exactly why
// this is the one place in the app that uses dangerouslySetInnerHTML, unlike every other screen (see
// Cleaning.tsx's own comment), which renders potentially user-authored text as plain React children:
// there is no user-authored text anywhere in this string, only numbers and theme labels a Claude call or
// this app's own code already produced, HTML-escaped, before they ever reached here.
//
// It is sized by its own reported chart_width/chart_height (not a hardcoded per-chart-id guess): the
// outer .rp-chart-scroll only grows a horizontal scrollbar when this fixed-pixel content genuinely does
// not fit the viewport, instead of forcing every chart to a blanket minimum width regardless of its real
// size.
function ChartFragment({ block }: { block: ReportBlock }) {
  return (
    <div className="rp-chart-scroll">
      <div
        className="rp-chart"
        style={{ width: block.chart_width, minHeight: block.chart_height }}
        aria-label={block.chart_title}
        dangerouslySetInnerHTML={{ __html: block.chart_html }}
      />
    </div>
  )
}

function Divider({ children }: { children: ReactNode }) {
  return <div className="rp-section">{children}</div>
}

function FindingBlock({ datasetId, block }: { datasetId: number; block: ReportBlock }) {
  const [open, setOpen] = useState(false)
  const finding = block.finding
  if (!finding) return null
  return (
    <Divider>
      <div className="rp-head">
        <p className="rp-sentence">{finding.sentence}</p>
        <div className="rp-head-side">
          <Badge confidence={finding.confidence} />
          {finding.theme_id != null && (
            <button type="button" className="th-see" onClick={() => setOpen(!open)}>
              {open ? 'Hide answers' : 'See answers'}
            </button>
          )}
        </div>
      </div>
      <ChartFragment block={block} />
      {open && finding.theme_id != null && <AnswerList id={datasetId} themeId={finding.theme_id} />}
    </Divider>
  )
}

export default function ReportView({ report, datasetId }: { report: ReportResponse; datasetId: number }) {
  const overview = report.blocks.find((b) => b.kind === 'overview')
  const quality = report.blocks.find((b) => b.kind === 'quality')
  const findings = report.blocks.filter((b) => b.kind === 'finding')

  return (
    <div className="rp">
      <div className="rp-title">{report.question}</div>
      <div className="rp-summary">{report.summary}</div>

      <div className="rp-chips-label">Columns used</div>
      <div className="rp-chips">
        <span className="rp-chip">
          {report.column}
          <span className="rp-chip-note">open-ended text</span>
        </span>
      </div>

      {findings.length > 0 && (
        <div className="rp-standout">
          <div className="rp-standout-title">What stands out</div>
          <div className="rp-standout-list">
            {findings.map((b, i) => (
              <div className="rp-standout-row" key={b.finding_id ?? b.chart_id}>
                <span className="rp-standout-n">{i + 1}</span>
                <span className="rp-standout-sentence">{b.finding?.sentence}</span>
                {b.finding && <Badge confidence={b.finding.confidence} />}
              </div>
            ))}
          </div>
        </div>
      )}

      {overview && (
        <Divider>
          <ChartFragment block={overview} />
        </Divider>
      )}

      {findings.length > 0
        ? findings.map((b) => <FindingBlock key={b.finding_id ?? b.chart_id} datasetId={datasetId} block={b} />)
        : report.also_checked_nothing_notable && (
            <Divider>
              <div className="rp-nothing">Also checked, nothing notable.</div>
            </Divider>
          )}

      {quality && (
        <Divider>
          <ChartFragment block={quality} />
        </Divider>
      )}
    </div>
  )
}
