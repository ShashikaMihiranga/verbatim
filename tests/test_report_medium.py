from copy import deepcopy
from dataclasses import replace

import pandas as pd
from app.chart_data import BinCell, BinnedGridData, ScoreBand, ScoreData, SegmentData, SegmentGroup, SegmentRow
from app.charts import render_parts
from app.charts_medium import group_mix_columns
from app.fixtures.ev_sample import EV
from app.report_medium import (
    comparison_groups, complete_numeric_grid, finding_views, numeric_explorations, segment_flow_data,
    theme_views,
)


def data(groups=2):
    report = deepcopy(EV)
    report.themes = report.themes[:3]
    for t in report.themes:
        t.answer_refs = []
    report.segment = SegmentData('Customer type', [SegmentGroup(f'Group {i}', 120) for i in range(groups)], [
        SegmentRow(report.themes[0].name, 50, [50.0] * groups),
        SegmentRow(report.themes[1].name, 30, [30.0] * groups),
        SegmentRow(report.themes[2].name, 20, [20.0] * groups),
    ])
    report.score = ScoreData('Rating', [ScoreBand('Low', [60, 30, 10], -0.2, 120),
                                      ScoreBand('High', [40, 30, 30], -0.1, 120)])
    return report


def test_thin_hierarchy_tabs_are_not_exposed_and_rich_hierarchy_has_compact_pair():
    report = data()
    views = theme_views(report)
    assert views['sunburst']['compact_chart_id'] == 'icicle'
    # One fragment carries both layouts; a container query shows the wide one at desktop widths (it used to
    # be the 390px compact layout everywhere, a small column on a wide page) and the compact one on phones.
    html = views['icicle']['chart_html']
    assert views['icicle']['chart_width'] == 1180
    assert 'vb-icicle-wide' in html and 'vb-icicle-compact' in html and '@container vbicicle (min-width:640px)' in html
    assert 'font-size:14px' in html  # compact key keeps readable labels
    for t in report.themes:
        t.children = []
    assert 'sunburst' not in theme_views(report)
    assert 'icicle' not in theme_views(report)


def test_segment_finding_exposes_real_mix_split_and_segment_only_flow_without_mutation():
    report = data()
    report.score = ScoreData('', [])
    before = deepcopy(report)
    views = finding_views(report, 'segment_skew', report.themes[0].name)
    assert {'groupMix', 'groupSplitBars', 'sankey'} <= views.keys()
    assert 'Customer type' in views['sankey']['chart_html']
    assert 'estimates' in views['sankey']['chart_note']
    assert report == before


def test_score_flow_requires_three_real_themes_and_nonempty_aligned_bands():
    report = data()
    assert 'sankey' in finding_views(report, 'score_correlation', 'Cost')
    report.score.bands[0].mix = []
    assert finding_views(report, 'score_correlation', 'Cost') == {}
    report = data()
    report.themes = report.themes[:2]
    assert finding_views(report, 'score_correlation', 'Cost') == {}


def test_empty_flow_does_not_divide_by_zero_even_for_gallery_callers():
    report = data()
    report.score = ScoreData('', [])
    html, _, _ = render_parts('sankey', report)
    assert 'No eligible grouped answers' in html


def test_compare_dots_follows_finding_theme_not_the_largest_theme():
    report = data(groups=8)
    wanted = report.themes[1].name
    view = finding_views(report, 'segment_skew', wanted)['compareDots']
    assert f'{wanted}, by group' in view['chart_html']
    assert report.segment.rows[0].theme != wanted
    assert 'compareDots' not in finding_views(report, 'segment_skew', 'A theme absent from this chart')


def test_comparison_adapter_can_recover_twelve_groups_without_changing_heatmap_cap():
    report = data(groups=8)
    n = 1440
    report.themes[0].answer_refs = list(range(n))
    frame = pd.DataFrame({'Customer type': [f'Group {r // 120}' for r in range(n)]})
    expanded = comparison_groups(report, frame)
    assert len(expanded.segment.groups) == 12
    assert len(report.segment.groups) == 8
    assert 'compareDots' in finding_views(report, 'segment_skew', report.themes[0].name, expanded)
    # A filtered universe with fewer surviving groups cannot keep the full-dataset comparison.
    filtered = replace(report, themes=[replace(report.themes[0], answer_refs=list(range(120)))])
    assert comparison_groups(filtered, frame) is filtered


def test_group_mix_area_uses_actual_group_counts_and_prints_residual_without_invented_counts():
    report = data()
    report.segment.groups[0].n = 240
    report.segment.rows = report.segment.rows[:2]
    cols = group_mix_columns(report)
    assert cols[0]['n'] == 240
    assert cols[0]['entries'][-1] == ('Other / not shown', 20.0, 'other')
    html, _, _ = render_parts('groupMix', report)
    assert 'flex:240 1 0' in html and 'flex:120 1 0' in html
    assert '66.7%' in html and '33.3%' in html
    assert 'Other / not shown' in html


