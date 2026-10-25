from copy import deepcopy
from dataclasses import replace

import pytest

from app.charts import render_report_parts
from app.fixtures.ev_sample import EV
from app.report_focus import focus_finding, reveal_folded_theme
from app.report_medium import finding_views


def test_same_kind_charts_show_their_own_theme_without_mutating_the_overview():
    data = deepcopy(EV)
    before = deepcopy(data)
    for kind, chart in [('segment_skew', 'heatmap'), ('score_correlation', 'byScore'),
                        ('trend_shift', 'themeMixOverTime'), ('trend_shift', 'trend')]:
        a = focus_finding(data, kind, 'Cost', chart_id=chart)
        b = focus_finding(data, kind, 'Charging', chart_id=chart)
        assert a is not None and b is not None
        assert render_report_parts(chart, a)[0] != render_report_parts(chart, b)[0]
    assert data == before


def test_score_focus_preserves_band_sizes_and_percent_denominators():
    focused = focus_finding(EV, 'score_correlation', 'Charging')
    assert [n.name for n in focused.themes] == ['Charging', 'All other answers']
    for original, band in zip(EV.score.bands, focused.score.bands):
        assert band.mix[0] == original.mix[1]
        assert sum(band.mix) == 100
        assert (band.answers, band.sentiment) == (original.answers, original.sentiment)


def test_same_theme_different_group_highlights_the_actual_finding_cell():
    a = focus_finding(EV, 'segment_skew', 'Cost', '18-24')
    b = focus_finding(EV, 'segment_skew', 'Cost', '65+')
    assert a.segment.highlight == (0, 0)
    assert b.segment.highlight == (0, 5)
    assert '40%' in a.segment.highlight_text and '20%' in b.segment.highlight_text
    assert render_report_parts('heatmap', a)[0] != render_report_parts('heatmap', b)[0]


def test_trend_focus_retains_actual_shares_and_explicit_remainder():
    data = focus_finding(EV, 'trend_shift', 'Charging', chart_id='themeMixOverTime')
    assert len(data.trend.series) == 2
    assert data.trend.series[0] == EV.trend.series[1]
    assert [a + b for a, b in zip(*(s.values for s in data.trend.series))] == pytest.approx([100] * len(data.trend.labels))
    line = focus_finding(EV, 'trend_shift', 'Charging', chart_id='trend')
    assert len(line.trend.series) == 1


def test_filters_cannot_substitute_an_unrelated_theme_or_group():
    assert focus_finding(EV, 'segment_skew', 'Cost', 'Not present') is None
    assert focus_finding(EV, 'score_correlation', 'Not present') is None
    missing = replace(EV, trend=replace(EV.trend, series=[]))
    assert focus_finding(missing, 'trend_shift', 'Cost') is None


def test_specific_alternates_focus_evidence_and_broader_views_are_labeled():
    focused = focus_finding(EV, 'trend_shift', 'Charging')
    slope = finding_views(EV, 'trend_shift', 'Charging', focused=focused)['slopeChange']
    assert 'Charging' in slope['chart_html']
    assert 'Cost' not in slope['chart_html']
    flow = finding_views(EV, 'score_correlation', 'Charging')['sankey']
    assert flow['chart_label'].startswith('All themes:')
    assert 'context' in flow['chart_note']


def test_revealing_a_folded_theme_preserves_counts_and_weighted_tone():
    # Treat Charging as folded away: reconstruction must not add it to the total a second time.
    data = deepcopy(EV)
    before = deepcopy(data)
    node = data.themes[1]
    focused = reveal_folded_theme(data, node)
    assert focused.selected_theme == 'Charging'
    assert sum(t.count for t in focused.themes) == sum(t.count for t in data.themes)
    for i in range(3):
        assert sum(t.count * t.tones[i] for t in focused.themes) == pytest.approx(
            sum(t.count * t.tones[i] for t in data.themes), rel=1e-3)
    # Printed as labels, so one decimal like every stored theme (BUG-054).
    assert all(v == round(v, 1) for t in focused.themes for v in t.tones)
    assert data == before
