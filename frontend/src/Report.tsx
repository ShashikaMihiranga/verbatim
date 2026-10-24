import { useState, type ReactNode } from 'react'
import { AnswerList } from './Themes'
import type { Job } from './jobsApi'
import type { ReportBlock, ReportFilters as ReportFiltersValue, ReportResponse, ReportThemeChartVariant } from './reportApi'
import type { ThemeCard } from './themesApi'
import InsideOther from './InsideOther'
import OtherExploration from './OtherExploration'
import QuestionContext from './QuestionContext'
import { parseContextData } from './questionContextData'
import ReportFilters from './ReportFilters'
import ThemeChart from './ThemeChart'
import ThemeChartTabs from './ThemeChartTabs'
import FindingChartTabs from './FindingChartTabs'
import ThemeDetail from './ThemeDetail'
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
// size. Rendering itself, and the click/hover delegation for chart fragments that draw `[data-theme]`
// groups (currently only the overview block's treemap), now live in the shared `ThemeChart` component -
// also used by Themes.tsx's browse view - rather than a second, near-identical implementation here.
function ChartFragment({
  block, onThemeSelect, selectedTheme,
}: {
  block: ReportBlock
  onThemeSelect?: (name: string) => void
  // Theme editing (docs/TODO.md, fixed 2026-10-22): "selecting a theme in one chart highlights it in all
  // charts" - every ChartFragment on the page receives the SAME selected name from ReportView's own
  // `selectedThemeName` state, not just the overview block it originated from.
  selectedTheme?: string | null
}) {
  return <ThemeChart fragment={block} title={block.chart_title} onThemeSelect={onThemeSelect} selectedTheme={selectedTheme} />
}

function Divider({ children, id }: { children: ReactNode; id?: string }) {
  return <section className="rp-section" id={id}>{children}</section>
}

// "context"/"quotes"/"phrases" blocks (chart-block stream, 2026-10-24, wiring batch A): always-on
// supplements, not competing findings - no Badge/"see answers" (FindingBlock's own, finding-only
// features), just the chart itself. Unlike FindingBlock, never returns null on missing data: the
// backend (app.findings.build_findings) only ever appends one of these three kinds once its own real
// data exists, so an empty block here would mean a real backend bug, not an expected "nothing to show".
function SupplementBlock({ block }: { block: ReportBlock }) {
  return (
    <Divider>
      <ChartFragment block={block} />
    </Divider>
  )
}

function FindingBlock({
  datasetId, block, selectedTheme,
}: {
  datasetId: number
  block: ReportBlock
  selectedTheme?: string | null
}) {
  const [open, setOpen] = useState(false)
  const finding = block.finding
  if (!finding) return null
  return (
    <Divider id={`report-finding-${finding.id}`}>
      <div className="rp-head">
        <h3 className="rp-sentence">{finding.sentence}</h3>
        <div className="rp-head-side">
          <Badge confidence={finding.confidence} />
          {finding.theme_id != null && (
            <button type="button" className="th-see" onClick={() => setOpen(!open)}>
              {open ? 'Hide answers' : 'See answers'}
            </button>
          )}
        </div>
      </div>
      <FindingChartTabs block={block} selectedTheme={selectedTheme} />
      {open && finding.theme_id != null && <AnswerList id={datasetId} themeId={finding.theme_id} />}
    </Divider>
  )
}

