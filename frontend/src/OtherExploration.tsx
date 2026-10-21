import { useState } from 'react'
import type { ReportOtherBreakdown, ReportThemeSummary } from './reportApi'

// "Other" exploration (docs/TODO.md, 2026-10-21 Phase 1 - design discussion the same day). Root cause:
// the treemap above can only ever show 7 themes (app/charts.py's fixed 7-colour palette) - on a
// topic-rich dataset, real themes ranked 8th+ fold into "Other" alongside genuine HDBSCAN noise, and the
// resulting number can look alarmingly high even though most of it is real, findable content. This
// section only appears once that share crosses a real threshold, and exists purely to make the full
// picture visible - it never changes what the treemap above renders.
const OTHER_CALLOUT_THRESHOLD = 30 // % of answered responses

// Same absolute thresholds app/api_report.py's own summary line already uses to call a report's overall
// tone "positive"/"negative"/"mixed" - not a new arbitrary cutoff. Simpler than app/charts.py's
// relative-to-overall-sentiment `tone()` colour mix used by the primary charts: appropriate for this
// lighter-weight secondary list, not the report's main chart.
function toneColor(sentiment: number): string {
  if (sentiment >= 0.05) return 'var(--pos)'
  if (sentiment <= -0.05) return 'var(--neg)'
  return 'var(--neu)'
}

export default function OtherExploration({
  breakdown,
  allThemes,
}: {
  breakdown: ReportOtherBreakdown | null
  allThemes: ReportThemeSummary[]
}) {
  const [expanded, setExpanded] = useState(false)

  if (!breakdown) return null
  const otherShare = Math.round((breakdown.noise_share + breakdown.hidden_real_share) * 10) / 10
  if (otherShare < OTHER_CALLOUT_THRESHOLD) return null

  const shownThemeCount = breakdown.total_real_theme_count - breakdown.hidden_real_theme_count
  const maxShare = Math.max(...allThemes.map((t) => t.share), 1)

  return (
    <div className="rp-section">
      <div className="rp-other-callout">
        {otherShare}% of answers aren't in the {shownThemeCount} theme{shownThemeCount === 1 ? '' : 's'} shown above.
      </div>
      <div className="rp-other-note">
        We found {breakdown.total_real_theme_count} distinct topic{breakdown.total_real_theme_count === 1 ? '' : 's'} in
        total - the chart above can only show {shownThemeCount} clearly.
      </div>

      <div className="rp-other-stats">
        <div className="rp-other-stat">
          <div className="rp-other-stat-n">{breakdown.noise_share}%</div>
          <div className="rp-other-stat-l">Genuinely varied answers</div>
          <div className="rp-other-stat-note">These don't repeat often enough to group.</div>
        </div>
        <div className="rp-other-stat">
          <div className="rp-other-stat-n">{breakdown.hidden_real_share}%</div>
          <div className="rp-other-stat-l">More real themes</div>
          <div className="rp-other-stat-note">
            {breakdown.hidden_real_theme_count} more topic{breakdown.hidden_real_theme_count === 1 ? '' : 's'} not shown above.
          </div>
        </div>
      </div>

      {allThemes.length > 0 && (
        <>
          <button type="button" className="btn quiet rp-other-toggle" onClick={() => setExpanded(!expanded)}>
            {expanded ? 'Hide all themes' : `See all ${allThemes.length} themes`}
          </button>

          {expanded && (
            <div className="rp-other-list">
              {allThemes.map((t) => (
                <div className="rp-other-row" key={t.name}>
                  <div className="rp-other-row-name">{t.name}</div>
                  <div className="rp-other-row-bar-wrap">
                    <div
                      className="rp-other-row-bar"
                      style={{ width: `${(t.share / maxShare) * 100}%`, background: toneColor(t.sentiment) }}
                    />
                  </div>
                  <div className="rp-other-row-stats">
                    <span className="rp-other-row-share">{t.share}%</span>
                    <span className="rp-other-row-count">{t.count.toLocaleString()}</span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
