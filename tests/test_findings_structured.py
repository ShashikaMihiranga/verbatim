"""app/findings_structured.py: Part B1 (banding foundation, pure functions - see the top half of this file)
plus Part B2 (cross-tab + data plumbing - the bottom half, below). B1's tests need no mocking (no DB, no
pandas input). B2's cross-tab functions take plain dicts/lists so most of them stay just as mock-free; only
`pick_structured_columns` needs a real (in-memory sqlite) DB session, matching tests/test_findings.py's own
`session` fixture pattern."""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.chart_data import ScoreBand, ScoreData, SegmentData, SegmentGroup, SegmentRow, TrendData, TrendSeries
from app.charts import render_parts
from app.cleaning.models import CleaningPlan, Step
from app.db import Base
from app.findings import MAX_CANDIDATES, Candidate, build_report_data, candidate_findings, label_confidence, theme_nodes
from app.findings_structured import (
    Band,
    StructuredContext,
    apply_bands,
    band_age,
    band_dates,
    band_quartiles,
    band_score,
    build_binned_grid_data,
    build_category_avg_data,
    build_frequency_data,
    build_group_trend_data,
    build_numeric_data,
    build_score_data,
    build_segment_data,
    build_structured_context,
    build_trend_data,
    pick_structured_columns,
    resolve_filter_rows,
    score_correlation_candidates,
    segment_cell_tests,
    segment_skew_candidates,
    theme_answer_rows,
    trend_shift_candidates,
)
from app.models import Column, Dataset, Theme


# ==================================================================== band_score

def test_band_score_zero_to_ten_matches_ev_sample_convention():
    # app/fixtures/ev_sample.py's ScoreData uses exactly these three labels for a 0-10 scale.
    bands = band_score((0, 10))
    assert [b.label for b in bands] == ["Low (0-6)", "Middle (7-8)", "High (9-10)"]
    assert [(b.lo, b.hi) for b in bands] == [(0, 6), (7, 8), (9, 10)]


def test_band_score_one_to_five_three_band_split():
    bands = band_score((1, 5))
    assert [b.label for b in bands] == ["Low (1-2)", "Middle (3)", "High (4-5)"]
    assert [(b.lo, b.hi) for b in bands] == [(1, 2), (3, 3), (4, 5)]


def test_band_score_one_to_seven_three_band_split():
    bands = band_score((1, 7))
    assert [b.label for b in bands] == ["Low (1-3)", "Middle (4-5)", "High (6-7)"]
    assert [(b.lo, b.hi) for b in bands] == [(1, 3), (4, 5), (6, 7)]


def test_band_score_narrow_scale_two_band_fallback():
    bands = band_score((1, 2))
    assert len(bands) == 2
    assert [b.label for b in bands] == ["Low (1)", "High (2)"]
    assert [(b.lo, b.hi) for b in bands] == [(1, 1), (2, 2)]


@pytest.mark.parametrize("scale", [(0, 10), (1, 5), (1, 7), (1, 2), (0, 4), (2, 9)])
def test_band_score_every_value_in_range_maps_to_exactly_one_band(scale):
    lo, hi = scale
    bands = band_score(scale)
    # every band is real-valued on both ends - a score scale is always bounded
    assert all(b.lo is not None and b.hi is not None for b in bands)
    for v in range(lo, hi + 1):
        matches = [b for b in bands if b.lo <= v <= b.hi]
        assert len(matches) == 1, f"value {v} matched {len(matches)} bands for scale {scale}"


# ==================================================================== band_age

def test_band_age_standard_case_six_bands_open_above():
    bands = band_age(18, 80)
    assert [b.label for b in bands] == ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]
    assert bands[-1].lo == 65
    assert bands[-1].hi is None  # open above


def test_band_age_includes_under_18_band_when_min_below_18():
    bands = band_age(13, 70)
    assert bands[0].label == "<18"
    assert bands[0].lo is None  # open below
    assert bands[0].hi == 17
    assert [b.label for b in bands[1:]] == ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]


def test_band_age_excludes_under_18_band_when_min_at_least_18():
    bands = band_age(18, 70)
    assert bands[0].label == "18-24"
    assert all(b.label != "<18" for b in bands)


# ==================================================================== band_quartiles

def test_band_quartiles_normal_spread_four_real_valued_bands():
    values = list(range(1, 101))  # 1..100, plenty of spread, no repeated-value collapse
    bands = band_quartiles(values)
    assert len(bands) == 4
    assert bands[0].lo == 1
    assert bands[-1].hi == 100
    # bounds are contiguous and real-valued throughout
    for a, b in zip(bands, bands[1:]):
        assert a.hi == b.lo
    labels = [b.label for b in bands]
    assert len(set(labels)) == 4  # no duplicate labels


def test_band_quartiles_currency_unit_prefixes_dollar_sign():
    values = [20000, 25000, 30000, 35000, 40000, 45000, 50000, 60000, 70000, 90000]
    bands = band_quartiles(values, unit="currency")
    assert len(bands) == 4
    assert all(b.label.startswith("$") for b in bands)
    assert "," in bands[-1].label or bands[-1].hi < 1000  # comma-grouped for large values


def test_band_quartiles_degenerate_repeated_values_falls_back_to_two_bands():
    # 90 respondents report exactly 10, 10 report 20 - real quartile cuts collapse to a single point.
    values = [10] * 90 + [20] * 10
    bands = band_quartiles(values)
    assert len(bands) == 2
    labels = [b.label for b in bands]
    assert len(set(labels)) == 2  # no duplicate labels
    for b in bands:
        assert b.lo <= b.hi  # never an empty/inverted range
    assert bands[0].lo == 10
    assert bands[-1].hi == 20


def test_band_quartiles_raises_on_fewer_than_two_distinct_values():
    with pytest.raises(ValueError):
        band_quartiles([42, 42, 42])
    with pytest.raises(ValueError):
        band_quartiles([7])


# ==================================================================== band_dates

def test_band_dates_multi_month_span_picks_monthly_granularity():
    values = [date(2026, 1, 5), date(2026, 2, 14), date(2026, 3, 1), date(2026, 4, 20)]
    bands, note = band_dates(values)
    assert len(bands) == 4  # Jan, Feb, Mar, Apr
    assert [b.label for b in bands] == ["Jan", "Feb", "Mar", "Apr"]
    assert note == "Monthly, January to April."
    # every band is bounded on both ends and stored as real ordinals
    assert all(b.lo is not None and b.hi is not None for b in bands)


def test_band_dates_month_span_crossing_years_includes_year_in_labels():
    values = [date(2025, 11, 1), date(2025, 12, 15), date(2026, 1, 1), date(2026, 2, 10)]
    bands, note = band_dates(values)
    assert [b.label for b in bands] == ["Nov 2025", "Dec 2025", "Jan 2026", "Feb 2026"]
    assert note == "Monthly, November 2025 to February 2026."


def test_band_dates_few_weeks_span_picks_weekly_granularity():
    # all within the same calendar month, so monthly would only yield 1 period - too coarse.
    values = [date(2026, 1, 1), date(2026, 1, 8), date(2026, 1, 15), date(2026, 1, 20)]
    bands, note = band_dates(values)
    assert len(bands) >= 3
    assert note.startswith("Weekly,")
    # each weekly band spans 7 days (Monday to Sunday, inclusive ordinals)
    for b in bands:
        assert b.hi - b.lo == 6


def test_band_dates_raises_when_all_dates_are_identical():
    with pytest.raises(ValueError):
        band_dates([date(2026, 1, 1)] * 5)


def test_band_dates_raises_when_span_too_short_even_for_daily():
    # 2 distinct dates, one day apart, both in the same week and month - not enough for even 3 daily periods.
    with pytest.raises(ValueError):
        band_dates([date(2026, 1, 1), date(2026, 1, 2)])


# ==================================================================== apply_bands

def test_apply_bands_value_inside_band_maps_correctly():
    bands = band_score((0, 10))
    result = apply_bands({1: 3, 2: 7, 3: 10}, bands)
    assert result == {1: "Low (0-6)", 2: "Middle (7-8)", 3: "High (9-10)"}


def test_apply_bands_value_outside_every_band_is_omitted():
    bands = band_age(18, 80)  # bounded 18-65+, nothing below 18
    result = apply_bands({1: 12, 2: 30}, bands)
    assert 1 not in result
    assert result[2] == "25-34"


def test_apply_bands_missing_value_is_omitted():
    bands = band_score((0, 10))
    result = apply_bands({1: None, 2: float("nan"), 3: 5}, bands)
    assert set(result) == {3}
    assert result[3] == "Low (0-6)"


def test_apply_bands_multiple_rows_map_correctly_in_one_call():
    bands = band_score((0, 10))
    raw = {i: v for i, v in enumerate([0, 6, 7, 8, 9, 10, 2, None])}
    result = apply_bands(raw, bands)
    assert result == {0: "Low (0-6)", 1: "Low (0-6)", 2: "Middle (7-8)", 3: "Middle (7-8)",
                       4: "High (9-10)", 5: "High (9-10)", 6: "Low (0-6)"}
    assert 7 not in result  # the None value


def test_apply_bands_open_ended_band_matches_unbounded_side():
    bands = band_age(18, 80)
    result = apply_bands({1: 90, 2: 65}, bands)
    assert result[1] == "65+"
    assert result[2] == "65+"


# ==================================================================== B2 - cross-tab + data plumbing

def make_theme(label, size, sentiment, answer_refs, column_name="Why", dataset_id=1):
    return Theme(
        dataset_id=dataset_id, column_name=column_name, label=label, description=None,
        size=size, sentiment=sentiment, tone={"neg": 34.0, "neu": 33.0, "pos": 33.0}, answer_refs=answer_refs,
    )


