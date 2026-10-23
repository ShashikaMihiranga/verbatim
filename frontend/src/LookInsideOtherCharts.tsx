import { useState } from 'react'
import type { LookInsideOtherChart } from './jobsApi'
import ThemeChart from './ThemeChart'

// Stage 3c (docs/TODO.md, fixed 2026-10-23): the mockup's own second, separate 5-tab chart switcher
// (Other-Flow-Done.dc.html, lines 108-133) for the NEWLY-DISCOVERED sub-themes specifically, once a
// "look inside Other" job is done - not the main report's `ThemeChartTabs.tsx` (that one shows the
// top-level KNOWN themes), though it reuses the exact same tab-switching pattern.
//
// No Arc chart fragment exists in `charts` (app/api_themes.py's own `_build_other_result_charts` never
// builds one) - the mockup's Arc view ("how often two themes are mentioned in the same answer") needs a
// multi-label co-occurrence signal this pipeline's hard clustering cannot produce for ANY theme set, new
// or known (the same structural reason the main report's own Arc tab was excluded, see SPEC.md/
// docs/DECISIONS.md). The Arc tab stays visible here - the user asked for "all 5 tabs" at the UI level -
// but renders an honest explanatory message instead of a fake chart, never invented arcs.
const TAB_ORDER: Array<{ id: string; label: string }> = [
  { id: 'othergrowth', label: 'Sankey' },
  { id: 'rank', label: 'Rank' },
  { id: 'icicle', label: 'Icicle' },
  { id: 'sentsun', label: 'Sunburst' },
]

export default function LookInsideOtherCharts({ charts }: { charts: Record<string, LookInsideOtherChart> }) {
  const available = TAB_ORDER.filter((t) => charts[t.id])
  const [active, setActive] = useState<string>(available[0]?.id ?? 'arc')

  if (available.length === 0) return null

  return (
    <div className="lio-charts">
      <div className="rp-tabs" role="tablist">
        {available.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={active === t.id}
            className={`rp-tab ${active === t.id ? 'active' : ''}`}
            onClick={() => setActive(t.id)}
          >
            {t.label}
          </button>
        ))}
        <button
          type="button"
          role="tab"
          aria-selected={active === 'arc'}
          className={`rp-tab ${active === 'arc' ? 'active' : ''}`}
          onClick={() => setActive('arc')}
        >
          Arc
        </button>
      </div>

      {active === 'arc' ? (
        <p className="lio-arc-note">
          Arc view isn't available here: it would need to know how often two themes are mentioned in the
          same answer, but each answer is matched to exactly one theme, known or new. There's no real
          co-occurrence to show.
        </p>
      ) : (
        <ThemeChart fragment={charts[active]} title={charts[active].chart_title} />
      )}
    </div>
  )
}