export default function ReportView({
  report,
  datasetId,
  themes,
  filters,
  onFiltersChange,
  lookInsideOtherJob,
  onLookInsideOther,
}: {
  report: ReportResponse
  datasetId: number
  // Real `Theme` rows for this column (Themes.tsx already fetches these before showing the report, so
  // it passes them straight through rather than this view fetching them a second time). Used only to
  // resolve the overview chart's `onThemeSelect` (a theme NAME - the treemap's own `data-theme` attribute)
  // back to the `ThemeCard` `ThemeDetail` needs (id, description, tone, ...). Optional: a caller with no
  // themes handy (e.g. a future standalone embed) still renders a perfectly good report, just without a
  // theme-detail panel under the overview chart.
  themes?: ThemeCard[]
  // Filters feature (SPEC.md section 5). Both optional: a caller with nothing to filter on (or that
  // hasn't wired filter state at all) still renders a perfectly good, unfiltered report - the filter bar
  // itself already hides whenever `report.filter_options` has every field `null` (see ReportFilters).
  filters?: ReportFiltersValue
  onFiltersChange?: (next: ReportFiltersValue) => void
  // "Look inside Other" Stage 3 (docs/TODO.md, 2026-10-21). Both optional: a caller with no job-watching
  // state wired up (e.g. a future standalone embed) still renders a perfectly good report, just without
  // the "Look inside" CTA - same optionality pattern as `filters`/`onFiltersChange` above.
  lookInsideOtherJob?: Job | null
  onLookInsideOther?: () => void
}) {
  const overview = report.blocks.find((b) => b.kind === 'overview')
  const quality = report.blocks.find((b) => b.kind === 'quality')
  // The API explicitly labels broad context. Do not infer a relationship from headline prose or
  // discard findings merely because they use the same chart family. Only identical context repeats.
  const shared = new Map<string, ReportThemeChartVariant>()
  const findings = report.blocks.filter((b) => b.kind === 'finding').map((block) => {
    const local: Record<string, ReportThemeChartVariant> = {}
    for (const [key, view] of Object.entries(block.chart_variants ?? {})) {
      if (view.chart_label?.startsWith('All themes:')) {
        const identity = JSON.stringify([key, view.chart_html, view.chart_note, view.chart_width, view.chart_height])
        if (!shared.has(identity)) shared.set(identity, { ...view, chart_id: view.chart_id ?? key })
      } else local[key] = view
    }
    return { ...block, chart_variants: local }
  })
  const sharedViews = Array.from(shared.values())
  const context = report.blocks.find((b) => b.kind === 'context')
  const contextData = context ? parseContextData(context.chart_html) : null
  const quotes = report.blocks.find((b) => b.kind === 'quotes')
  const phrases = report.blocks.find((b) => b.kind === 'phrases')
  const [selectedThemeName, setSelectedThemeName] = useState<string | null>(null)
  const selectedTheme = themes?.find((t) => t.label === selectedThemeName) ?? null

  return (
    <div className="rp">
      <h1 className="rp-title">{report.question}</h1>
      <div className="rp-summary">{report.summary}</div>

      {context && (contextData
        ? <QuestionContext datasetId={datasetId} column={report.column} block={context} data={contextData} />
        : <SupplementBlock block={context} />)}

      <div className="rp-chips-label">Columns used</div>
      <div className="rp-chips">
        {report.columns_used.map((c) => (
          <span className="rp-chip" key={c.name}>
            {c.name}
            <span className="rp-chip-note">{c.role}</span>
          </span>
        ))}
      </div>

      {onFiltersChange && (
        <ReportFilters
          options={report.filter_options}
          value={filters ?? {}}
          onChange={onFiltersChange}
        />
      )}

      <nav className="rp-outline" aria-label="Report sections">
        {overview && <a href="#report-overview">Big picture</a>}
        {findings.length > 0 && <a href="#report-findings">Findings ({findings.length})</a>}
        {quality && <a href="#report-quality">Data quality</a>}
      </nav>

      {overview && (
        <Divider id="report-overview">
          <h2 className="rp-section-title">The big picture</h2>
          <ThemeChartTabs
            overview={overview}
            variants={report.theme_chart_variants}
            onThemeSelect={setSelectedThemeName}
            selectedTheme={selectedThemeName}
            highlightOtherRunning={lookInsideOtherJob?.status === 'running'}
          />
          {selectedTheme && <ThemeDetail id={datasetId} theme={selectedTheme} />}
        </Divider>
      )}

      <OtherExploration breakdown={report.other_breakdown} allThemes={report.all_themes} />
      {report.other_breakdown && <p className="rp-method-note">Other is a catch-all bucket, not a single topic. Check its breakdown before interpreting differences between groups.</p>}

      {onLookInsideOther && (report.other_breakdown !== null || lookInsideOtherJob) && (
        <InsideOther job={lookInsideOtherJob ?? null} onStart={onLookInsideOther} allThemes={report.all_themes} />
      )}

      {sharedViews.length > 0 && <Divider id="report-explore">
        <details className="rp-exploration">
          <summary>Explore all themes</summary>
          <p className="rp-method-note">These views show the broader context under the current filters. Individual findings below keep their own focused evidence.</p>
          {sharedViews.map((view, index) => <details className="rp-context-view" key={`${view.chart_id}-${index}`}>
            <summary>{view.chart_label?.replace(/^All themes:\s*/, '') || view.chart_title}</summary>
            {view.chart_note && <p className="rp-method-note">{view.chart_note}</p>}
            <ThemeChart fragment={view} title={view.chart_title} selectedTheme={selectedThemeName} />
          </details>)}
        </details>
      </Divider>}

      {findings.length > 0
        ? <div id="report-findings">
          <h2 className="rp-section-title rp-findings-title">What stands out</h2>
          {findings.map((b) => (
            <FindingBlock key={b.finding_id ?? b.chart_id} datasetId={datasetId} block={b} selectedTheme={selectedThemeName} />
          ))}
        </div>
        : report.also_checked_nothing_notable && (
            <Divider>
              <div className="rp-nothing">Also checked, nothing notable.</div>
            </Divider>
          )}

      {(report.explorations ?? []).map((exploration) => (
        <Divider key={exploration.chart_id ?? exploration.chart_title}>
          <details className="rp-exploration">
            <summary>Explore {exploration.chart_label ?? exploration.chart_title}</summary>
            {exploration.chart_note && <p className="rp-method-note">{exploration.chart_note}</p>}
            <ThemeChart fragment={exploration} title={exploration.chart_title} selectedTheme={selectedThemeName} />
          </details>
        </Divider>
      ))}

      {quotes && <SupplementBlock block={quotes} />}
      {phrases && <SupplementBlock block={phrases} />}

      {quality && (
        <Divider id="report-quality">
          <ChartFragment block={quality} selectedTheme={selectedThemeName} />
        </Divider>
      )}
    </div>
  )
}