def test_group_mix_labels_are_escaped():
    report = data()
    report.segment.groups[0].label = '<script>alert(1)</script>'
    report.segment.rows[0].theme = 'bad" onmouseover="alert(1)'
    html = render_parts('groupMix', report)[0]
    assert '<script>' not in html and 'onmouseover="alert' not in html
    assert '&lt;script&gt;' in html and '&quot;' in html


def test_flow_with_many_groups_keeps_nonnegative_node_coordinates():
    report = segment_flow_data(data(groups=12))
    assert report is not None
    from html.parser import HTMLParser
    class Rects(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag == 'rect':
                values = dict(attrs)
                assert float(values.get('y', 0)) >= 0
                assert float(values.get('height', 0)) >= 0
    Rects().feed(render_parts('sankey', report)[0])


def test_slope_view_requires_real_aligned_endpoints():
    report = data()
    assert 'slopeChange' in finding_views(report, 'trend_shift', 'Cost')
    report.trend.series[0].values = []
    assert 'slopeChange' not in finding_views(report, 'trend_shift', 'Cost')


def grid_report():
    report = data()
    report.binned_grid = BinnedGridData('Age', 'Spend', ['Young', 'Old'], ['Low', 'High'], [
        BinCell('Young', 'Low', 80, -0.2), BinCell('Young', 'High', 1, 0.987654),
        BinCell('Old', 'Low', 1, 0.987654), BinCell('Old', 'High', 80, 0.2),
    ])
    return report


def test_numeric_grid_is_an_explicit_exploration_and_suppresses_small_cells():
    report = grid_report()
    charts = numeric_explorations(report)
    assert len(charts) == 1
    assert 'not separately scored' in charts[0]['chart_note']
    assert 'not an additional finding' in charts[0]['chart_note']
    assert '0.99' not in charts[0]['chart_html']
    assert report.binned_grid.cells[1].count == 1  # never mutate shared input


def test_numeric_grid_with_no_surviving_two_axis_comparison_is_omitted():
    report = grid_report()
    for c in report.binned_grid.cells:
        c.count = 0
    assert numeric_explorations(report) == []


def test_numeric_plus_score_uses_existing_grid_producer_and_current_answer_rows():
    report = data()
    report.binned_grid = BinnedGridData('', '', [], [], [])
    # Two themes with different tone (-0.05 / -0.20) split unevenly across Spend, so cells really differ;
    # with one theme every cell has the same tone and the grid is (correctly) withheld as flat.
    report.themes[0].answer_refs = [r for r in range(240) if r % 4 < 3]
    report.themes[1].answer_refs = [r for r in range(240) if r % 4 == 3]
    frame = pd.DataFrame({'Spend': [float(r % 4) for r in range(240)],
                          'Rating': [float((r // 4) % 2 * 10) for r in range(240)]})
    enriched = complete_numeric_grid(report, frame, {'numeric': ['Spend'], 'score': ['Rating']})
    assert enriched.binned_grid.row_name == 'Spend'
    assert enriched.binned_grid.col_name == 'Rating'
    assert numeric_explorations(enriched)
    assert report.binned_grid.cells == []
    only_one_value = replace(report, themes=[replace(t, answer_refs=[r for r in t.answer_refs if frame.at[r, 'Rating'] == 0])
                                             for t in report.themes])
    assert complete_numeric_grid(only_one_value, frame, {'numeric': ['Spend'], 'score': ['Rating']}) is only_one_value


def test_no_alternatives_are_attached_to_unrelated_finding_kinds():
    assert finding_views(data(), 'tone_contrast', 'Cost') == {}


def test_a_grid_whose_cells_all_read_about_the_same_is_not_shown():
    # Found live on dataset 11: every cell read +0.50 to +0.52, so the grid told the reader nothing.
    report = data()
    report.binned_grid = BinnedGridData('Spend', 'Rating', ['Low', 'High'], ['Low', 'High'], [
        BinCell(r, c, 200, 0.51) for r in ('Low', 'High') for c in ('Low', 'High')
    ])
    assert numeric_explorations(report) == []
    report.binned_grid.cells[0] = BinCell('Low', 'Low', 200, 0.30)
    assert numeric_explorations(report)


def test_identifier_columns_are_never_used_as_numbers():
    from app.findings_structured import looks_like_identifier

    assert all(looks_like_identifier(n) for n in ('Clothing_ID', 'customer id', 'orderId', 'SKU', 'ID'))
    assert not any(looks_like_identifier(n) for n in ('Age', 'Rating', 'Paid', 'Liquid', 'Valid', 'Width'))
