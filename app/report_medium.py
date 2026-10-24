"""Stage 5 presentation adapter. Does not generate/rank findings or change stored headlines.

Every view is rebuilt from current (possibly filtered) ReportData. Eligibility starts with the shared
registry, plus renderer-shape checks that prevent empty/misaligned data from reaching old renderers.
"""
from __future__ import annotations

from dataclasses import replace
from collections import Counter
import math

from .chart_data import ReportData, ScoreBand, ScoreData
from .charts import TITLES, render_parts
from .charts_medium import group_mix_columns
from .cleaning.suppression import min_group_size
from .report_blocks import BY_SLUG

FLOW_NOTE = ('Flow widths are estimates from rounded group percentages. The tone end uses each theme\'s '
             'overall tone split; it does not trace individual answers through tone.')
GRID_NOTE = ('Cells use the existing theme-average sentiment estimate, not separately scored individual '
             'answers. Groups below the minimum size are withheld. This is an exploration, not an additional finding.')


def view(chart_id: str, data: ReportData, label: str, note: str = '') -> dict:
    if chart_id == 'icicle':
        # The gallery's legacy SVG scales its text down on phones. Reuse the live overview's fluid
        # HTML icicle instead; ordinary HTML labels keep readable font sizes and theme selection.
        from .charts import esc, fmt, hdr, icicle_html
        key = ''.join(
            f'<div data-theme="{esc(t.name)}" style="font-size:14px;overflow-wrap:anywhere">'
            f'<strong>{esc(t.name)}</strong><br>{t.share:g}% · {fmt(t.count)} answers</div>'
            for t in data.themes if t.count > 0
        )
        html = (f'<div style="padding:24px 16px">{hdr("Themes and sub-themes", "Themes above, sub-themes below. Labels retain their size on smaller screens.")}'
                f'<div style="margin-top:24px">{icicle_html(data, 358, 400)}</div>'
                f'<div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;margin-top:20px">{key}</div></div>')
        width, height = 390, 580 + 50 * math.ceil(len(data.themes) / 2)
    else:
        html, width, height = render_parts(chart_id, data)
    return {'chart_id': chart_id, 'chart_title': TITLES.get(chart_id, chart_id),
            'chart_label': label, 'chart_note': note, 'chart_html': html,
            'chart_width': width, 'chart_height': height}


def theme_views(data: ReportData) -> dict[str, dict]:
    result = {}
    for chart_id, slug, label in (
        ('icicle', 'theme_hierarchy_compact', 'Icicle'),
        ('sentsun', 'sentiment_sun', 'Sentiment sun'),
        ('rank', 'rank_by_tone', 'Rank'),
        ('diverge', 'tone_split', 'Tone split'),
        ('sunburst', 'theme_hierarchy', 'Sunburst'),
    ):
        if BY_SLUG[slug].needs(data):
            result[chart_id] = view(chart_id, data, label)
    if 'sunburst' in result and 'icicle' in result:
        result['sunburst']['compact_chart_id'] = 'icicle'
    return result


def valid_segment(data: ReportData) -> bool:
    groups = data.segment.groups
    return (2 <= len(groups) <= 20 and all(g.n >= min_group_size() for g in groups)
            and bool(group_mix_columns(data)))


def segment_flow_data(data: ReportData) -> ReportData | None:
    """Explicit group→score-band shape adapter. Missing theme rows become the named Other remainder.
    Never pass an empty score array to the existing Sankey renderer (which divides by its flow total).
    """
    if not valid_segment(data):
        return None
    by_theme = {row.theme: row for row in data.segment.rows}
    bands = []
    other_index = next((i for i, t in enumerate(data.themes) if t.color == 'other'), None)
    for j, group in enumerate(data.segment.groups):
        mix = [by_theme[t.name].values[j] if t.name in by_theme else 0.0 for t in data.themes]
        remainder = max(0.0, 100 - sum(mix))
        if remainder > 0.11 * len(mix):
            if other_index is None:
                return None  # cannot attribute undisplayed rows to a made-up real theme
            mix[other_index] += remainder
        if sum(mix) <= 0:
            return None
        sentiment = sum(t.sentiment * v for t, v in zip(data.themes, mix)) / sum(mix)
        bands.append(ScoreBand(group.label, mix, sentiment, group.n))
    return replace(data, score=ScoreData(data.segment.name, bands))


def valid_flow(data: ReportData) -> bool:
    n = len(data.themes)
    if sum(t.color != 'other' and t.count > 0 and t.share > 0 for t in data.themes) < 3 or len(data.score.bands) < 2:
        return False
    for band in data.score.bands:
        if band.answers < min_group_size() or len(band.mix) != n:
            return False
        if not all(math.isfinite(v) and 0 <= v <= 100 for v in band.mix):
            return False
        if not 0 < sum(band.mix) <= 100 + n * 0.11:
            return False
    return True


def valid_slope(data: ReportData) -> bool:
    labels, series = data.trend.labels, data.trend.series
    return (len(labels) >= 2 and bool(series)
            and all(len(s.values) == len(labels) and all(math.isfinite(v) and 0 <= v <= 100 for v in s.values)
                    for s in series))