def abc_themes():
    """Three themes (two real, one "Other") whose `answer_refs` cover rows 0-9 with no overlaps and no
    gaps - the shared fixture every B2 cross-tab test below builds its raw column values against."""
    return [
        make_theme("A", 4, 0.5, [0, 1, 2, 3]),
        make_theme("B", 4, -0.5, [4, 5, 6, 7]),
        make_theme("Other", 2, 0.0, [8, 9]),
    ]


# -------------------------------------------------------------------- theme_answer_rows

def test_theme_answer_rows_unions_and_sorts_every_themes_refs():
    themes = abc_themes()
    assert theme_answer_rows(themes) == list(range(10))


def test_theme_answer_rows_deduplicates_and_ignores_none():
    t1 = make_theme("A", 2, 0.0, [3, 1])
    t2 = make_theme("B", 1, 0.0, [1, 2])
    t3 = make_theme("Other", 0, 0.0, None)
    assert theme_answer_rows([t1, t2, t3]) == [1, 2, 3]


# -------------------------------------------------------------------- build_score_data

def test_build_score_data_hand_computable_mix_sentiment_and_answers():
    themes = abc_themes()
    nodes = theme_nodes(themes, total_answered=10)
    assert [n.name for n in nodes] == ["A", "B", "Other"]

    # scale (0, 10) -> Low(0-6)/Middle(7-8)/High(9-10). Row->raw score value:
    raw_by_row = {
        0: 3, 1: 4, 2: 9, 3: 9,   # A: Low, Low, High, High
        4: 2, 5: 7, 6: 8, 7: 9,   # B: Low, Middle, Middle, High
        8: 5, 9: 10,              # Other: Low, High
    }
    data = build_score_data("Score", (0, 10), raw_by_row, nodes, floor=2)
    assert data is not None
    assert data.name == "Score"
    by_label = {b.label: b for b in data.bands}
    assert set(by_label) == {"Low (0-6)", "Middle (7-8)", "High (9-10)"}

    low = by_label["Low (0-6)"]
    assert low.answers == 4  # rows 0, 1, 4, 8
    assert low.mix == [50.0, 25.0, 25.0]  # A=2/4, B=1/4, Other=1/4
    assert low.sentiment == pytest.approx((0.5 * 2 + -0.5 * 1 + 0.0 * 1) / 4, abs=1e-6)

    mid = by_label["Middle (7-8)"]
    assert mid.answers == 2  # rows 5, 6
    assert mid.mix == [0.0, 100.0, 0.0]
    assert mid.sentiment == pytest.approx(-0.5, abs=1e-6)

    high = by_label["High (9-10)"]
    assert high.answers == 4  # rows 2, 3, 7, 9
    assert high.mix == [50.0, 25.0, 25.0]
    assert high.sentiment == pytest.approx((0.5 * 2 + -0.5 * 1 + 0.0 * 1) / 4, abs=1e-6)


def test_build_score_data_drops_bands_below_floor_but_keeps_the_rest():
    themes = abc_themes()
    nodes = theme_nodes(themes, total_answered=10)
    raw_by_row = {
        0: 3, 1: 4, 2: 9, 3: 9, 4: 2, 5: 7, 6: 8, 7: 9, 8: 5, 9: 10,
    }
    # Middle only has 2 answers (rows 5, 6) - below floor=3, dropped; Low (4) and High (4) survive.
    data = build_score_data("Score", (0, 10), raw_by_row, nodes, floor=3)
    assert data is not None
    assert {b.label for b in data.bands} == {"Low (0-6)", "High (9-10)"}


def test_build_score_data_returns_none_when_fewer_than_two_bands_survive():
    themes = abc_themes()
    nodes = theme_nodes(themes, total_answered=10)
    raw_by_row = {
        0: 3, 1: 4, 2: 9, 3: 9, 4: 2, 5: 7, 6: 8, 7: 9, 8: 5, 9: 10,
    }
    # floor=5 - every band (4, 2, 4 answers) falls below it, so 0 survive.
    assert build_score_data("Score", (0, 10), raw_by_row, nodes, floor=5) is None


def test_build_score_data_returns_none_when_no_row_has_a_valid_score():
    themes = abc_themes()
    nodes = theme_nodes(themes, total_answered=10)
    assert build_score_data("Score", (0, 10), {}, nodes, floor=2) is None


# -------------------------------------------------------------------- build_numeric_data (docs/TODO.md,
# fixed 2026-10-22) - same cross-tab core as build_score_data, banded via quartiles instead of a fixed scale

def test_build_numeric_data_bands_via_quartiles_not_a_fixed_scale():
    themes = abc_themes()
    nodes = theme_nodes(themes, total_answered=10)
    # 10 distinct values, 0..90 - quartile cuts, not a Low/Middle/High 0-10 scale.
    raw_by_row = {i: float(i * 10) for i in range(10)}
    data = build_numeric_data("Age", raw_by_row, nodes, floor=2)
    assert data is not None
    assert data.name == "Age"
    assert len(data.bands) == 4  # 4 distinct quartile cuts at this spread
    assert sum(b.answers for b in data.bands) == 10


def test_build_numeric_data_returns_none_when_fewer_than_two_distinct_values():
    themes = abc_themes()
    nodes = theme_nodes(themes, total_answered=10)
    raw_by_row = {i: 5.0 for i in range(10)}  # every value identical - band_quartiles itself raises
    assert build_numeric_data("Age", raw_by_row, nodes, floor=2) is None


def test_build_numeric_data_formats_labels_with_the_given_unit():
    themes = abc_themes()
    nodes = theme_nodes(themes, total_answered=10)
    raw_by_row = {i: float(i * 1000) for i in range(10)}
    data = build_numeric_data("Income", raw_by_row, nodes, floor=2, unit="currency")
    assert data is not None
    assert all(label.startswith("$") for label in {b.label for b in data.bands})


# -------------------------------------------------------------------- build_segment_data

def test_build_segment_data_hand_computable_values_overall_and_highlight():
    themes = [
        make_theme("A", 5, 0.0, [0, 1, 2, 3, 4]),
        make_theme("B", 5, 0.0, [5, 6, 7, 8, 9]),
        make_theme("Other", 5, 0.0, [10, 11, 12, 13, 14]),
    ]
    nodes = theme_nodes(themes, total_answered=15)
    assert [n.name for n in nodes] == ["A", "B", "Other"]
    assert [n.share for n in nodes] == [pytest.approx(33.3)] * 3

    # G1 (5 rows): A=2, B=2, Other=1. G2 (10 rows): A=3, B=3, Other=4.
    raw_by_row = {
        0: "G1", 1: "G1", 2: "G2", 3: "G2", 4: "G2",           # A: G1, G1, G2, G2, G2
        5: "G1", 6: "G1", 7: "G2", 8: "G2", 9: "G2",           # B: G1, G1, G2, G2, G2
        10: "G1", 11: "G2", 12: "G2", 13: "G2", 14: "G2",      # Other: G1, G2, G2, G2, G2
    }
    data = build_segment_data("Segment", raw_by_row, nodes, floor=2, heatmap_group_floor=2)
    assert data is not None
    assert data.name == "Segment"
    # G2 (10) is larger than G1 (5), so groups sort largest-first: G2 then G1.
    assert [(g.label, g.n) for g in data.groups] == [("G2", 10), ("G1", 5)]

    by_theme = {r.theme: r for r in data.rows}
    assert by_theme["A"].overall == pytest.approx(33.3)
    assert by_theme["A"].values == [30.0, 40.0]  # [G2, G1]
    assert by_theme["B"].values == [30.0, 40.0]
    assert by_theme["Other"].values == [40.0, 20.0]

    assert by_theme["A"].counts == [3, 2]  # real counts travel with the row (BUG-050)
    assert by_theme["Other"].counts == [4, 1]

    # Other/G1 is 0.6x overall, but 1 answer out of 5 is no evidence of anything: no cell passes the
    # significance test, so the chart gets no hover claim at all (BUG-050).
    assert data.highlight is None
    assert data.highlight_text == ""


def test_build_segment_data_drops_groups_below_heatmap_floor():
    themes = [
        make_theme("A", 6, 0.0, list(range(6))),
        make_theme("Other", 4, 0.0, list(range(6, 10))),
    ]
    nodes = theme_nodes(themes, total_answered=10)
    raw_by_row = {i: "Big" for i in range(8)}
    raw_by_row.update({8: "Tiny", 9: "Tiny"})
    # "Big" has 8 rows, "Tiny" has 2 - below heatmap_group_floor=5, dropped.
    data = build_segment_data("Segment", raw_by_row, nodes, floor=2, heatmap_group_floor=5)
    assert data is None  # only 1 group survives


def test_build_segment_data_returns_none_when_fewer_than_two_groups_survive():
    themes = abc_themes()
    nodes = theme_nodes(themes, total_answered=10)
    raw_by_row = {i: "OnlyGroup" for i in range(10)}
    assert build_segment_data("Segment", raw_by_row, nodes, floor=2, heatmap_group_floor=5) is None


def test_build_segment_data_skips_rows_whose_overall_share_is_zero():
    """A theme with 0 overall share (e.g. total_answered mismatched, or a pathological 0-size theme) must
    never be picked as the highlight cell - dividing by its overall would raise ZeroDivisionError."""
    themes = [
        make_theme("A", 0, 0.0, []),
        make_theme("B", 10, 0.0, list(range(10))),
    ]
    nodes = theme_nodes(themes, total_answered=10)
    raw_by_row = {i: ("G1" if i < 5 else "G2") for i in range(10)}
    data = build_segment_data("Segment", raw_by_row, nodes, floor=2, heatmap_group_floor=2)
    assert data is not None
    a_row = next(r for r in data.rows if r.theme == "A")
    assert a_row.overall == 0.0
    # The highlight, if any, must not reference row 0 ("A") since its overall is 0.
    if data.highlight is not None:
        assert data.rows[data.highlight[0]].theme != "A"


