import { useState } from 'react'
import type { ReportBlock, ReportThemeChartVariant } from './reportApi'
import ThemeChart from './ThemeChart'

// Chart-type switcher (docs/TODO.md, 2026-10-21 Stage 2): the mockup's 5-tab switcher, minus the two
// tabs this stage deliberately defers - "Known themes" (a bespoke animated build, Stage 3) and "Arc"
// (app/api_report.py's own comment: no real multi-label cooccurrence signal this hard-clustering
// pipeline can produce, so there is nothing honest to show there yet). The first tab reuses the SAME
// treemap fragment Report.tsx's overview block already renders (so theme-click selection keeps working
// unchanged); the other three ("icicle" | "sentsun" | "rank") come from `theme_chart_variants`, all
// built server-side from the one already-built report_data - see reportApi.ts's own comment on that
// field for why there is no separate API call per tab.
const VARIANT_ORDER: Array<{ id: string; label: string }> = [
  { id: 'icicle', label: 'Icicle' },
  { id: 'sentsun', label: 'Sentiment sun' },
  { id: 'rank', label: 'Rank' },
  { id: 'diverge', label: 'Tone split' },
  { id: 'sunburst', label: 'Sunburst' },
]

export default function ThemeChartTabs({
  overview,
  variants,
  onThemeSelect,
  selectedTheme,
  highlightOtherRunning,
}: {
  overview: ReportBlock
  variants: Record<string, ReportThemeChartVariant>
  onThemeSelect?: (name: string) => void
  // Theme editing (docs/TODO.md, fixed 2026-10-22): threaded into both the treemap tab and whichever
  // variant tab is active, so a selection persists across tab switches too, not just within one tab.
  selectedTheme?: string | null
  // Stage 3b (docs/TODO.md, fixed 2026-10-23): only meaningful on the treemap tab (the only chart that
  // draws an `[data-theme="Other"]` block) - passed to every tab anyway since `ThemeChart` itself is
  // already a no-op when that group doesn't exist in a given fragment.
  highlightOtherRunning?: boolean
}) {
  const [active, setActive] = useState<string>('treemap')
  const available = VARIANT_ORDER.filter((v) => variants?.[v.id])

  if (available.length === 0) {
    // No variants reached the response (e.g. an older cached report) - render just the treemap, same as
    // before this feature existed, rather than showing a tab bar with nothing to switch to.
    return (
      <ThemeChart
        fragment={overview} title={overview.chart_title} onThemeSelect={onThemeSelect}
        selectedTheme={selectedTheme} highlightOtherRunning={highlightOtherRunning}
      />
    )
  }

  return (
    <div>
      <div className="rp-tabs" role="tablist">
        <button
          type="button"
          role="tab"
          aria-selected={active === 'treemap'}
          className={`rp-tab ${active === 'treemap' ? 'active' : ''}`}
          onClick={() => setActive('treemap')}
        >
          Known themes
        </button>
        {available.map((v) => (
          <button
            key={v.id}
            type="button"
            role="tab"
            aria-selected={active === v.id}
            className={`rp-tab ${active === v.id ? 'active' : ''}`}
            onClick={() => setActive(v.id)}
          >
            {v.label}
          </button>
        ))}
      </div>

      {active === 'treemap' ? (
        <ThemeChart
          fragment={overview} title={overview.chart_title} onThemeSelect={onThemeSelect}
          selectedTheme={selectedTheme} highlightOtherRunning={highlightOtherRunning}
        />
      ) : (
        <ThemeChart fragment={variants[active]} title={variants[active].chart_title} selectedTheme={selectedTheme} />
      )}
    </div>
  )
}
