import { useId, useState } from 'react'
import type { KeyboardEvent } from 'react'
import type { ReportBlock, ReportThemeChartVariant } from './reportApi'
import ThemeChart from './ThemeChart'

type Fragment = Pick<ReportThemeChartVariant, 'chart_html' | 'chart_width' | 'chart_height' | 'chart_id'>

export function ResponsiveChart({ fragment, compact, title, selectedTheme, onThemeSelect, finding = false }: {
  fragment: Fragment
  compact?: Fragment
  title: string
  selectedTheme?: string | null
  onThemeSelect?: (name: string) => void
  finding?: boolean
}) {
  if (!compact) return <ThemeChart fragment={fragment} title={title} selectedTheme={selectedTheme} onThemeSelect={onThemeSelect} finding={finding} />
  return (
    <div className="rp-responsive-chart">
      <div className="rp-chart-desktop"><ThemeChart fragment={fragment} title={title} selectedTheme={selectedTheme} onThemeSelect={onThemeSelect} finding={finding} /></div>
      <div className="rp-chart-compact"><ThemeChart fragment={compact} title={`${title}, compact`} selectedTheme={selectedTheme} onThemeSelect={onThemeSelect} finding={finding} /></div>
    </div>
  )
}

const LABELS: Record<string, string> = { heatmap: 'Heatmap', byScore: 'Score groups', trend: 'Over time' }

export default function FindingChartTabs({ block, selectedTheme }: { block: ReportBlock; selectedTheme?: string | null }) {
  const id = useId()
  const [requested, setRequested] = useState(block.chart_id)
  const options = [
    { key: block.chart_id, label: LABELS[block.chart_id] ?? block.chart_title, fragment: block },
    ...Object.entries(block.chart_variants ?? {}).filter(([key]) => key !== block.chart_id).map(([key, fragment]) => ({
      key, label: fragment.chart_label ?? fragment.chart_title, fragment,
    })),
  ]
  // A filter can remove the active view. Derive a safe fallback immediately; do not render stale HTML.
  const selected = options.find((option) => option.key === requested) ?? options[0]
  const note = 'chart_note' in selected.fragment ? selected.fragment.chart_note : undefined
  const compact = selected.fragment.compact_chart_id ? block.chart_variants?.[selected.fragment.compact_chart_id] : undefined

  function navigate(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    const keys = ['ArrowLeft', 'ArrowRight', 'Home', 'End']
    if (!keys.includes(event.key)) return
    event.preventDefault()
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? options.length - 1
      : (index + (event.key === 'ArrowRight' ? 1 : -1) + options.length) % options.length
    setRequested(options[next].key)
    const buttons = event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]')
    buttons?.[next]?.focus()
  }

  if (options.length === 1) return <ThemeChart fragment={block} title={block.chart_title} selectedTheme={selectedTheme} finding />
  return (
    <div>
      <div className="rp-tabs" role="tablist" aria-label="Ways to view this finding">
        {options.map((option, index) => (
          <button type="button" role="tab" key={option.key} id={`${id}-${option.key}`}
            aria-selected={selected.key === option.key} aria-controls={`${id}-panel`}
            tabIndex={selected.key === option.key ? 0 : -1}
            className={`rp-tab ${selected.key === option.key ? 'active' : ''}`}
            onClick={() => setRequested(option.key)} onKeyDown={(event) => navigate(event, index)}>
            {option.label}
          </button>
        ))}
      </div>
      <div id={`${id}-panel`} role="tabpanel" aria-labelledby={`${id}-${selected.key}`}>
        {typeof note === 'string' && note && <p className="rp-method-note">{note}</p>}
        <ResponsiveChart fragment={selected.fragment} compact={compact} title={selected.fragment.chart_title} selectedTheme={selectedTheme} finding />
      </div>
    </div>
  )
}