def test_build_segment_data_overall_ignores_rows_with_no_group_bug_041():
    """BUG-041 (dataset 12, scaled down): most of a theme's answers have no group value. Its share of ALL
    answers (3.4%) must not be the baseline for cells that only count grouped rows (0.1-0.2%) - otherwise
    every region reads as "almost never mentions" the theme. Rows 0-2999 are in R1/R2/R3 (1,000 each), rows
    3000-3999 have no group at all."""
    privacy_refs = [0, 1, 1000, 1001, 2000] + list(range(3000, 3130))  # 135 answers, only 5 grouped
    privacy = set(privacy_refs)
    themes = [
        make_theme("Privacy", 135, 0.0, privacy_refs),
        make_theme("Main", 3865, 0.0, [r for r in range(4000) if r not in privacy]),
    ]
    nodes = theme_nodes(themes, total_answered=4000)
    assert next(n for n in nodes if n.name == "Privacy").share == pytest.approx(3.4)
    raw_by_row = {r: f"R{r // 1000 + 1}" for r in range(3000)}

    data = build_segment_data("Region", raw_by_row, nodes, floor=30)
    row = next(r for r in data.rows if r.theme == "Privacy")
    assert row.values == [0.2, 0.2, 0.1]  # R1, R2, R3 (equal sizes keep insertion order)
    assert row.overall == 0.2  # 5 / 3000 grouped rows, not 135 / 4000
    # 0.1 vs 0.2 is a rounding artefact of 0.1/0.2 vs 0.167, not a 2x skew - and the theme is spread evenly.
    assert segment_skew_candidates(data, themes, floor=30) == []
    # No hover claim either: 1 vs 2 answers per region is noise (BUG-050).
    assert data.highlight is None


def test_build_segment_data_real_skew_survives_ungrouped_rows_and_one_finding_per_theme():
    """A theme that genuinely concentrates in one group is still found when many rows have no group, and
    the baseline only counts the groups shown (a "Tiny" group below the heatmap floor is excluded from it
    as well). Its three skewed cells yield ONE segment-skew candidate, the strongest (BUG-042)."""
    skewed_refs = list(range(100)) + list(range(3000, 3510))  # 100 in R1, 500 ungrouped, 10 in Tiny
    skewed = set(skewed_refs)
    themes = [
        make_theme("Skewed", 610, 0.0, skewed_refs),
        make_theme("Main", 3390, 0.0, [r for r in range(4000) if r not in skewed]),
    ]
    nodes = theme_nodes(themes, total_answered=4000)
    raw_by_row = {r: f"R{r // 1000 + 1}" for r in range(3000)}
    raw_by_row.update({r: "Tiny" for r in range(3500, 3510)})

    data = build_segment_data("Region", raw_by_row, nodes, floor=30)
    assert [g.label for g in data.groups] == ["R1", "R2", "R3"]
    row = next(r for r in data.rows if r.theme == "Skewed")
    assert row.values == [10.0, 0.0, 0.0]
    assert row.overall == 3.3  # 100 / 3000, ignoring both the ungrouped rows and Tiny

    candidates = [c for c in segment_skew_candidates(data, themes, floor=30) if c.theme_name == "Skewed"]
    assert len(candidates) == 1
    assert candidates[0].numbers["group"] == "R1"  # 6.7-point gap beats R2/R3's 3.3
    assert candidates[0].score == pytest.approx(6.7)


# -------------------------------------------------------------------- build_frequency_data (chart-block
# stream, 2026-10-24: ranked_answers/ranked_list)

def test_build_frequency_data_merges_case_and_plural_variants():
    raw = {i: v for i, v in enumerate(
        ["Teacher"] * 20 + ["teacher"] * 5 + ["Nurse"] * 18 + ["nurses"] * 3 + ["Engineer"] * 10,
    )}
    data = build_frequency_data("Job", raw, floor=2)
    by_label = {i.label: i for i in data.items}
    assert by_label["Teacher"].merged == 1  # "teacher" folded in
    assert by_label["Nurse"].merged == 1  # "nurses" folded in
    assert by_label["Engineer"].merged == 0
    assert data.answered == 56
    assert data.highlight == "Teacher"  # the most common group


def test_build_frequency_data_keeps_the_most_common_casing_as_the_display_label():
    raw = {i: v for i, v in enumerate(
        ["teacher"] * 2 + ["Teacher"] * 10 + ["TEACHER"] * 1 + ["Nurse"] * 8,
    )}
    data = build_frequency_data("Job", raw, floor=2)
    assert data.items[0].label == "Teacher"  # the most common of the 3 case forms, not the first seen


def test_build_frequency_data_drops_groups_below_the_floor():
    raw = {i: v for i, v in enumerate(["Common"] * 10 + ["AlsoCommon"] * 6 + ["Rare"] * 2)}
    data = build_frequency_data("Job", raw, floor=5)
    labels = {i.label for i in data.items}
    assert "Rare" not in labels  # below floor=5, dropped
    assert labels == {"Common", "AlsoCommon"}
    assert data.answered == 18  # answered counts every real row, including the dropped group's


def test_build_frequency_data_returns_none_when_fewer_than_two_groups_survive():
    raw = {i: "OnlyOne" for i in range(10)}
    assert build_frequency_data("Job", raw, floor=2) is None


def test_build_frequency_data_caps_to_max_items():
    raw: dict[int, str] = {}
    i = 0
    for n in range(12):  # 12 distinct groups, each well above the floor
        for _ in range(5):
            raw[i] = f"Group{n}"
            i += 1
    data = build_frequency_data("Job", raw, floor=2, max_items=8)
    assert len(data.items) == 8


# -------------------------------------------------------------------- build_category_avg_data (chart-block
# stream, 2026-10-24, batch 2: vs_average)

def test_build_category_avg_data_ranks_categories_by_their_own_real_average():
    cat = {i: v for i, v in enumerate(["Engineer"] * 4 + ["Teacher"] * 4)}
    num = {0: 90000, 1: 92000, 2: 94000, 3: 96000, 4: 40000, 5: 42000, 6: 44000, 7: 46000}
    data = build_category_avg_data("Job", "Income", cat, num, floor=2)
    assert data is not None
    assert [i.label for i in data.items] == ["Engineer", "Teacher"]  # highest average first
    assert data.items[0].avg == 93000.0
    assert data.overall_avg == pytest.approx((90000 + 92000 + 94000 + 96000 + 40000 + 42000 + 44000 + 46000) / 8)


def test_build_category_avg_data_only_counts_rows_with_both_values():
    cat = {0: "Engineer", 1: "Engineer", 2: "Teacher"}  # row 2 has no matching number value
    num = {0: 90000, 1: 92000, 3: 999999}  # row 3 has no matching category value
    data = build_category_avg_data("Job", "Income", cat, num, floor=1)
    assert data is None  # only "Engineer" has any row with both values - 1 category can't be ranked
    cat2 = {0: "Engineer", 1: "Teacher"}
    num2 = {0: 90000, 1: 40000}
    data2 = build_category_avg_data("Job", "Income", cat2, num2, floor=1)
    assert data2.overall_avg == 65000.0  # only rows 0,1 count - never a stray unmatched value


def test_build_category_avg_data_drops_categories_below_the_floor():
    cat = {i: "Common" for i in range(10)}
    cat.update({i: "AlsoCommon" for i in range(10, 16)})
    cat.update({16: "Rare", 17: "Rare"})
    num = {i: 100.0 for i in range(18)}
    data = build_category_avg_data("Job", "Income", cat, num, floor=5)
    labels = {i.label for i in data.items}
    assert "Rare" not in labels
    assert labels == {"Common", "AlsoCommon"}


def test_build_category_avg_data_returns_none_when_fewer_than_two_categories_survive():
    cat = {i: "OnlyOne" for i in range(10)}
    num = {i: 100.0 for i in range(10)}
    assert build_category_avg_data("Job", "Income", cat, num, floor=2) is None


# -------------------------------------------------------------------- build_trend_data

def _period_row_ids(period_sizes: dict[str, int]) -> dict[str, list[int]]:
    ids: dict[str, list[int]] = {}
    n = 0
    for label, size in period_sizes.items():
        ids[label] = list(range(n, n + size))
        n += size
    return ids


def test_build_trend_data_hand_computable_shares_sentiment_and_hover_index():
    # Three periods, each with exactly 30 rows (the trend-specific floor, boundary-inclusive) laid out as
    # contiguous row-index blocks so date_bands (lo/hi over row index itself) map 1:1 to periods.
    period_rows = _period_row_ids({"P1": 30, "P2": 30, "P3": 30})
    date_bands = [
        Band("P1", 0, 29), Band("P2", 30, 59), Band("P3", 60, 89),
    ]
    raw_by_row = {r: float(r) for r in range(90)}

    p1_a, p1_b, p1_o = period_rows["P1"][:15], period_rows["P1"][15:25], period_rows["P1"][25:30]
    p2_a, p2_b, p2_o = period_rows["P2"][:10], period_rows["P2"][10:25], period_rows["P2"][25:30]
    p3_a, p3_b, p3_o = period_rows["P3"][:5], period_rows["P3"][5:10], period_rows["P3"][10:30]

    a_refs = p1_a + p2_a + p3_a
    b_refs = p1_b + p2_b + p3_b
    o_refs = p1_o + p2_o + p3_o
    assert len(a_refs) == len(b_refs) == len(o_refs) == 30

    themes = [
        make_theme("A", 30, 0.4, a_refs),
        make_theme("B", 30, -0.2, b_refs),
        make_theme("Other", 30, 0.0, o_refs),
    ]
    nodes = theme_nodes(themes, total_answered=90)
    assert [n.name for n in nodes] == ["A", "B", "Other"]

    data = build_trend_data("Date", raw_by_row, nodes, date_bands, "Monthly, P1 to P3.", floor=30)
    assert data is not None
    assert data.labels == ["P1", "P2", "P3"]
    assert data.note == "Monthly, P1 to P3."
    assert data.hover_index == 2

    by_theme = {s.theme: s for s in data.series}
    assert by_theme["A"].values == [50.0, pytest.approx(33.3), pytest.approx(16.7)]
    assert by_theme["B"].values == [pytest.approx(33.3), 50.0, pytest.approx(16.7)]
    assert by_theme["Other"].values == [pytest.approx(16.7), pytest.approx(16.7), pytest.approx(66.7)]

    # sentiment[i] = weighted avg of Theme.sentiment across ALL themes, per period (rounded to 3 decimals
    # by build_trend_data, matching build_report_data's own overall_sentiment rounding convention).
    assert data.sentiment[0] == pytest.approx((0.4 * 15 + -0.2 * 10 + 0.0 * 5) / 30, abs=1e-3)
    assert data.sentiment[1] == pytest.approx((0.4 * 10 + -0.2 * 15 + 0.0 * 5) / 30, abs=1e-3)
    assert data.sentiment[2] == pytest.approx((0.4 * 5 + -0.2 * 5 + 0.0 * 20) / 30, abs=1e-3)


