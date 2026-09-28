"""app/findings_structured.py (Part B1 - banding foundation only). Plain-assert, no-mocking style matching
tests/test_findings.py - these functions are pure (no DB, no pandas input), so there is nothing to fake."""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.findings_structured import Band, apply_bands, band_age, band_dates, band_quartiles, band_score


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
