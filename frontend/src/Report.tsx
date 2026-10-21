import { useState, type ReactNode } from 'react'
import { AnswerList } from './Themes'
import type { Job } from './jobsApi'
import type { ReportBlock, ReportFilters as ReportFiltersValue, ReportResponse } from './reportApi'
import type { ThemeCard } from './themesApi'
import LookInsideOther from './LookInsideOther'
import OtherExploration from './OtherExploration'
import ReportFilters from './ReportFilters'
import ThemeChart from './ThemeChart'
import ThemeChartTabs from './ThemeChartTabs'
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
function ChartFragment({ block, onThemeSelect }: { block: ReportBlock; onThemeSelect?: (name: string) => void }) {
  return <ThemeChart fragment={block} title={block.chart_title} onThemeSelect={onThemeSelect} />
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
  const findings = report.blocks.filter((b) => b.kind === 'finding')
  const [selectedThemeName, setSelectedThemeName] = useState<string | null>(null)
  const selectedTheme = themes?.find((t) => t.label === selectedThemeName) ?? null

  return (
    <div className="rp">
      <div className="rp-title">{report.question}</div>
      <div className="rp-summary">{report.summary}</div>

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
          <ThemeChartTabs
            overview={overview}
            variants={report.theme_chart_variants}
            onThemeSelect={setSelectedThemeName}
          />
          {selectedTheme && <ThemeDetail id={datasetId} theme={selectedTheme} />}
        </Divider>
      )}

      <OtherExploration breakdown={report.other_breakdown} allThemes={report.all_themes} />

      {onLookInsideOther && (report.other_breakdown !== null || lookInsideOtherJob) && (
        <LookInsideOther job={lookInsideOtherJob ?? null} onStart={onLookInsideOther} />
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