def test_build_trend_data_drops_periods_under_thirty_and_needs_at_least_three():
    themes = [make_theme("A", 60, 0.0, list(range(60)))]
    nodes = theme_nodes(themes, total_answered=60)
    date_bands = [Band("P1", 0, 29), Band("P2", 30, 59)]
    raw_by_row = {r: float(r) for r in range(60)}
    # Both periods individually have 30 answers (>= 30), but only 2 periods total exist - below the
    # "need at least 3 periods" floor, so this must return None regardless of per-period counts.
    assert build_trend_data("Date", raw_by_row, nodes, date_bands, "note", floor=30) is None


def test_build_trend_data_returns_none_when_a_period_is_too_small():
    themes = [make_theme("A", 89, 0.0, list(range(89)))]
    nodes = theme_nodes(themes, total_answered=89)
    date_bands = [Band("P1", 0, 29), Band("P2", 30, 59), Band("P3", 60, 88)]  # P3 has only 29 rows
    raw_by_row = {r: float(r) for r in range(89)}
    data = build_trend_data("Date", raw_by_row, nodes, date_bands, "note", floor=30)
    assert data is None  # only P1 and P2 survive - below the "at least 3" floor


# -------------------------------------------------------------------- build_group_trend_data (chart-block
# stream, 2026-10-24, batch 2: trend_groups/trend_styled)

def test_build_group_trend_data_real_sentiment_per_group_per_period():
    themes = [make_theme("Negative theme", 150, -0.6, list(range(150))), make_theme("Positive theme", 150, 0.6, list(range(150, 300)))]
    nodes = theme_nodes(themes, total_answered=300)
    # Biz rows all land in the negative theme, Cons rows all in the positive theme - every period.
    segment_raw = {r: ("Biz" if r < 150 else "Cons") for r in range(300)}
    period_by_row = {r: ["P1", "P2", "P3"][r % 3] for r in range(300)}
    data = build_group_trend_data("Type", segment_raw, period_by_row, ["P1", "P2", "P3"], "note", nodes, group_floor=10)
    assert data is not None
    by_group = {s.group: s for s in data.series}
    assert all(v == pytest.approx(-0.6) for v in by_group["Biz"].values)
    assert all(v == pytest.approx(0.6) for v in by_group["Cons"].values)
    assert data.labels == ["P1", "P2", "P3"]


def test_build_group_trend_data_drops_a_period_missing_from_any_surviving_group():
    themes = [make_theme("A", 220, 0.0, list(range(220)))]
    nodes = theme_nodes(themes, total_answered=220)
    segment_raw = {r: ("Biz" if r < 110 else "Cons") for r in range(220)}
    # Biz only ever appears in P1/P2; Cons appears in P1/P2/P3 - P3 must be dropped (Biz has no data there).
    period_by_row = {}
    for r in range(110):
        period_by_row[r] = "P1" if r < 60 else "P2"
    for r in range(110, 220):
        period_by_row[r] = ["P1", "P2", "P3"][(r - 110) % 3]
    data = build_group_trend_data("Type", segment_raw, period_by_row, ["P1", "P2", "P3"], "note", nodes, group_floor=10)
    assert data is None  # only P1/P2 survive for both groups - below the "at least 3 periods" floor


def test_build_group_trend_data_drops_groups_below_the_floor_and_caps_to_max_groups():
    themes = [make_theme("A", 300, 0.0, list(range(300)))]
    nodes = theme_nodes(themes, total_answered=300)
    segment_raw = {}
    for i, g in enumerate(["Big1", "Big2", "Big3", "Tiny"]):
        n = 5 if g == "Tiny" else 95
        for j in range(n):
            segment_raw[len(segment_raw)] = g
    period_by_row = {r: ["P1", "P2", "P3"][r % 3] for r in range(len(segment_raw))}
    data = build_group_trend_data(
        "Type", segment_raw, period_by_row, ["P1", "P2", "P3"], "note", nodes, group_floor=10, max_groups=2,
    )
    assert data is not None
    groups = {s.group for s in data.series}
    assert "Tiny" not in groups  # below group_floor=10
    assert len(groups) == 2  # capped to max_groups=2 even though 3 real groups survived the floor


def test_build_group_trend_data_returns_none_when_fewer_than_two_groups_survive():
    themes = [make_theme("A", 100, 0.0, list(range(100)))]
    nodes = theme_nodes(themes, total_answered=100)
    segment_raw = {r: "OnlyGroup" for r in range(100)}
    period_by_row = {r: ["P1", "P2", "P3"][r % 3] for r in range(100)}
    assert build_group_trend_data("Type", segment_raw, period_by_row, ["P1", "P2", "P3"], "note", nodes, group_floor=10) is None


# -------------------------------------------------------------------- build_binned_grid_data (chart-block
# stream, 2026-10-24, batch 3: binned_grid)

def test_build_binned_grid_data_crosses_two_real_number_columns():
    themes = [make_theme("Pos", 50, 0.5, list(range(50))), make_theme("Neg", 50, -0.5, list(range(50, 100)))]
    nodes = theme_nodes(themes, total_answered=100)
    row_raw = {r: float(r % 10) for r in range(100)}  # 10 distinct values, even spread
    col_raw = {r: float((r * 7) % 20) for r in range(100)}
    data = build_binned_grid_data("Age", "Spend", row_raw, col_raw, nodes, floor=1)
    assert data is not None
    assert data.row_name == "Age" and data.col_name == "Spend"
    assert len(data.cells) == len(data.row_labels) * len(data.col_labels)
    assert sum(c.count for c in data.cells) <= 100  # some cells may be under-floor and zeroed


def test_build_binned_grid_data_only_counts_rows_with_both_values():
    themes = [make_theme("A", 2, 0.0, [0, 1])]
    nodes = theme_nodes(themes, total_answered=2)
    row_raw = {0: 1.0, 1: 2.0}  # row 2 has no col value
    col_raw = {0: 1.0, 2: 2.0}  # row 1 has no row value
    assert build_binned_grid_data("A", "B", row_raw, col_raw, nodes, floor=1) is None  # only row 0 has both


def test_build_binned_grid_data_returns_none_when_a_column_cannot_be_banded():
    themes = [make_theme("A", 20, 0.0, list(range(20)))]
    nodes = theme_nodes(themes, total_answered=20)
    row_raw = {r: 5.0 for r in range(20)}  # only 1 distinct value - band_quartiles raises
    col_raw = {r: float(r) for r in range(20)}
    assert build_binned_grid_data("A", "B", row_raw, col_raw, nodes, floor=1) is None


def test_build_binned_grid_data_zeroes_cells_under_the_floor_without_dropping_the_band():
    themes = [make_theme("A", 40, 0.2, list(range(40)))]
    nodes = theme_nodes(themes, total_answered=40)
    row_raw = {r: float(r % 4) for r in range(40)}  # 4 even row bands
    col_raw = {r: (0.0 if r != 0 else 1.0) for r in range(40)}  # col band with only 1 member overall
    data = build_binned_grid_data("A", "B", row_raw, col_raw, nodes, floor=5)
    assert data is not None
    sparse_cells = [c for c in data.cells if c.col_label == data.col_labels[-1]]
    assert all(c.count == 0 and c.sentiment == 0.0 for c in sparse_cells)  # under floor=5, zeroed not dropped


# -------------------------------------------------------------------- pick_structured_columns

@pytest.fixture()
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with SessionLocal() as s:
        yield s


def _make_dataset(s):
    ds = Dataset(project_id=1, filename="survey.csv", file_hash="0" * 64, row_count=100, profile={})
    s.add(ds)
    s.flush()
    return ds


def test_pick_structured_columns_respects_position_order(session):
    ds = _make_dataset(session)
    session.add_all([
        Column(dataset_id=ds.id, name="Score2", position=1, kind="score", stats={}),
        Column(dataset_id=ds.id, name="Score1", position=0, kind="score", stats={}),
        Column(dataset_id=ds.id, name="Segment1", position=2, kind="segment", stats={}),
        Column(dataset_id=ds.id, name="Date1", position=3, kind="date", stats={}),
    ])
    session.commit()

    picked = pick_structured_columns(ds.id, session)
    assert picked == {
        "score": ["Score1", "Score2"], "segment": ["Segment1"], "date": ["Date1"], "numeric": [], "yes_no": [],
        "short_text": [],
    }


def test_pick_structured_columns_skips_switched_off_columns(session):
    ds = _make_dataset(session)
    session.add_all([
        Column(dataset_id=ds.id, name="Score1", position=0, kind="score", stats={"off": True}),
        Column(dataset_id=ds.id, name="Score2", position=1, kind="score", stats={"off": False}),
    ])
    session.commit()

    picked = pick_structured_columns(ds.id, session)
    assert picked["score"] == ["Score2"]


def test_pick_structured_columns_none_when_no_matching_kind(session):
    ds = _make_dataset(session)
    session.add(Column(dataset_id=ds.id, name="Open", position=0, kind="open_text", stats={}))
    session.commit()

    picked = pick_structured_columns(ds.id, session)
    assert picked == {"score": [], "segment": [], "date": [], "numeric": [], "yes_no": [], "short_text": []}


