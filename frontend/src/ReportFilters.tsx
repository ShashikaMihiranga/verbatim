import type { ReportFilterOptions, ReportFilters as ReportFiltersValue } from './reportApi'

// Filters feature (SPEC.md section 5: "a global filter (segment, score band, date range) recomputes
// every block from cached cross-tabs"). Purely controlled: no fetch of its own - the parent (Themes.tsx)
// owns `value`/`onChange` and re-fetches the whole report whenever `onChange` fires, the same way every
// other report control in this app works. Each control renders only when its own `options.*` field is
// non-null (the backend only ever offers values that already survived suppression - see
// `ReportFilterOptions`'s own comment), so a dataset with no usable segment/score/date column renders
// nothing here at all.
export default function ReportFilters({
  options,
  value,
  onChange,
}: {
  options: ReportFilterOptions
  value: ReportFiltersValue
  onChange: (next: ReportFiltersValue) => void
}) {
  const hasAnyOption = options.segment || options.score_band || options.date_range
  if (!hasAnyOption) return null

  const hasActiveFilter = Boolean(value.segment || value.scoreBand || value.dateFrom || value.dateTo)

  return (
    <div className="rp-filters">
      {options.segment && (
        <select
          className="rp-filter-select"
          aria-label={`Filter by ${options.segment.column}`}
          value={value.segment ?? ''}
          onChange={(e) => onChange({ ...value, segment: e.target.value || undefined })}
        >
          <option value="">All {options.segment.column}</option>
          {options.segment.groups.map((g) => (
            <option key={g} value={g}>{g}</option>
          ))}
        </select>
      )}

      {options.score_band && (
        <select
          className="rp-filter-select"
          aria-label={`Filter by ${options.score_band.column}`}
          value={value.scoreBand ?? ''}
          onChange={(e) => onChange({ ...value, scoreBand: e.target.value || undefined })}
        >
          <option value="">All {options.score_band.column}</option>
          {options.score_band.bands.map((b) => (
            <option key={b} value={b}>{b}</option>
          ))}
        </select>
      )}

      {options.date_range && (
        <>
          <input
            type="date"
            className="rp-filter-date"
            aria-label={`${options.date_range.column} from`}
            min={options.date_range.min}
            max={options.date_range.max}
            value={value.dateFrom ?? ''}
            onChange={(e) => onChange({ ...value, dateFrom: e.target.value || undefined })}
          />
          <input
            type="date"
            className="rp-filter-date"
            aria-label={`${options.date_range.column} to`}
            min={options.date_range.min}
            max={options.date_range.max}
            value={value.dateTo ?? ''}
            onChange={(e) => onChange({ ...value, dateTo: e.target.value || undefined })}
          />
        </>
      )}

      {hasActiveFilter && (
        <button type="button" className="btn quiet" onClick={() => onChange({})}>
          Clear filters
        </button>
      )}
    </div>
  )
}