def comparison_groups(data: ReportData, clean_df) -> ReportData:
    """Recover 8–20 group comparisons from the confirmed winning column, without changing the
    heatmap's eight-group cap, filters, candidate pool or Claude's structured producer.
    """
    from .findings_structured import build_segment_data

    name = data.segment.name
    if not name or name not in clean_df.columns:
        return data
    rows = {r for t in data.themes for r in t.answer_refs}
    raw = {}
    for r in rows:
        try:
            value = clean_df.at[r, name]
        except KeyError:
            continue
        if isinstance(value, str) and value.strip():
            raw[r] = value
    floor = max(100, min_group_size())
    counts = Counter(raw.values())
    eligible = {group for group, count in counts.items() if count >= floor}
    if not 8 <= len(eligible) <= 20:
        return data
    segment = build_segment_data(name, {r: v for r, v in raw.items() if v in eligible},
                                 data.themes, floor, heatmap_group_floor=floor, max_groups=20)
    return replace(data, segment=segment) if segment is not None else data


def complete_numeric_grid(data: ReportData, clean_df, columns: dict[str, list[str]]) -> ReportData:
    """Use the existing grid producer for the number+score case its original numeric-only loop skips.
    The row universe comes from the current filtered theme nodes, never raw demographic report rows.
    """
    from .findings_structured import build_binned_grid_data

    if safe_numeric_grid(data) is not None:
        return data
    rows = {r for t in data.themes for r in t.answer_refs}
    cache = {}

    def values(column):
        if column not in cache:
            raw = {}
            if column in clean_df.columns:
                for r in rows:
                    try:
                        value = float(clean_df.at[r, column])
                    except (KeyError, ValueError, TypeError):
                        continue
                    if math.isfinite(value):
                        raw[r] = value
            cache[column] = raw
        return cache[column]

    for number in columns.get('numeric', []):
        for score in columns.get('score', []):
            if number == score:
                continue
            grid = build_binned_grid_data(number, score, values(number), values(score), data.themes, min_group_size())
            candidate = replace(data, binned_grid=grid) if grid is not None else None
            if candidate is not None and safe_numeric_grid(candidate) is not None:
                return candidate
    return data


def finding_views(data: ReportData, kind: str, theme_name: str, comparisons: ReportData | None = None) -> dict[str, dict]:
    result = {}
    if kind == 'score_correlation' and BY_SLUG['theme_flow'].needs(data) and valid_flow(data):
        result['sankey'] = view('sankey', data, 'Theme flow', FLOW_NOTE)
    if kind == 'segment_skew' and valid_segment(data):
        result['groupMix'] = view('groupMix', data, 'Group size and mix')
        if BY_SLUG['group_split_bars'].needs(data):
            result['groupSplitBars'] = view('groupSplitBars', data, 'Two groups')
        compare_data = comparisons or data
        if BY_SLUG['compare_dots'].needs(compare_data) and valid_segment(compare_data):
            selected_row = next((r for r in compare_data.segment.rows if r.theme == theme_name), None)
            if selected_row is not None:
                segment = replace(compare_data.segment, rows=[selected_row] + [r for r in compare_data.segment.rows if r is not selected_row])
                result['compareDots'] = view('compareDots', replace(compare_data, segment=segment), 'Compare groups')
        flow_data = segment_flow_data(data)
        if flow_data is not None and BY_SLUG['theme_flow'].needs(flow_data) and valid_flow(flow_data):
            result['sankey'] = view('sankey', flow_data, 'Theme flow', FLOW_NOTE)
    if kind == 'trend_shift' and BY_SLUG['slope_change'].needs(data) and valid_slope(data):
        result['slopeChange'] = view('slopeChange', data, 'First vs last')
    return result


def safe_numeric_grid(data: ReportData) -> ReportData | None:
    grid = data.binned_grid
    if not BY_SLUG['binned_grid'].needs(data) or not grid.row_name or not grid.col_name or grid.row_name == grid.col_name:
        return None
    cells = [c for c in grid.cells if c.count >= min_group_size()
             and c.row_label in grid.row_labels and c.col_label in grid.col_labels
             and math.isfinite(c.sentiment)]
    if len({c.row_label for c in cells}) < 2 or len({c.col_label for c in cells}) < 2:
        return None
    # Defensive suppression: the renderer must not expose smaller cells passed by an older producer.
    kept = {(c.row_label, c.col_label) for c in cells}
    safe = replace(grid, cells=[c if (c.row_label, c.col_label) in kept else replace(c, count=0, sentiment=0.0)
                               for c in grid.cells])
    return replace(data, binned_grid=safe)


def numeric_explorations(data: ReportData) -> list[dict]:
    safe_data = safe_numeric_grid(data)
    if safe_data is None:
        return []
    grid = safe_data.binned_grid
    chart = view('binnedGrid', safe_data, f'{grid.row_name} and {grid.col_name}', GRID_NOTE)
    return [chart]