# -------------------------------------------------------------------- build_structured_context

def _plan_with_score_step(column: str, scale: list[int]) -> CleaningPlan:
    step = Step(
        id="s1", key="check_score_range", column=column, title="", description="",
        enabled=True, params={"scale": scale},
    )
    return CleaningPlan(steps=[step], settings={}, columns={})


def test_build_structured_context_returns_none_score_when_scale_step_missing():
    themes = abc_themes()
    nodes = theme_nodes(themes, total_answered=10)
    clean_df = pd.DataFrame({"Score": [3, 4, 9, 9, 2, 7, 8, 9, 5, 10]})
    plan = CleaningPlan(steps=[], settings={}, columns={})  # no check_score_range step at all

    context = build_structured_context(
        clean_df, plan, themes, nodes, {"score": ["Score"]}, floor=2,
    )
    assert context.score is None
    assert context.score_column_name == ""


def test_build_structured_context_builds_score_from_confirmed_scale():
    themes = abc_themes()
    nodes = theme_nodes(themes, total_answered=10)
    clean_df = pd.DataFrame({"Score": [3, 4, 9, 9, 2, 7, 8, 9, 5, 10]})
    plan = _plan_with_score_step("Score", [0, 10])

    context = build_structured_context(clean_df, plan, themes, nodes, {"score": ["Score"]}, floor=2)
    assert context.score is not None
    assert context.score_column_name == "Score"
    assert context.score.name == "Score"
    assert {b.label for b in context.score.bands} == {"Low (0-6)", "Middle (7-8)", "High (9-10)"}


def test_build_structured_context_ignores_absent_columns():
    themes = abc_themes()
    nodes = theme_nodes(themes, total_answered=10)
    clean_df = pd.DataFrame({"Score": [3, 4, 9, 9, 2, 7, 8, 9, 5, 10]})
    plan = _plan_with_score_step("Score", [0, 10])

    context = build_structured_context(clean_df, plan, themes, nodes, {}, floor=2)
    assert context == StructuredContext()


def test_build_structured_context_falls_back_to_the_next_candidate_when_the_first_produces_nothing():
    """The core new behaviour this stream adds: pick_structured_columns now hands over every confirmed
    candidate of a kind, not just the first in column-position order, and build_structured_context must
    actually try the second one when the first's data fails to survive suppression - not just always use
    whichever column happened to be confirmed/uploaded first."""
    n = 300
    rows = range(n)
    # BadSegment: a single group covering every row - build_segment_data needs >=2 surviving groups, so
    # this candidate must fail and NOT become context.segment.
    bad_segment = ["OnlyGroup" for _ in rows]
    # GoodSegment: the same 170/130 split _big_dataset() already uses elsewhere in this file, well clear
    # of every suppression floor - this candidate must be the one actually used.
    good_segment = ["North" if i < 170 else "South" for i in rows]
    clean_df = pd.DataFrame({"BadSegment": bad_segment, "GoodSegment": good_segment})

    themes = [
        make_theme("A", 150, 0.3, list(range(0, 150))),
        make_theme("B", 100, -0.1, list(range(150, 250))),
        make_theme("Other", 50, 0.0, list(range(250, 300))),
    ]
    nodes = theme_nodes(themes, total_answered=300)
    plan = CleaningPlan(steps=[], settings={}, columns={})
    columns = {"score": [], "segment": ["BadSegment", "GoodSegment"], "date": []}

    context = build_structured_context(clean_df, plan, themes, nodes, columns, floor=30)

    assert context.segment is not None
    assert context.segment_column_name == "GoodSegment"
    groups_by_label = {g.label: g.n for g in context.segment.groups}
    assert groups_by_label == {"North": 170, "South": 130}


# -------------------------------------------------------------------- numeric/yes_no kinds (docs/TODO.md,
# fixed 2026-10-22): feed the SAME score/segment slots as a fallback, only when no real score/segment
# candidate won.

def test_build_structured_context_builds_score_from_a_numeric_column_via_quartiles():
    """The real gap this fixes: a confirmed `numeric`-kind column (no check_score_range step, since
    numeric columns are never scored against a fixed scale) used to be silently dropped entirely - now
    it feeds context.score via band_quartiles instead."""
    n = 300
    rows = range(n)
    themes = [
        make_theme("A", 150, 0.3, list(range(0, 150))),
        make_theme("B", 100, -0.1, list(range(150, 250))),
        make_theme("Other", 50, 0.0, list(range(250, 300))),
    ]
    nodes = theme_nodes(themes, total_answered=300)
    age = [20 + (i % 60) for i in rows]  # spread 20-79, well clear of every quartile-band floor
    clean_df = pd.DataFrame({"Age": age})
    plan = CleaningPlan(steps=[], settings={}, columns={})

    context = build_structured_context(
        clean_df, plan, themes, nodes, {"score": [], "segment": [], "date": [], "numeric": ["Age"], "yes_no": []},
        floor=30,
    )

    assert context.score is not None
    assert context.score_column_name == "Age"
    assert len(context.score.bands) in (2, 4)  # band_quartiles' own 4-band (or 2-band fallback) contract
    # No scale was ever confirmed for a numeric column - resolve_filter_rows must not band this wrongly.
    assert context.score_raw_by_row is None
    assert context.score_scale is None


def test_build_structured_context_prefers_a_real_score_column_over_numeric():
    """Regression pin: numeric is a FALLBACK, not a parallel slot - when a real score column already won,
    a numeric candidate must never override it."""
    n = 300
    rows = range(n)
    themes = [
        make_theme("A", 150, 0.3, list(range(0, 150))),
        make_theme("B", 100, -0.1, list(range(150, 250))),
        make_theme("Other", 50, 0.0, list(range(250, 300))),
    ]
    nodes = theme_nodes(themes, total_answered=300)
    score = [[3, 7, 9][i % 3] for i in rows]
    age = [20 + (i % 60) for i in rows]
    clean_df = pd.DataFrame({"Score": score, "Age": age})
    plan = _plan_with_score_step("Score", [0, 10])

    context = build_structured_context(
        clean_df, plan, themes, nodes, {"score": ["Score"], "segment": [], "date": [], "numeric": ["Age"], "yes_no": []},
        floor=30,
    )

    assert context.score_column_name == "Score"


def test_build_structured_context_builds_segment_from_a_yes_no_column():
    """The real gap this fixes: a confirmed `yes_no`-kind column used to be silently dropped entirely -
    now it feeds context.segment via build_segment_data directly (a yes/no column is just a 2-value
    categorical, no new code path needed)."""
    n = 300
    rows = range(n)
    themes = [
        make_theme("A", 150, 0.3, list(range(0, 150))),
        make_theme("B", 100, -0.1, list(range(150, 250))),
        make_theme("Other", 50, 0.0, list(range(250, 300))),
    ]
    nodes = theme_nodes(themes, total_answered=300)
    recommend = ["Yes" if i < 170 else "No" for i in rows]  # 170/130, clear of the heatmap floor
    clean_df = pd.DataFrame({"WouldRecommend": recommend})
    plan = CleaningPlan(steps=[], settings={}, columns={})

    context = build_structured_context(
        clean_df, plan, themes, nodes,
        {"score": [], "segment": [], "date": [], "numeric": [], "yes_no": ["WouldRecommend"]}, floor=30,
    )

    assert context.segment is not None
    assert context.segment_column_name == "WouldRecommend"
    groups_by_label = {g.label: g.n for g in context.segment.groups}
    assert groups_by_label == {"Yes": 170, "No": 130}


def test_build_structured_context_prefers_a_real_segment_column_over_yes_no():
    """Regression pin: yes_no is a FALLBACK, not a parallel slot."""
    n = 300
    rows = range(n)
    themes = [
        make_theme("A", 150, 0.3, list(range(0, 150))),
        make_theme("B", 100, -0.1, list(range(150, 250))),
        make_theme("Other", 50, 0.0, list(range(250, 300))),
    ]
    nodes = theme_nodes(themes, total_answered=300)
    segment = ["North" if i < 170 else "South" for i in rows]
    recommend = ["Yes" if i < 170 else "No" for i in rows]
    clean_df = pd.DataFrame({"Segment": segment, "WouldRecommend": recommend})
    plan = CleaningPlan(steps=[], settings={}, columns={})

    context = build_structured_context(
        clean_df, plan, themes, nodes,
        {"score": [], "segment": ["Segment"], "date": [], "numeric": [], "yes_no": ["WouldRecommend"]}, floor=30,
    )

    assert context.segment_column_name == "Segment"


# -------------------------------------------------------------------- integration: full build_report_data
# through the real charts module, plus the backward-compat pin

def _big_dataset():
    """300 rows, all three of score/segment/date well clear of every suppression floor: 3 score bands of
    100 each, 2 segment groups (170/130), 3 monthly date periods of 100 each. Three themes (A=150, B=100,
    Other=50)."""
    n = 300
    rows = range(n)
    score = [[3, 7, 9][i % 3] for i in rows]  # even 100/100/100 split across Low/Middle/High
    segment = ["North" if i < 170 else "South" for i in rows]  # 170 / 130, no tie
    month = ["2026-01-15" if i < 100 else "2026-02-15" if i < 200 else "2026-03-15" for i in rows]
    clean_df = pd.DataFrame({"Score": score, "Segment": segment, "Date": month})

    themes = [
        make_theme("A", 150, 0.3, list(range(0, 150))),
        make_theme("B", 100, -0.1, list(range(150, 250))),
        make_theme("Other", 50, 0.0, list(range(250, 300))),
    ]
    plan = _plan_with_score_step("Score", [0, 10])
    return clean_df, themes, plan


def test_build_structured_context_builds_all_three_from_realistic_data():
    clean_df, themes, plan = _big_dataset()
    nodes = theme_nodes(themes, total_answered=300)
    columns = {"score": ["Score"], "segment": ["Segment"], "date": ["Date"]}

    context = build_structured_context(clean_df, plan, themes, nodes, columns, floor=30)

    assert context.score is not None
    assert {b.answers for b in context.score.bands} == {100}

    assert context.segment is not None
    groups_by_label = {g.label: g.n for g in context.segment.groups}
    assert groups_by_label == {"North": 170, "South": 130}

    assert context.trend is not None
    assert context.trend.labels == ["Jan", "Feb", "Mar"]
    assert all(s.values for s in context.trend.series)


def test_build_structured_context_drops_nan_segment_values_instead_of_treating_them_as_a_group():
    """Real bug, 2026-10-21: a blank/missing segment cell reads back from pandas as `float('nan')`, and an
    unguarded `clean_df.at[r, segment_col]` lookup let that NaN become a literal `SegmentGroup(label=nan,
    ...)`. That NaN then flowed all the way to `app/api_report.py`'s `filter_options` in the JSON response,
    crashing the WHOLE report endpoint with a 500 ("Out of range float values are not JSON compliant:
    nan") - not just the segment/heatmap block. A missing value must never become its own "group"."""
    n = 300
    rows = range(n)
    score = [[3, 7, 9][i % 3] for i in rows]
    # 170 North, 100 South, 30 missing (blank cells) - North/South both still clear the floor=30 gate.
    segment = ["North" if i < 170 else "South" if i < 270 else float("nan") for i in rows]
    clean_df = pd.DataFrame({"Score": score, "Segment": segment})

    themes = [
        make_theme("A", 150, 0.3, list(range(0, 150))),
        make_theme("B", 100, -0.1, list(range(150, 250))),
        make_theme("Other", 50, 0.0, list(range(250, 300))),
    ]
    plan = _plan_with_score_step("Score", [0, 10])
    nodes = theme_nodes(themes, total_answered=300)
    columns = {"score": ["Score"], "segment": ["Segment"], "date": []}

    context = build_structured_context(clean_df, plan, themes, nodes, columns, floor=30)

    assert context.segment is not None
    labels = {g.label for g in context.segment.groups}
    assert labels == {"North", "South"}  # never a NaN-labeled third "group"
    assert all(isinstance(label, str) for label in labels)
    groups_by_label = {g.label: g.n for g in context.segment.groups}
    assert groups_by_label == {"North": 170, "South": 100}
    # The 30 blank rows must never appear in segment_raw_by_row either - they're not a real group.
    assert len(context.segment_raw_by_row) == 270


def test_build_structured_context_filter_rows_restricts_rows():
    """The core Filters mechanism: `filter_rows` narrows the row universe everything below is computed
    from, with zero changes to build_score_data/build_segment_data/build_trend_data themselves. Drops only
    _big_dataset()'s last 30 rows (the end of South/March) so both segment groups and all 3 trend periods
    still clear their own suppression floors - isolating the test to "counts shrink correctly", not
    "chart disappears"."""
    clean_df, themes, plan = _big_dataset()
    nodes = theme_nodes(themes, total_answered=300)
    columns = {"score": ["Score"], "segment": ["Segment"], "date": ["Date"]}

    filter_rows = set(range(270))  # North (0-169) untouched, South (170-299) trimmed to 170-269
    context = build_structured_context(
        clean_df, plan, themes, nodes, columns, floor=30, filter_rows=filter_rows,
    )

    assert context.segment is not None
    groups_by_label = {g.label: g.n for g in context.segment.groups}
    assert groups_by_label == {"North": 170, "South": 100}  # South shrank from 130 to 100

    assert context.trend is not None
    assert context.trend.labels == ["Jan", "Feb", "Mar"]
    assert len(context.date_raw_by_row) == 270  # Mar shrank (200-269 only) but all 3 periods still survive


# ==================================================================== resolve_filter_rows

def _structured_for_filters() -> StructuredContext:
    clean_df, themes, plan = _big_dataset()
    nodes = theme_nodes(themes, total_answered=300)
    columns = {"score": ["Score"], "segment": ["Segment"], "date": ["Date"]}
    return build_structured_context(clean_df, plan, themes, nodes, columns, floor=30)


def test_resolve_filter_rows_all_none_is_none():
    structured = _structured_for_filters()
    assert resolve_filter_rows(structured, None, None, None, None) is None


def test_resolve_filter_rows_segment_only():
    structured = _structured_for_filters()
    rows = resolve_filter_rows(structured, "North", None, None, None)
    assert rows == set(range(170))  # North is rows 0-169 in _big_dataset()


def test_resolve_filter_rows_score_band_only():
    structured = _structured_for_filters()
    rows = resolve_filter_rows(structured, None, "High (9-10)", None, None)
    # _big_dataset()'s score cycles [3, 7, 9][i % 3] - "High" (9-10) is every i % 3 == 2 row.
    assert rows == {i for i in range(300) if i % 3 == 2}


def test_resolve_filter_rows_date_range_inclusive_and_one_sided():
    structured = _structured_for_filters()
    jan_only = resolve_filter_rows(structured, None, None, date(2026, 1, 1), date(2026, 1, 31))
    assert jan_only == set(range(100))

    from_feb = resolve_filter_rows(structured, None, None, date(2026, 2, 1), None)
    assert from_feb == set(range(100, 300))


def test_resolve_filter_rows_combined_constraints_intersect_not_union():
    structured = _structured_for_filters()
    rows = resolve_filter_rows(structured, "North", "High (9-10)", None, None)
    assert rows == {i for i in range(170) if i % 3 == 2}


def test_resolve_filter_rows_unresolvable_column_yields_empty_set():
    """A constraint naming a role that never resolved to real chart data must be a real empty set, not a
    silent no-op fallback to unfiltered."""
    themes = abc_themes()
    nodes = theme_nodes(themes, total_answered=10)
    clean_df = pd.DataFrame({"Score": [3, 4, 9, 9, 2, 7, 8, 9, 5, 10]})
    plan = CleaningPlan(steps=[], settings={}, columns={})  # no check_score_range step
    structured = build_structured_context(clean_df, plan, themes, nodes, {"score": ["Score"]}, floor=2)
    assert structured.score is None  # sanity: this candidate never resolved

    assert resolve_filter_rows(structured, None, "High", None, None) == set()
    assert resolve_filter_rows(structured, "AnyGroup", None, None, None) == set()
    assert resolve_filter_rows(structured, None, None, date(2020, 1, 1), None) == set()


def test_build_report_data_with_structured_renders_through_real_charts_module():
    """The most important B2 test: proves build_report_data's structured score/segment/trend output is
    actually consumable by app/charts.py's render_parts, not just internally self-consistent - mirrors
    tests/test_findings.py::test_build_report_data_renders_through_real_charts_module's rigor for the
    3 new chart ids this stream wires up (byScore, heatmap, trend)."""
    clean_df, themes, plan = _big_dataset()
    nodes = theme_nodes(themes, total_answered=300)
    columns = {"score": ["Score"], "segment": ["Segment"], "date": ["Date"]}
    structured = build_structured_context(clean_df, plan, themes, nodes, columns, floor=30)

    dataset = Dataset(project_id=1, filename="survey.csv", file_hash="0" * 64, row_count=300, profile={})
    data = build_report_data(dataset, themes, {}, "Why?", structured=structured)

    assert data.score.bands and data.segment.rows and data.trend.labels

    byscore_html, _, _ = render_parts("byScore", data)
    assert "A" in byscore_html and "B" in byscore_html and "Other" in byscore_html

    heatmap_html, _, _ = render_parts("heatmap", data)
    assert "North" in heatmap_html and "South" in heatmap_html

    trend_html, _, _ = render_parts("trend", data)
    assert "Jan" in trend_html and "Feb" in trend_html and "Mar" in trend_html


def test_build_report_data_structured_none_is_byte_identical_to_omitting_it():
    """Backward-compat pin: build_report_data's new `structured` keyword defaults to `None`, and passing
    it explicitly as `None` must produce identical score/segment/trend output to omitting it entirely -
    this is what proves existing callers (tests/test_findings.py, tests/test_api_report.py) keep working
    unmodified."""
    themes = abc_themes()
    dataset = Dataset(project_id=1, filename="survey.csv", file_hash="0" * 64, row_count=10, profile={})

    omitted = build_report_data(dataset, themes, {}, "Why?")
    explicit_none = build_report_data(dataset, themes, {}, "Why?", structured=None)

    assert omitted.score == explicit_none.score == ScoreData(name="", bands=[])
    assert omitted.segment == explicit_none.segment == SegmentData(name="", groups=[], rows=[])
    assert omitted.trend == explicit_none.trend == TrendData(
        labels=[], series=[], sentiment=[], hover_index=0, note="",
    )


# ==================================================================== B3 - new candidate-finding kinds

# ---------------------------------------------------------------- segment_skew_candidates

def _segment(counts_by_theme: dict[str, list[int]], sizes: list[int]) -> SegmentData:
    """A heatmap built straight from counts, the way `build_segment_data` fills it."""
    total = sum(sizes)
    rows = [
        SegmentRow(theme=name, overall=round(100 * sum(c) / total, 1),
                   values=[round(100 * x / n, 1) for x, n in zip(c, sizes)], counts=list(c))
        for name, c in counts_by_theme.items()
    ]
    return SegmentData(name="Region", groups=[SegmentGroup(f"G{i + 1}", n) for i, n in enumerate(sizes)], rows=rows)


def _themes_for(segment: SegmentData) -> list:
    return [make_theme(r.theme, max(sum(r.counts), 1), 0.0, list(range(max(sum(r.counts), 1))))
            for r in segment.rows]


def test_segment_skew_real_skew_passes_with_counts_and_corrected_p():
    segment = _segment({"A": [300, 100, 200]}, [1000, 1000, 1000])  # 30% / 10% / 20%, overall 20%
    candidates = segment_skew_candidates(segment, _themes_for(segment), floor=30)
    assert len(candidates) == 1  # G1 (1.5x) and G2 (0.5x) both pass; one finding per theme (BUG-042)
    c = candidates[0]
    assert c.kind == "segment_skew" and c.theme_name == "A" and c.count == 1000
    assert c.numbers["group"] in {"G1", "G2"}
    assert c.numbers["overall_share_pct"] == 20.0
    assert c.numbers["cell_count"] in {300, 100}
    assert c.numbers["p_adjusted"] < 0.001
    assert c.score == pytest.approx(10.0)


def test_segment_skew_significant_but_ratio_too_small_is_not_a_finding():
    segment = _segment({"A": [280, 200]}, [1000, 1000])  # 28% vs 20%: real (p < 0.001) but only 1.17x
    cells = segment_cell_tests(segment)
    assert all(c.q < 0.05 for c in cells)
    assert not any(c.passes for c in cells)
    assert segment_skew_candidates(segment, _themes_for(segment), floor=30) == []


def test_segment_skew_rare_theme_needs_a_two_point_gap():
    segment = _segment({"A": [300, 100]}, [20000, 20000])  # 1.5% vs 0.5%: 1.5x and real, gap only 0.5 points
    assert all(c.q < 0.05 for c in segment_cell_tests(segment))
    assert segment_skew_candidates(segment, _themes_for(segment), floor=30) == []


def test_segment_skew_needs_ten_answers_in_or_expected_in_the_cell():
    # G1 has 8 of 100 (8%), G2 none of 1000: huge ratio, but 8 answers and under 1 expected is too thin.
    segment = _segment({"A": [8, 0]}, [100, 1000])
    assert segment_skew_candidates(segment, _themes_for(segment), floor=30) == []
    # The same skew at ten times the size passes.
    bigger = _segment({"A": [80, 0]}, [1000, 10000])
    assert len(segment_skew_candidates(bigger, _themes_for(bigger), floor=30)) == 1


def test_segment_skew_below_one_direction_and_zero_rows():
    segment = _segment({"Empty": [0, 0, 0], "B": [100, 400, 400]}, [1000, 1000, 1000])  # B: 10% vs 40%
    candidates = segment_skew_candidates(segment, _themes_for(segment), floor=30)
    assert [c.theme_name for c in candidates] == ["B"]  # an all-zero row is skipped, never a ZeroDivision
    assert segment.highlight is None  # hand-built here; build_segment_data is what sets it
    assert candidates[0].numbers["group"] == "G1"
    assert candidates[0].numbers["ratio"] == pytest.approx(10 / 30, abs=1e-3)


def test_segment_skew_hand_made_rows_without_counts_still_work():
    """Fixtures and older hand-built heatmaps have no `counts`; they are estimated from shares x group n."""
    segment = SegmentData(
        name="Segment", groups=[SegmentGroup("G1", 1000), SegmentGroup("G2", 1000)],
        rows=[SegmentRow(theme="A", overall=20.0, values=[30.0, 10.0])],
    )
    candidates = segment_skew_candidates(segment, [make_theme("A", 400, 0.0, list(range(400)))], floor=30)
    assert len(candidates) == 1 and candidates[0].numbers["cell_count"] in {300, 100}


def test_segment_cells_use_fisher_when_expected_counts_are_small():
    from scipy.stats import fisher_exact
    from app.findings_structured import _two_proportion_p

    assert _two_proportion_p(3, 200, 0, 800) == pytest.approx(fisher_exact([[3, 197], [0, 800]]).pvalue)


def test_segment_skew_chance_only_heatmap_gives_no_findings_after_correction():
    """7 themes x 20 regions with NO real difference (every region draws from the same shares). Without the
    correction some cells look "significant" and plenty clear a bare 1.5x ratio; with it, none survive."""
    import numpy as np

    rng = np.random.default_rng(2026)
    sizes = [150] * 20
    shares = [0.20, 0.12, 0.08, 0.05, 0.04, 0.03, 0.02]
    segment = _segment(
        {f"T{i}": [int(x) for x in rng.binomial(sizes, s)] for i, s in enumerate(shares)}, sizes,
    )
    cells = segment_cell_tests(segment)
    assert len(cells) == 140
    assert sum(c.p < 0.05 for c in cells) > 0  # chance alone produces "significant" cells...
    assert sum(c.ratio >= 1.5 or c.ratio <= 1 / 1.5 for c in cells) > 10  # ...and many naive 1.5x skews
    assert not any(c.passes for c in cells)  # ...none of which survive
    assert segment_skew_candidates(segment, _themes_for(segment), floor=30) == []


def test_segment_skew_dataset_12_shape_gives_no_findings():
    """BUG-041/050 at real scale: 24,961 answers with a Region across 12 regions; the theme has only 39 of
    them, spread at random. No region is unusual, whatever the per-region ratios look like."""
    import numpy as np

    rng = np.random.default_rng(12)
    sizes = [2080] * 12
    sizes[0] += 24961 - sum(sizes)
    region = rng.choice(12, size=39, p=[n / 24961 for n in sizes])
    counts = [int((region == g).sum()) for g in range(12)]
    segment = _segment({"Privacy": counts}, sizes)
    assert segment_skew_candidates(segment, _themes_for(segment), floor=30) == []


def test_label_confidence_segment_skew_thresholds():
    at_solid = Candidate("segment_skew", "x", 1, "X", count=100, score=1.0, numbers={"ratio": 2.0})
    assert label_confidence(at_solid) == "solid"
    at_solid_low_side = Candidate("segment_skew", "x", 1, "X", count=100, score=1.0, numbers={"ratio": 0.5})
    assert label_confidence(at_solid_low_side) == "solid"

    just_below_solid_ratio = Candidate("segment_skew", "x", 1, "X", count=100, score=1.0, numbers={"ratio": 1.9})
    assert label_confidence(just_below_solid_ratio) == "tentative"

    small_group = Candidate("segment_skew", "x", 1, "X", count=40, score=1.0, numbers={"ratio": 3.0})
    assert label_confidence(small_group) == "tentative"  # ratio is huge, but count is below the solid floor


# ---------------------------------------------------------------- score_correlation_candidates

def test_score_correlation_candidates_at_gate_and_just_below_gate():
    themes = [make_theme("A", 100, 0.0, list(range(100)))]

    at_gate = ScoreData(name="Score", bands=[
        ScoreBand(label="Low", mix=[10.0], sentiment=0.0, answers=50),
        ScoreBand(label="High", mix=[18.0], sentiment=0.0, answers=50),  # spread exactly 8.0
    ])
    candidates = score_correlation_candidates(at_gate, themes, floor=30)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.kind == "score_correlation" and c.theme_name == "A"
    assert c.numbers == {
        "column": "Score", "theme": "A", "low_band": "Low", "low_pct": 10.0,
        "high_band": "High", "high_pct": 18.0, "spread_pct": 8.0,
    }

    just_below = ScoreData(name="Score", bands=[
        ScoreBand(label="Low", mix=[10.0], sentiment=0.0, answers=50),
        ScoreBand(label="High", mix=[17.9], sentiment=0.0, answers=50),  # spread 7.9
    ])
    assert score_correlation_candidates(just_below, themes, floor=30) == []


def test_score_correlation_candidates_names_the_real_peak_band_even_if_its_the_middle_one():
    themes = [make_theme("A", 100, 0.0, list(range(100)))]
    score = ScoreData(name="Score", bands=[
        ScoreBand(label="Low", mix=[20.0], sentiment=0.0, answers=50),
        ScoreBand(label="Middle", mix=[40.0], sentiment=0.0, answers=50),  # the real peak
        ScoreBand(label="High", mix=[15.0], sentiment=0.0, answers=50),
    ])
    candidates = score_correlation_candidates(score, themes, floor=30)
    assert len(candidates) == 1
    c = candidates[0]
    assert c.numbers["high_band"] == "Middle" and c.numbers["high_pct"] == 40.0
    assert c.numbers["low_band"] == "High" and c.numbers["low_pct"] == 15.0
    assert c.numbers["spread_pct"] == 25.0


def test_score_correlation_candidates_drops_bands_under_floor():
    themes = [make_theme("A", 100, 0.0, list(range(100)))]
    score = ScoreData(name="Score", bands=[
        ScoreBand(label="Low", mix=[10.0], sentiment=0.0, answers=20),  # below floor=30
        ScoreBand(label="High", mix=[40.0], sentiment=0.0, answers=50),
    ])
    assert score_correlation_candidates(score, themes, floor=30) == []


def test_label_confidence_score_correlation_thresholds():
    at_solid = Candidate("score_correlation", "x", 1, "X", count=100, score=1.0, numbers={"spread_pct": 15.0})
    assert label_confidence(at_solid) == "solid"
    just_below_solid = Candidate("score_correlation", "x", 1, "X", count=100, score=1.0, numbers={"spread_pct": 14.9})
    assert label_confidence(just_below_solid) == "tentative"
    small_group = Candidate("score_correlation", "x", 1, "X", count=40, score=1.0, numbers={"spread_pct": 25.0})
    assert label_confidence(small_group) == "tentative"


# ---------------------------------------------------------------- trend_shift_candidates

def test_trend_shift_candidates_at_gate_and_just_below_gate():
    themes = [make_theme("A", 100, 0.0, list(range(100)))]
    at_gate = TrendData(
        labels=["P1", "P2", "P3"],
        series=[TrendSeries(theme="A", color="t1", values=[10.0, 10.0, 16.0])],  # change exactly +6.0
        sentiment=[0.0, 0.0, 0.0], hover_index=2, note="note",
    )
    candidates = trend_shift_candidates(at_gate, themes, floor=30, column="Date")
    assert len(candidates) == 1
    c = candidates[0]
    assert c.kind == "trend_shift" and c.theme_name == "A" and c.count == 100
    assert c.numbers == {
        "column": "Date", "theme": "A", "first_period": "P1", "first_pct": 10.0,
        "last_period": "P3", "last_pct": 16.0, "change_pct": 6.0, "direction": "rising",
    }

    just_below = TrendData(
        labels=["P1", "P2", "P3"],
        series=[TrendSeries(theme="A", color="t1", values=[10.0, 10.0, 15.9])],  # change 5.9
        sentiment=[0.0, 0.0, 0.0], hover_index=2, note="note",
    )
    assert trend_shift_candidates(just_below, themes, floor=30) == []


def test_trend_shift_candidates_fading_direction_and_default_column():
    themes = [make_theme("A", 100, 0.0, list(range(100)))]
    trend = TrendData(
        labels=["P1", "P2", "P3"],
        series=[TrendSeries(theme="A", color="t1", values=[20.0, 10.0, 5.0])],  # change -15.0
        sentiment=[0.0, 0.0, 0.0], hover_index=2, note="note",
    )
    candidates = trend_shift_candidates(trend, themes, floor=30)  # column omitted - defaults to ""
    assert len(candidates) == 1
    assert candidates[0].numbers["direction"] == "fading"
    assert candidates[0].numbers["change_pct"] == -15.0
    assert candidates[0].numbers["column"] == ""


def test_trend_shift_candidates_theme_size_below_floor_is_excluded():
    themes = [make_theme("A", 10, 0.0, list(range(10)))]  # size 10 < floor 30
    trend = TrendData(
        labels=["P1", "P2", "P3"],
        series=[TrendSeries(theme="A", color="t1", values=[10.0, 10.0, 40.0])],  # change +30.0, huge
        sentiment=[0.0, 0.0, 0.0], hover_index=2, note="note",
    )
    assert trend_shift_candidates(trend, themes, floor=30) == []


def test_label_confidence_trend_shift_thresholds():
    at_solid = Candidate("trend_shift", "x", 1, "X", count=100, score=1.0, numbers={"change_pct": 12.0})
    assert label_confidence(at_solid) == "solid"
    at_solid_falling = Candidate("trend_shift", "x", 1, "X", count=100, score=1.0, numbers={"change_pct": -12.0})
    assert label_confidence(at_solid_falling) == "solid"
    just_below_solid = Candidate("trend_shift", "x", 1, "X", count=100, score=1.0, numbers={"change_pct": 11.9})
    assert label_confidence(just_below_solid) == "tentative"
    small_group = Candidate("trend_shift", "x", 1, "X", count=40, score=1.0, numbers={"change_pct": 20.0})
    assert label_confidence(small_group) == "tentative"


# ---------------------------------------------------------------- candidate_findings backward-compat pin

def _dominant_and_longtail_themes_for_pin():
    return [
        make_theme("Cost", 600, -0.05, list(range(600))),
        make_theme("Charging", 150, -0.05, list(range(600, 750))),
        make_theme("Range", 100, -0.05, list(range(750, 850))),
        make_theme("Other", 150, -0.05, list(range(850, 1000))),
    ]


def test_candidate_findings_structured_none_is_byte_identical_to_omitting_it():
    """Backward-compat pin, mirroring test_build_report_data_structured_none_is_byte_identical_to_omitting_it
    above: candidate_findings's new `structured` keyword defaults to `None`, and passing it explicitly as
    `None` must produce identical output to omitting it entirely."""
    themes = _dominant_and_longtail_themes_for_pin()
    omitted = candidate_findings(themes)
    explicit_none = candidate_findings(themes, structured=None)
    assert omitted == explicit_none
    assert {c.kind for c in omitted} == {"dominant_theme", "long_tail"}


# ---------------------------------------------------------------- integration: all 5 kinds at once

def _all_five_kinds_dataset():
    """1000 rows across 4 themes (A/B/C/Other), engineered so the 2 pre-existing kinds (tone_contrast x3,
    dominant_theme, long_tail - 5 candidates, already filling MAX_CANDIDATES on their own) AND the 3 new
    kinds (segment_skew, score_correlation, trend_shift, via theme A's deliberately huge, easily-solid
    score/segment/date skews) all clear their gates at once. The new kinds' real-world effect sizes here
    are engineered far larger than the old tone_contrast candidates' tiny -1..+1-scale gaps (~0.2-0.4), so
    this is the scenario that would have caught the pre-existing cross-kind scale mismatch: an un-normalised
    score would always keep the 5 old candidates and never let a new one in, since they alone already fill
    the cap."""
    themes = [
        make_theme("A", 400, 0.30, list(range(0, 400))),
        make_theme("B", 250, -0.05, list(range(400, 650))),
        make_theme("C", 150, -0.05, list(range(650, 800))),
        make_theme("Other", 200, -0.05, list(range(800, 1000))),
    ]

    score = (
        [9] * 300 + [3] * 100  # A: mostly High - a big, solid score_correlation skew
        + [3] * 84 + [7] * 83 + [9] * 83  # B: roughly even across bands - no skew
        + [3] * 50 + [7] * 50 + [9] * 50  # C: roughly even - no skew
        + [3] * 67 + [7] * 67 + [9] * 66  # Other: roughly even - no skew
    )
    segment = (
        ["South"] * 350 + ["North"] * 50  # A: mostly South
        + ["North"] * 250  # B: entirely North - a big, solid segment_skew cell
        + ["South"] * 150  # C: entirely South
        + ["South"] * 200  # Other: entirely South
    )
    date = (
        ["2026-01-15"] * 50 + ["2026-02-15"] * 100 + ["2026-03-15"] * 250  # A: rises sharply Jan -> Mar
        + ["2026-01-15"] * 84 + ["2026-02-15"] * 83 + ["2026-03-15"] * 83  # B: flat
        + ["2026-01-15"] * 50 + ["2026-02-15"] * 50 + ["2026-03-15"] * 50  # C: flat
        + ["2026-01-15"] * 67 + ["2026-02-15"] * 67 + ["2026-03-15"] * 66  # Other: flat
    )
    assert len(score) == len(segment) == len(date) == 1000

    clean_df = pd.DataFrame({"Score": score, "Segment": segment, "Date": date})
    plan = _plan_with_score_step("Score", [0, 10])
    return clean_df, themes, plan


def test_candidate_findings_all_five_kinds_qualify_and_new_kinds_are_not_crowded_out():
    """The single most important new test in this whole stream: proves the score-scale-matching in
    app/findings_structured.py's B3 section actually worked, by constructing a pool where the 3 new kinds
    must compete directly against a pre-existing pool that already fills MAX_CANDIDATES on its own."""
    clean_df, themes, plan = _all_five_kinds_dataset()
    total = sum(t.size for t in themes)
    nodes = theme_nodes(themes, total)
    columns = {"score": ["Score"], "segment": ["Segment"], "date": ["Date"]}
    structured = build_structured_context(clean_df, plan, themes, nodes, columns, floor=30)
    assert structured.score is not None
    assert structured.segment is not None
    assert structured.trend is not None

    without_structured = candidate_findings(themes)
    assert len(without_structured) == MAX_CANDIDATES  # the old pool alone already fills the cap
    assert {c.kind for c in without_structured} == {"tone_contrast", "dominant_theme", "long_tail"}

    with_structured = candidate_findings(themes, structured=structured)
    assert len(with_structured) == MAX_CANDIDATES

    new_kinds = {"segment_skew", "score_correlation", "trend_shift"}
    kinds_present = {c.kind for c in with_structured}
    assert kinds_present & new_kinds, (
        "at least one new kind must have broken into the top MAX_CANDIDATES once structured data is given"
    )
    # a wrong (un-normalised, tone_contrast-like) scale would leave the ranked pool unchanged from the
    # old-only case, since 5 old candidates alone already fill the cap - so a real change here is the point.
    assert kinds_present != {"tone_contrast", "dominant_theme", "long_tail"}

    for c in with_structured:
        if c.kind == "score_correlation":
            assert c.numbers["spread_pct"] >= 8.0
        if c.kind == "segment_skew":
            assert c.numbers["ratio"] >= 1.5 or c.numbers["ratio"] <= 1 / 1.5
        if c.kind == "trend_shift":
            assert abs(c.numbers["change_pct"]) >= 6.0


def test_ratio_phrase_says_never_for_a_zero_share():
    from app.findings_structured import _ratio_phrase

    assert _ratio_phrase("Cost", "North", 0.0) == "North never mentions Cost."
    assert _ratio_phrase("Cost", "North", 0.5) == "North mentions Cost about half as often as the average respondent."


def test_looks_like_code_values_spots_barcodes_not_groups():
    from app.findings_structured import looks_like_code_values

    assert looks_like_code_values(["848719000000.0", "841667000000.0"])  # dataset 1's "ean" (BUG-051)
    assert looks_like_code_values(["00012345678", "00012345679", "Other"])
    assert not looks_like_code_values(["North", "South"])
    assert not looks_like_code_values(["2024", "2025"])  # years are short, a real grouping
    assert not looks_like_code_values([])


def test_build_structured_context_skips_a_barcode_segment_for_the_next_real_one_bug_051():
    """Dataset 1: a column holding EAN barcodes ("Product code" here) was confirmed as a segment and won the heatmap,
    so findings read "in 848719000000.0". It must be skipped, and the next segment candidate used."""
    n = 300
    clean_df = pd.DataFrame({
        "Product code": [848719000000.0 if i < 150 else 841667000000.0 for i in range(n)],
        "Region": ["North" if i < 170 else "South" for i in range(n)],
    })
    themes = [
        make_theme("A", 150, 0.3, list(range(0, 150))),
        make_theme("B", 150, -0.1, list(range(150, 300))),
    ]
    nodes = theme_nodes(themes, total_answered=300)
    columns = {"score": [], "segment": ["Product code", "Region"], "date": []}

    context = build_structured_context(clean_df, None, themes, nodes, columns, floor=30)

    assert context.segment_column_name == "Region"
    assert {g.label for g in context.segment.groups} == {"North", "South"}
