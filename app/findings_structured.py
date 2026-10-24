"""Banding foundation for score/segment/date findings (SPEC.md build-order step 3, part B1 of the plan -
see `docs/DECISIONS.md`/the session plan for the full B1/B2/B3 staging). This module is deliberately pure:
plain Python values in, plain Python values out - no database access, no pandas dataframes as input, no
knowledge of `Theme`/`Dataset`/`Column`. Turning a `numeric`/`score`/`date` spreadsheet column into
readable groups ("bands", SPEC.md section 9.2) is a small, easily-tested piece of math on its own; the
cross-tab plumbing that joins these bands back to real rows and themes (B2) and the new candidate-finding
kinds built on top of that (B3) are separate, later streams - this module knows nothing about either.

Four kinds of banding are covered, matching SPEC.md section 9.2 and this app's own existing conventions:
  - `band_score`: a 0-10 (or similar) "likelihood to buy"-style rating. Reuses the NPS detractor/passive/
    promoter convention (0-6 / 7-8 / 9-10) `app/fixtures/ev_sample.py`'s `ScoreData` already establishes
    for a 0-10 scale, generalized for other scales.
  - `band_age`: the fixed 18-24/25-34/.../65+ bands SPEC.md section 9.2 names explicitly for age.
  - `band_quartiles`: quartile cuts for income and other skewed numeric measures, "so each group has
    enough answers" (SPEC.md section 9.2), with a documented fallback for repeated-value data.
  - `band_dates`: adaptive month/week/day periods for a trend chart, picking the coarsest granularity that
    still yields at least 3 periods (finer granularity for a shorter date spread).

`apply_bands` then maps raw per-row values against a list of `Band`s. It is the one function all four
banding functions feed into, and it is deliberately strict: a value that does not fall inside any band
(out of range, `None`, or `NaN`) is left out of the result entirely, never coerced into a nearest band -
this is how out-of-range or missing values get correctly excluded from a chart's denominator downstream,
rather than silently distorting a group's count.

`segment` columns need none of this (SPEC.md: already a small set of category strings) and are out of
scope here entirely - see the plan's B1 section.
"""
from __future__ import annotations

import calendar
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Sequence

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from .chart_data import (
    BinCell, BinnedGridData, CategoryAvg, CategoryAvgData, FreqData, FreqItem, GroupTrendData,
    GroupTrendSeries, ScoreBand, ScoreData, SegmentData, SegmentGroup, SegmentRow, TrendData, TrendSeries,
)
from .models import Column, Theme

__all__ = [
    "Band", "band_score", "band_age", "band_quartiles", "band_dates", "apply_bands",
    "StructuredContext", "theme_answer_rows", "build_score_data", "build_segment_data", "build_trend_data",
    "build_frequency_data", "build_category_avg_data", "build_group_trend_data", "build_binned_grid_data",
    "pick_structured_columns", "build_structured_context", "resolve_filter_rows", "segment_skew_candidates",
    "score_correlation_candidates", "trend_shift_candidates",
]


@dataclass
class Band:
    """One banded group with a real-value label. `lo`/`hi` are inclusive bounds used by `apply_bands`
    (`None` means open on that side - only `band_age`'s bottom "<18" band and top "65+" band ever use
    that, every other band produced by this module is bounded on both ends). `label` is always built from
    real cut values, never a bare index or an opaque bucket name (SPEC.md section 9.2: "Bands are always
    labelled with real values")."""

    label: str
    lo: float | None
    hi: float | None


def _fmt_num(x: float) -> str:
    """Whole numbers print without a trailing ".0"; anything else prints with Python's general "%g"-style
    formatting. Shared by every band-label helper below so a "6" never turns into "6.0" or "6.00" next to
    the "7-8" it borders."""
    return str(int(x)) if float(x) == int(x) else f"{x:g}"


def _range_label(a: float, b: float) -> str:
    """"6" for a single-value band, "0-6" for a range - never "6-6"."""
    return _fmt_num(a) if a == b else f"{_fmt_num(a)}-{_fmt_num(b)}"


# ==================================================================== band_score

def band_score(scale: tuple[int, int]) -> list[Band]:
    """Bands a confirmed score scale (`scale = (lo, hi)`, e.g. `(0, 10)` or `(1, 5)`) into 2 or 3 real-
    valued bands. This function never sees the actual column data, only its scale - a caller resolves the
    scale separately (the plan's B2 step reads it from `CleaningPlan`'s `check_score_range` step).

    A `hi - lo == 10` scale (the common 0-10 case) gets the exact NPS detractor/passive/promoter split
    this app already uses in `app/fixtures/ev_sample.py`'s `ScoreData`: "Low (lo-lo+6)", "Middle
    (lo+7-lo+8)", "High (lo+9-hi)" - so a 0-10 score column bands exactly the way the EV sample fixture's
    hand-built bands already do, not a fresh even 3-way split that would disagree with it.

    Any other scale with `hi - lo >= 3` gets 3 integer bands that are as equal as integer math allows,
    computed by giving any remainder to the low band first, then the high band (never the middle) - this
    mirrors the shape of the NPS split above, where the low band is the largest or tied-largest and the
    middle band is the smallest, rather than a plain equal thirds. For `(1, 5)`: "Low (1-2)", "Middle (3)",
    "High (4-5)". For `(1, 7)`: "Low (1-3)", "Middle (4-5)", "High (6-7)".

    A very narrow scale (`hi - lo < 3`, e.g. `(1, 2)`) does not have enough integers to split three ways
    at all, so this falls back to 2 bands split at the midpoint: "Low", "High".

    Every band's `lo`/`hi` is a real, non-`None` number on both ends - a score scale is always bounded, so
    there is never an "open" band here (unlike `band_age`'s "65+")."""
    lo, hi = scale
    span = hi - lo

    if span == 10:
        return [
            Band(f"Low ({_range_label(lo, lo + 6)})", lo, lo + 6),
            Band(f"Middle ({_range_label(lo + 7, lo + 8)})", lo + 7, lo + 8),
            Band(f"High ({_range_label(lo + 9, hi)})", lo + 9, hi),
        ]

    if span < 3:
        mid = (lo + hi) / 2
        low_hi = math.floor(mid)
        high_lo = min(low_hi + 1, hi)
        return [
            Band(f"Low ({_range_label(lo, low_hi)})", lo, low_hi),
            Band(f"High ({_range_label(high_lo, hi)})", high_lo, hi),
        ]

    n = hi - lo + 1  # count of integers covered, e.g. (1, 5) -> 5
    base = n // 3
    rem = n % 3
    low_size = base + (1 if rem >= 1 else 0)
    high_size = base + (1 if rem >= 2 else 0)
    low_hi = lo + low_size - 1
    mid_lo = low_hi + 1
    mid_hi = hi - high_size
    high_lo = mid_hi + 1
    return [
        Band(f"Low ({_range_label(lo, low_hi)})", lo, low_hi),
        Band(f"Middle ({_range_label(mid_lo, mid_hi)})", mid_lo, mid_hi),
        Band(f"High ({_range_label(high_lo, hi)})", high_lo, hi),
    ]


# ==================================================================== band_age

_AGE_BANDS: list[tuple[int, int | None]] = [
    (18, 24), (25, 34), (35, 44), (45, 54), (55, 64), (65, None),
]


def band_age(min_age: float, max_age: float) -> list[Band]:
    """SPEC.md section 9.2's standard age bands: 18-24, 25-34, 35-44, 45-54, 55-64, 65+ - fixed cut
    points, not derived from the data (unlike `band_quartiles`), matching how age bands are always
    presented regardless of a particular dataset's actual spread. `max_age` is accepted for a symmetrical,
    self-documenting signature (a caller always has both bounds handy from profiling) but does not change
    the output - the top band is always open above ("65+", `hi=None`) rather than clipped to the data's
    real maximum.

    When `min_age` is meaningfully below 18 (`min_age < 18` - respondents who are legitimately teenagers
    or younger, or bad data that slipped past validation either way), an extra open-below "<18" band is
    prepended so those rows still land somewhere instead of being silently excluded by `apply_bands`."""
    bands: list[Band] = []
    if min_age < 18:
        bands.append(Band("<18", None, 17))
    for lo, hi in _AGE_BANDS:
        label = f"{lo}+" if hi is None else f"{lo}-{hi}"
        bands.append(Band(label, lo, hi))
    return bands


# ==================================================================== band_quartiles

def _money(x: float) -> str:
    return f"${round(x):,}"


def _band_label(a: float, b: float, unit: str | None) -> str:
    fmt = _money if unit == "currency" else _fmt_num
    a_s, b_s = fmt(a), fmt(b)
    return a_s if a_s == b_s else f"{a_s}-{b_s}"


def band_quartiles(values: Sequence[float], unit: str | None = None) -> list[Band]:
    """Quartile bands (4 groups, roughly equal answer counts) for income and other skewed numeric
    measures, per SPEC.md section 9.2 - cut points come from `pandas.Series(values).quantile([.25, .5,
    .75])` on the real observed values, then labelled with those real cut values (never invented round
    numbers). `unit == "currency"` prefixes labels with "$" and groups digits with commas (e.g.
    "$24,000-51,000"); anything else prints plain numbers.

    Raises `ValueError` if fewer than 2 distinct values are present - there is nothing to band (every
    value would fall in one degenerate group no matter where the cuts go).

    Degenerate/repeated-value handling: real survey data often has many respondents reporting the exact
    same income (round numbers, a capped "or more" response, and so on), which can make two or more of the
    three quartile cut points come out identical. Emitting the naive 4 bands in that case would produce a
    zero-width band and/or two bands with the same numeric-range label, both of which are useless to a
    reader. When that happens (`q1`, `q2`, `q3` are not all distinct), this falls back to a 2-band split at
    the overall median instead - always exactly 2 real, non-duplicate, non-empty bands, since the median of
    at least 2 distinct values can equal at most one of the data's min/max, never both."""
    clean = [v for v in values if v is not None]
    distinct = sorted(set(clean))
    if len(distinct) < 2:
        raise ValueError("band_quartiles needs at least 2 distinct values to band.")

    s = pd.Series(clean, dtype="float64")
    lo_v, hi_v = distinct[0], distinct[-1]
    q1, q2, q3 = (float(v) for v in s.quantile([0.25, 0.5, 0.75]))

    if len({q1, q2, q3}) < 3:
        median = float(s.median())
        return [
            Band(_band_label(lo_v, median, unit), lo_v, median),
            Band(_band_label(median, hi_v, unit), median, hi_v),
        ]

    cuts = [lo_v, q1, q2, q3, hi_v]
    return [Band(_band_label(cuts[i], cuts[i + 1], unit), cuts[i], cuts[i + 1]) for i in range(4)]


# ==================================================================== band_dates

def _spans_multiple_years(years: Sequence[int]) -> bool:
    return len(set(years)) > 1


def _month_periods(lo_d: date, hi_d: date) -> list[tuple[int, int]]:
    periods = []
    y, m = lo_d.year, lo_d.month
    while (y, m) <= (hi_d.year, hi_d.month):
        periods.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return periods


def _month_band(y: int, m: int, include_year: bool) -> Band:
    start = date(y, m, 1)
    end = date(y, m, calendar.monthrange(y, m)[1])
    label = start.strftime("%b")
    if include_year:
        label = f"{label} {y}"
    return Band(label, float(start.toordinal()), float(end.toordinal()))


def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())  # Monday of that date's week


def _week_periods(lo_d: date, hi_d: date) -> list[date]:
    periods = []
    cur = _week_start(lo_d)
    last = _week_start(hi_d)
    while cur <= last:
        periods.append(cur)
        cur += timedelta(days=7)
    return periods


def _week_band(start: date, include_year: bool) -> Band:
    end = start + timedelta(days=6)
    label = f"{start.strftime('%b')} {start.day}"
    if include_year:
        label = f"{label} {start.year}"
    return Band(label, float(start.toordinal()), float(end.toordinal()))


def _day_periods(lo_d: date, hi_d: date) -> list[date]:
    periods = []
    cur = lo_d
    while cur <= hi_d:
        periods.append(cur)
        cur += timedelta(days=1)
    return periods


def _day_band(d: date, include_year: bool) -> Band:
    label = f"{d.strftime('%b')} {d.day}"
    if include_year:
        label = f"{label} {d.year}"
    ordinal = float(d.toordinal())
    return Band(label, ordinal, ordinal)


def _day_month(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


def band_dates(values: Sequence[date]) -> tuple[list[Band], str]:
    """Bands real `date` objects (parsing is the caller's job - this function never sees strings) into
    time periods for a trend chart, picking the coarsest granularity that still yields at least 3 periods
    across the observed min-to-max span, tried in this order: month, then week, then day. A short survey
    window (a few weeks of responses) would produce only 1-2 monthly buckets - not enough for a trend line
    to say anything - so this backs off to week, and then day, until there is enough to show.

    Each `Band` covers one whole calendar period (month/week/day), `lo`/`hi` stored as
    `date.toordinal()` so they compare as plain floats against `apply_bands`' raw values (the caller must
    convert its own date values to `.toordinal()` the same way before calling `apply_bands`). Period
    boundaries are the real calendar period (e.g. the 1st to the last day of the month), not clipped to
    the observed data's exact min/max, so every date within a covered period lands in that band even if no
    response happened to fall on the period's very first or last day.

    Labels are short month names ("Jan") or "Mon D" ("Jan 5") for week/day, matching
    `app/fixtures/ev_sample.py`'s `TrendData` label style. The year is appended only when the date range
    spans more than one calendar year (short labels stay unambiguous within a single year, matching that
    fixture's plain "Jan".."Dec" precedent). The returned `note` is a short sentence describing the chosen
    granularity and span (e.g. "Monthly, January to December."), matching `TrendData.note`'s existing style
    exactly for the month case.

    Raises `ValueError` if fewer than 3 periods can be formed even at daily granularity - the data does
    not have enough date spread to band into a trend at all (e.g. all dates identical, or only 1-2 distinct
    dates)."""
    clean = sorted(v for v in values if v is not None)
    distinct = sorted(set(clean))
    if len(distinct) < 2:
        raise ValueError("band_dates needs at least 2 distinct dates to band.")
    lo_d, hi_d = distinct[0], distinct[-1]

    months = _month_periods(lo_d, hi_d)
    if len(months) >= 3:
        include_year = _spans_multiple_years([y for y, _ in months])
        bands = [_month_band(y, m, include_year) for y, m in months]
        first = date(*months[0], 1).strftime("%B") + (f" {months[0][0]}" if include_year else "")
        last = date(*months[-1], 1).strftime("%B") + (f" {months[-1][0]}" if include_year else "")
        return bands, f"Monthly, {first} to {last}."

    weeks = _week_periods(lo_d, hi_d)
    if len(weeks) >= 3:
        include_year = _spans_multiple_years([d.year for d in weeks])
        bands = [_week_band(start, include_year) for start in weeks]
        last_end = weeks[-1] + timedelta(days=6)
        return bands, f"Weekly, {_day_month(weeks[0])} to {_day_month(last_end)}."

    days = _day_periods(lo_d, hi_d)
    if len(days) >= 3:
        include_year = _spans_multiple_years([d.year for d in days])
        bands = [_day_band(d, include_year) for d in days]
        return bands, f"Daily, {_day_month(days[0])} to {_day_month(days[-1])}."

    raise ValueError("Not enough date spread to band even at daily granularity (need at least 3 days).")


# ==================================================================== apply_bands

def apply_bands(raw_by_row: dict[int, float], bands: list[Band]) -> dict[int, str]:
    """Maps each row's raw numeric value to the label of the first `Band` it falls inside (inclusive on
    both ends where a bound is not `None`), checking `bands` in the order given. A row whose value is
    `None`, `NaN`, or does not fall inside any band is left out of the returned dict entirely - it is never
    coerced into the nearest band. This is deliberate: it is how out-of-range or missing values get
    correctly excluded from a chart's denominator downstream, rather than quietly padding a group they do
    not really belong to. For `band_dates`' output, the caller is expected to have already converted its
    date values to the same `.toordinal()` float representation the bands themselves use - this function
    only ever compares plain floats, it never touches a `date` object."""
    result: dict[int, str] = {}
    for row, value in raw_by_row.items():
        if value is None:
            continue
        if isinstance(value, float) and math.isnan(value):
            continue
        for band in bands:
            lo_ok = band.lo is None or value >= band.lo
            hi_ok = band.hi is None or value <= band.hi
            if lo_ok and hi_ok:
                result[row] = band.label
                break
    return result


# ==================================================================== B2 - cross-tab + data plumbing
#
# Everything below joins B1's bands (and raw segment/date columns) back to real cleaned-dataframe rows and
# `Theme` rows, producing the exact `ScoreData`/`SegmentData`/`TrendData` shapes `app/chart_data.py` and
# `app/charts.py`'s `f_byscore`/`f_heatmap`/`f_trend` already render. No new banding math lives here - only
# tallying, suppression, and formatting into those dataclasses.
#
# Sentiment approximation (documented once, here, rather than repeated per function below): no per-row
# sentiment is persisted anywhere in this codebase (only each `Theme.sentiment`, one aggregate float per
# theme, exists - see docs/DECISIONS.md's 2026-09-25 entry, "Per-answer sentiment storage: NOT persisted").
# So every per-band/per-period sentiment value this module computes is necessarily a count-weighted average
# of each theme's *aggregate* `Theme.sentiment` over the rows landing in that band/period - the same
# approximation `app/findings.py::_overall_sentiment` already makes globally, just re-weighted per cell -
# never a true per-row recomputation.


@dataclass
class StructuredContext:
    """Everything `build_report_data` needs to fill in the score/segment/trend charts for one report,
    assembled once by `build_structured_context` below. A field stays at its default (`None`/`""`) when
    that column was absent, failed to resolve a scale/date spread, or produced no chart-worthy data after
    suppression - `build_report_data` falls back to today's empty placeholders in exactly that case, so a
    dataset with no usable score/segment/date column behaves byte-for-byte like it did before this module
    existed."""

    score: ScoreData | None = None
    score_column_name: str = ""
    segment: SegmentData | None = None
    segment_column_name: str = ""
    trend: TrendData | None = None
    trend_column_name: str = ""
    frequency: FreqData | None = None
    frequency_column_name: str = ""
    category_avg: CategoryAvgData | None = None
    group_trend: GroupTrendData | None = None
    binned_grid: BinnedGridData | None = None

    # Raw (pre-band/pre-cap), per-row values behind whichever candidate column won each role, stashed here
    # purely so `resolve_filter_rows` (below) can turn a filter request into a row-index set without
    # re-reading the cleaned dataframe a third time. `None` when that role has no winning column - mirrors
    # the corresponding `*_column_name == ""` case exactly. Only meaningful on an UNFILTERED context (the
    # one `_render_report` builds first, see `app/api_report.py`) - populated harmlessly but never read
    # again on a second, already-filtered `build_structured_context` call.
    score_raw_by_row: dict[int, float] | None = None
    score_scale: tuple[int, int] | None = None
    segment_raw_by_row: dict[int, str] | None = None
    date_raw_by_row: dict[int, date] | None = None


def theme_answer_rows(themes: list["Theme"]) -> list[int]:
    """Every cleaned-dataframe row index that belongs to ANY theme (i.e. every open-ended answer that got
    clustered into a theme at all, including "Other"). Extracted so this exact set - `sorted({r for t in
    themes for r in (t.answer_refs or [])})` - is computed once, in one place, rather than duplicated per
    caller (see `app/api_report.py::_answer_lengths_for`'s identical inline pattern, which this generalizes
    for the score/segment/date cross-tabs below)."""
    return sorted({r for t in themes for r in (t.answer_refs or [])})


# -------------------------------------------------------------------- build_score_data

def _cross_tab_bands(
    column: str, bands: list[Band], raw_by_row: dict[int, float],
    nodes: list["ThemeNode"], floor: int,
) -> "ScoreData | None":
    """Shared cross-tab core behind `build_score_data` (bands from `band_score`) and `build_numeric_data`
    (bands from `band_quartiles`) - the banding scheme differs, but "for each surviving band, what % of
    that band's answers came from each theme" is identical math either way, so it lives once here rather
    than twice. For each surviving band (per the given `bands`), computes `ScoreBand.mix` (in `nodes`
    order so it lines up positionally with `ReportData.themes`), a count-weighted-average sentiment, and
    the band's total answer count. A band whose total answer count is below `floor` is dropped entirely
    (not shown as a degenerate near-empty band); if fewer than 2 bands survive, returns `None` - nothing
    meaningful to show, mirroring SPEC.md's chart skip-condition philosophy. See the module-level note
    above for the sentiment approximation this uses."""
    band_by_row = apply_bands(raw_by_row, bands)
    if not band_by_row:
        return None

    band_totals: dict[str, int] = {b.label: 0 for b in bands}
    for label in band_by_row.values():
        band_totals[label] += 1

    # theme_name -> band_label -> count-of-that-theme's-rows-in-that-band
    per_theme: dict[str, dict[str, int]] = {}
    for node in nodes:
        counts = {b.label: 0 for b in bands}
        for r in node.answer_refs:
            label = band_by_row.get(r)
            if label is not None:
                counts[label] += 1
        per_theme[node.name] = counts

    surviving = [b for b in bands if band_totals[b.label] >= floor]
    if len(surviving) < 2:
        return None

    result_bands: list[ScoreBand] = []
    for b in surviving:
        total = band_totals[b.label]
        mix = [round(100 * per_theme[node.name][b.label] / total, 1) for node in nodes]
        weighted_sentiment = 0.0
        for node in nodes:
            weighted_sentiment += node.sentiment * per_theme[node.name][b.label]
        result_bands.append(ScoreBand(
            label=b.label, mix=mix, sentiment=round(weighted_sentiment / total, 3), answers=total,
        ))

    return ScoreData(name=column, bands=result_bands)


def build_score_data(
    column: str, scale: tuple[int, int], raw_by_row: dict[int, float],
    nodes: list["ThemeNode"], floor: int,
) -> "ScoreData | None":
    """A `score`-kind column (fixed 0-10-style scale) cross-tabbed against themes - see `_cross_tab_bands`
    for the actual math, shared with `build_numeric_data` below."""
    return _cross_tab_bands(column, band_score(scale), raw_by_row, nodes, floor)


def build_numeric_data(
    column: str, raw_by_row: dict[int, float], nodes: list["ThemeNode"], floor: int,
    unit: str | None = None,
) -> "ScoreData | None":
    """A `numeric`-kind column (no fixed scale - age, income, or any other free numeric measure) cross-
    tabbed against themes, reusing `_cross_tab_bands`'s exact same math `build_score_data` uses, just
    banded via `band_quartiles` (skewed-numeric quartile cuts, SPEC.md section 9.2) instead of a fixed
    scale - `numeric` columns are never confirmed with a `check_score_range` scale, so there is no fixed
    scale to band against. Rendered via the same `f_byscore` chart `score`-kind columns already use (see
    `app/charts.py`'s `TITLES`/`FRAMES`) - no new chart type needed, since both are "a numeric measure cut
    into bands, themes mixed inside each" (`ScoreData`'s own shape). Returns `None` if `band_quartiles`
    can't band this column (fewer than 2 distinct values) rather than raising - same "skip this candidate,
    try the next" contract every other `build_*_data` function here already has."""
    try:
        bands = band_quartiles(list(raw_by_row.values()), unit)
    except ValueError:
        return None
    return _cross_tab_bands(column, bands, raw_by_row, nodes, floor)


# -------------------------------------------------------------------- build_segment_data

def _ratio_phrase(theme_name: str, group_label: str, ratio: float) -> str:
    """Plain-English cell tooltip, matching SPEC.md's own example style and `app/fixtures/ev_sample.py`'s
    `SegmentData.highlight_text` verbatim for the ratio > 1 case. Below 1, a clean "half as often" reads
    better than a decimal for ratios near 0.5; anything else below 1 just states the decimal ratio rather
    than reaching for a fraction word that would not fit every value cleanly."""
    if 0.45 <= ratio <= 0.55:
        return f"{group_label} mentions {theme_name} about half as often as the average respondent."
    return f"{group_label} mentions {theme_name} {ratio:.1f} times as often as the average respondent."


def build_segment_data(
    column: str, raw_by_row: dict[int, str], nodes: list["ThemeNode"], floor: int,
    heatmap_group_floor: int = 100, max_rows: int = 7, max_groups: int = 8,
) -> "SegmentData | None":
    """Cross-tabs an already-capped set of segment/category groups (`raw_by_row`'s values - capping to the
    `max_groups` largest groups is the caller's job, see `build_structured_context`, not this function's:
    it uses whatever groups are already present in `raw_by_row`) against themes, for the segment/age
    heatmap.

    `floor` is accepted (kept in this function's signature only for a uniform call shape with
    `build_score_data`/`build_trend_data`) but NOT what gates a group here: SPEC.md's heatmap-specific skip
    condition ("any segment under 100 answers") is stricter than the general suppression floor, so
    `heatmap_group_floor` (default 100) is what actually drops a group. `max_groups` is likewise accepted
    for the same signature-uniformity reason; the real capping to the largest groups already happened
    before this function was called.

    Groups under `heatmap_group_floor` are dropped; if fewer than 2 groups survive, returns `None`. Rows
    are the `max_rows` largest themes from `nodes` (all of them if fewer exist). `SegmentRow.overall` is
    the theme's real overall share (`ThemeNode.share`), never a value recomputed from this subset.
    `highlight` is the single (row, group) cell with the largest deviation from that row's overall share,
    scored as `max(ratio, 1/ratio)` where `ratio = cell_value / overall` (a cell whose value is exactly 0
    is treated as the most extreme possible deviation, since "never mentioned in this group at all" is
    itself a strong signal); rows whose `overall` is 0 are skipped entirely to avoid dividing by zero.
    """
    group_totals: dict[str, int] = {}
    for v in raw_by_row.values():
        group_totals[v] = group_totals.get(v, 0) + 1

    surviving_groups = sorted(
        (g for g, n in group_totals.items() if n >= heatmap_group_floor),
        key=lambda g: group_totals[g], reverse=True,
    )
    if len(surviving_groups) < 2:
        return None

    picked_nodes = nodes[:max_rows]

    counts: dict[str, dict[str, int]] = {}
    for node in picked_nodes:
        c = {g: 0 for g in surviving_groups}
        for r in node.answer_refs:
            g = raw_by_row.get(r)
            if g in c:
                c[g] += 1
        counts[node.name] = c

    rows: list[SegmentRow] = []
    for node in picked_nodes:
        values = [round(100 * counts[node.name][g] / group_totals[g], 1) for g in surviving_groups]
        rows.append(SegmentRow(theme=node.name, overall=node.share, values=values))

    best: tuple[int, int] | None = None
    best_score = -1.0
    best_ratio = 0.0
    for ri, row in enumerate(rows):
        if row.overall == 0:
            continue
        for gi, v in enumerate(row.values):
            ratio = v / row.overall
            score = float("inf") if ratio == 0 else max(ratio, 1 / ratio)
            if score > best_score:
                best_score = score
                best = (ri, gi)
                best_ratio = ratio

    highlight_text = ""
    if best is not None:
        ri, gi = best
        highlight_text = _ratio_phrase(rows[ri].theme, surviving_groups[gi], best_ratio)

    return SegmentData(
        name=column,
        groups=[SegmentGroup(label=g, n=group_totals[g]) for g in surviving_groups],
        rows=rows,
        highlight=best,
        highlight_text=highlight_text,
    )


# -------------------------------------------------------------------- build_frequency_data (chart-block
# stream, 2026-10-24: `ranked_answers`/`ranked_list` - a frequency table for a SECOND, short-answer text
# column, distinct from the main open-ended column every other chart in this stream reads)

def _merge_key(value: str) -> str:
    """Case- and simple-plural-insensitive grouping key: "Teacher"/"teacher"/"teachers" all collapse to one
    group. Deliberately NOT a full lemmatizer/stemmer (no new dependency, no model call) - a plain trailing
    "s" strip catches the large majority of real spelling-variant duplicates this block's own example
    ("Teacher and Nurse... merged for spelling and plurals") describes, at the cost of occasionally
    under-merging a genuine irregular plural ("children"/"child") - an honest, documented limit, not a
    silent one."""
    v = value.strip().lower()
    return v[:-1] if v.endswith("s") and len(v) > 3 else v


def build_frequency_data(
    column: str, raw_by_row: dict[int, str], floor: int, max_items: int = 8,
) -> "FreqData | None":
    """A real answer-frequency table for a short-answer column (occupation, product name, free-form
    one-word/few-word answers) - distinct from the main open-ended column's theme clustering, which this
    function has no involvement in. Groups by `_merge_key` (spelling/case/simple-plural merge), keeps the
    most-common ORIGINAL casing/form as the display label per group, and drops any group under `floor`
    (the same general suppression floor every other candidate-building step in this app already uses - no
    block-specific stricter floor the way the segment heatmap has one, since this is a plain ranked list,
    not a per-cell breakdown someone could be singled out in).

    Returns `None` when fewer than 2 groups survive the floor (an un-rankable "everyone said something
    different" list is not a real finding) - same "a valid empty result, not an error" contract every
    other `build_*_data` function here already follows.
    """
    groups: dict[str, dict[str, int]] = {}  # merge key -> {display form -> count}
    answered = 0
    for v in raw_by_row.values():
        if not isinstance(v, str) or not v.strip():
            continue
        answered += 1
        key = _merge_key(v)
        forms = groups.setdefault(key, {})
        forms[v.strip()] = forms.get(v.strip(), 0) + 1

    ranked = sorted(
        ((key, forms) for key, forms in groups.items() if sum(forms.values()) >= floor),
        key=lambda kf: sum(kf[1].values()), reverse=True,
    )
    if len(ranked) < 2:
        return None
    if answered <= 0:
        return None

    top = ranked[:max_items]
    items = []
    for _, forms in top:
        total = sum(forms.values())
        label = max(forms, key=forms.get)  # most-common original casing/form, never invented
        merged = len(forms) - 1  # how many OTHER spellings/forms folded into this one
        items.append(FreqItem(label=label, pct=round(total / answered * 100, 1), merged=merged))

    top_label = items[0].label
    merged_total = sum(i.merged for i in items)
    footnote = (
        f"{merged_total} spelling or plural variant{'s' if merged_total != 1 else ''} merged into the "
        f"{len(items)} answers shown." if merged_total else f"{len(items)} distinct answers shown, no spelling variants merged."
    )
    return FreqData(question=column, answered=answered, items=items, highlight=top_label, footnote=footnote)


# -------------------------------------------------------------------- build_category_avg_data (chart-block
# stream, 2026-10-24, batch 2: vs_average - a number column's average, split by a short_text category)

def build_category_avg_data(
    category_col: str, number_col: str,
    category_raw: dict[int, str], number_raw: dict[int, float],
    floor: int, max_categories: int = 8,
) -> "CategoryAvgData | None":
    """Reuses `_merge_key`'s case/plural grouping (same as `build_frequency_data` - these two commonly
    share the SAME short_text column, so a category should merge the same way in both blocks). Only rows
    with BOTH a real category value and a real number value count toward a category's average or the
    overall average - a row missing either tells us nothing about this specific pairing, even if it has
    one of the two values. Ranked by average descending (the design's own example: "Software engineers
    and managers earn well above average" - the point is the ordering, not alphabetical category order).

    Returns `None` when fewer than 2 categories survive the floor, or no row has both values at all - the
    same "a valid empty result, not an error" contract every other `build_*_data` function here follows.
    """
    rows = set(category_raw) & set(number_raw)
    if not rows:
        return None
    overall_avg = sum(number_raw[r] for r in rows) / len(rows)

    groups: dict[str, dict[str, list[float]]] = {}  # merge key -> {display form -> [values]}
    for r in rows:
        v = category_raw[r]
        if not isinstance(v, str) or not v.strip():
            continue
        key = _merge_key(v)
        forms = groups.setdefault(key, {})
        forms.setdefault(v.strip(), []).append(number_raw[r])

    def _total_n(forms: dict[str, list[float]]) -> int:
        return sum(len(vs) for vs in forms.values())

    ranked = sorted(
        ((key, forms) for key, forms in groups.items() if _total_n(forms) >= floor),
        key=lambda kf: sum(v for vs in kf[1].values() for v in vs) / _total_n(kf[1]), reverse=True,
    )
    if len(ranked) < 2:
        return None

    items = []
    for _, forms in ranked[:max_categories]:
        label = max(forms, key=lambda f: len(forms[f]))  # most-common original casing/form
        all_values = [v for vs in forms.values() for v in vs]
        items.append(CategoryAvg(label=label, avg=round(sum(all_values) / len(all_values), 2), n=len(all_values)))

    return CategoryAvgData(category_name=category_col, number_name=number_col, overall_avg=round(overall_avg, 2), items=items)


# -------------------------------------------------------------------- build_trend_data

def build_trend_data(
    column: str, raw_by_row: dict[int, float], nodes: list["ThemeNode"],
    date_bands: list["Band"], date_note: str, floor: int, max_series: int = 5,
) -> "TrendData | None":
    """Cross-tabs a date column (already converted to `.toordinal()` floats by the caller, see
    `build_structured_context`) against themes, for the trend line chart. `date_bands`/`date_note` are
    `band_dates(...)`'s own output - this function only applies them (`apply_bands`) and tallies, it does
    not re-derive granularity.

    A period whose total row count is below 30 (SPEC.md's trend-specific skip condition) is dropped; if
    fewer than 3 periods survive, returns `None`. `series` covers the `max_series` largest themes from
    `nodes` (all of them if fewer exist); each `TrendSeries.values[i]` is that theme's share (%) of period
    `i`'s surviving answers. `sentiment[i]` is the same count-weighted-average-of-`Theme.sentiment`
    approximation `build_score_data` uses for bands, computed per period across ALL themes (not just the
    picked series) - matching how `app/findings.py::_overall_sentiment` already blends sentiment globally,
    just re-weighted per period. `hover_index` is always the last surviving period's index."""
    period_by_row = apply_bands(raw_by_row, date_bands)
    if not period_by_row:
        return None

    period_totals: dict[str, int] = {b.label: 0 for b in date_bands}
    for label in period_by_row.values():
        period_totals[label] += 1

    surviving_periods = [b.label for b in date_bands if period_totals[b.label] >= 30]
    if len(surviving_periods) < 3:
        return None

    # tallied across ALL themes (not just the picked series) - sentiment[i] needs the full picture even
    # though only the top max_series themes are plotted as lines.
    counts: dict[str, dict[str, int]] = {}
    for node in nodes:
        c = {p: 0 for p in surviving_periods}
        for r in node.answer_refs:
            p = period_by_row.get(r)
            if p in c:
                c[p] += 1
        counts[node.name] = c

    picked_nodes = nodes[:max_series]
    series: list[TrendSeries] = []
    for node in picked_nodes:
        values = []
        for p in surviving_periods:
            total = period_totals[p]
            values.append(round(100 * counts[node.name][p] / total, 1) if total else 0.0)
        series.append(TrendSeries(theme=node.name, color=node.color, values=values))

    sentiment: list[float] = []
    for p in surviving_periods:
        total = period_totals[p]
        weighted = 0.0
        for node in nodes:
            weighted += node.sentiment * counts[node.name][p]
        sentiment.append(round(weighted / total, 3) if total else 0.0)

    return TrendData(
        labels=surviving_periods, series=series, sentiment=sentiment,
        hover_index=len(surviving_periods) - 1, note=date_note,
    )


# -------------------------------------------------------------------- build_group_trend_data (chart-block
# stream, 2026-10-24, batch 2: trend_groups/trend_styled - a genuinely new per-GROUP-per-PERIOD cross-tab,
# not a relabeled build_trend_data)

def build_group_trend_data(
    group_col: str, segment_raw: dict[int, str],
    period_by_row: dict[int, str], periods: list[str], date_note: str,
    nodes: list["ThemeNode"], group_floor: int = 100, max_groups: int = 5,
) -> "GroupTrendData | None":
    """Per-GROUP sentiment over time, via the SAME count-weighted-average-of-`Theme.sentiment`
    approximation `build_trend_data` already uses (no true per-row sentiment is ever persisted - see that
    function's own docstring and this module's top-level note) - here weighted per (group, period) cell
    instead of per period across all rows.

    A candidate GROUP needs `group_floor` (default 100 - SPEC's own segment/heatmap floor, reused here
    rather than inventing a third one) answers total to be considered at all; only the `max_groups`
    largest survive. A PERIOD is kept only if every surviving group has at least one real answer in it -
    a period where some group has zero data would force either an invented value or a misleading flat
    line, so it is dropped instead, the same "a period with too little data just isn't shown" discipline
    `build_trend_data`'s own 30-answer-per-period floor already follows.

    Returns `None` when fewer than 2 groups survive, or fewer than 3 periods survive the per-group
    completeness check."""
    row_sentiment: dict[int, float] = {}
    for node in nodes:
        for r in node.answer_refs:
            row_sentiment[r] = node.sentiment

    group_totals: dict[str, int] = {}
    for g in segment_raw.values():
        group_totals[g] = group_totals.get(g, 0) + 1
    surviving_groups = sorted(
        (g for g, n in group_totals.items() if n >= group_floor), key=lambda g: group_totals[g], reverse=True,
    )[:max_groups]
    if len(surviving_groups) < 2:
        return None

    cells: dict[tuple[str, str], list[float]] = {}
    for r, g in segment_raw.items():
        if g not in surviving_groups:
            continue
        p = period_by_row.get(r)
        if p is None or p not in periods:
            continue
        s = row_sentiment.get(r)
        if s is None:
            continue
        cells.setdefault((g, p), []).append(s)

    surviving_periods = [p for p in periods if all((g, p) in cells for g in surviving_groups)]
    if len(surviving_periods) < 3:
        return None

    colors = ["t1", "t2", "t3", "t4", "t5", "t6", "t7"]
    series = [
        GroupTrendSeries(
            group=g, color=colors[i % len(colors)],
            values=[round(sum(cells[(g, p)]) / len(cells[(g, p)]), 3) for p in surviving_periods],
        )
        for i, g in enumerate(surviving_groups)
    ]
    return GroupTrendData(group_column=group_col, labels=surviving_periods, series=series, note=date_note)


# -------------------------------------------------------------------- build_binned_grid_data (chart-block
# stream, 2026-10-24, batch 3: binned_grid - two independent number columns, quartile-banded, crossed)

def build_binned_grid_data(
    row_col: str, col_col: str,
    row_raw: dict[int, float], col_raw: dict[int, float],
    nodes: list["ThemeNode"], floor: int,
) -> "BinnedGridData | None":
    """Reuses `band_quartiles` (same quartile cuts `build_numeric_data`'s own numeric fallback already
    uses) independently on each column, then crosses the two real band sets into a grid. Each cell's
    sentiment is the same count-weighted-average-of-`Theme.sentiment` approximation
    `build_group_trend_data` already uses (via each row's own home theme - no true per-row sentiment is
    ever persisted, see that function's own docstring). A cell under `floor` answers is dropped from the
    output entirely (its count/sentiment stay at 0/0.0, matching a reader's own expectation of "nothing
    notable here" rather than a noisy small-sample average) - never discarding the row/column band it
    sits in, only that one cell's own number.

    Returns `None` when either column fails to band (`band_quartiles`'s own `ValueError` - fewer than 2
    distinct values) or no row has values in both columns at all."""
    rows = set(row_raw) & set(col_raw)
    if not rows:
        return None
    row_sentiment: dict[int, float] = {}
    for node in nodes:
        for r in node.answer_refs:
            row_sentiment[r] = node.sentiment
    try:
        row_bands = band_quartiles([row_raw[r] for r in rows])
        col_bands = band_quartiles([col_raw[r] for r in rows])
    except ValueError:
        return None

    row_label_by_row = apply_bands({r: row_raw[r] for r in rows}, row_bands)
    col_label_by_row = apply_bands({r: col_raw[r] for r in rows}, col_bands)

    cell_rows: dict[tuple[str, str], list[int]] = {}
    for r in rows:
        rl, cl = row_label_by_row.get(r), col_label_by_row.get(r)
        if rl is None or cl is None:
            continue
        cell_rows.setdefault((rl, cl), []).append(r)

    row_labels = [b.label for b in row_bands]
    col_labels = [b.label for b in col_bands]
    cells = []
    for rl in row_labels:
        for cl in col_labels:
            members = cell_rows.get((rl, cl), [])
            if len(members) < floor:
                cells.append(BinCell(row_label=rl, col_label=cl, count=0, sentiment=0.0))
                continue
            sentiments = [row_sentiment[r] for r in members if r in row_sentiment]
            avg = round(sum(sentiments) / len(sentiments), 3) if sentiments else 0.0
            cells.append(BinCell(row_label=rl, col_label=cl, count=len(members), sentiment=avg))

    return BinnedGridData(row_name=row_col, col_name=col_col, row_labels=row_labels, col_labels=col_labels, cells=cells)


# -------------------------------------------------------------------- pick_structured_columns

def pick_structured_columns(dataset_id: int, db: Session) -> dict[str, list[str]]:
    """Every confirmed, not-switched-off `Column` name of each kind ("score", "segment", "date", "numeric",
    "yes_no", "short_text"), in
    `Column.position` order - every candidate, not just the first, so `build_structured_context` can try
    each in turn and use the first one that actually produces a usable chart, instead of committing to
    upload-column-order regardless of whether that specific column's data survives suppression.

    `short_text` added (chart-block stream, 2026-10-24) for `ranked_answers`/`ranked_list` - a SEPARATE
    short-answer column (job title, product name, one-word/few-word factual answers), never the dataset's
    main open-ended column (that one is clustered into themes, never frequency-counted as a flat list)."""
    cols = list(db.scalars(
        select(Column).where(Column.dataset_id == dataset_id).order_by(Column.position)
    ).all())
    result: dict[str, list[str]] = {
        "score": [], "segment": [], "date": [], "numeric": [], "yes_no": [], "short_text": [],
    }
    for c in cols:
        if c.kind in result and not (c.stats or {}).get("off"):
            result[c.kind].append(c.name)
    return result


# -------------------------------------------------------------------- build_structured_context

def build_structured_context(
    clean_df, plan: "CleaningPlan", themes: list["Theme"], nodes: list["ThemeNode"],
    columns: dict[str, list[str]], floor: int, filter_rows: set[int] | None = None,
) -> StructuredContext:
    """Top-level B2 assembly: for each of "score"/"segment"/"date", tries every confirmed candidate column
    of that kind (`columns[kind]`, `pick_structured_columns`'s own position-ordered list) in turn, resolving
    it into real cleaned-dataframe values keyed by `theme_answer_rows(themes)` and calling the matching
    `build_*_data` function above, and keeps the FIRST candidate whose result is chart-worthy - stopping
    there rather than always taking the first column in upload order regardless of whether its own data
    survives suppression. A candidate that is absent, fails to resolve a scale/date spread, or produces no
    chart-worthy data after suppression is simply skipped in favour of the next one; if every candidate for
    a kind fails, that field is left out of the returned `StructuredContext` (stays at its `None`/`""`
    default) - never raises.

    `numeric`/`yes_no` kinds (docs/TODO.md, fixed 2026-10-22) feed the SAME `score`/`segment` slots above,
    tried only after every real `score`/`segment` candidate has failed - NOT a separate pair of slots.
    `ReportData.score`/`.segment` (app/findings.py::build_report_data) are each a single field read
    directly by `app/charts.py`'s `f_byscore`/`f_heatmap`, so two independently-populated "quantitative"
    or "categorical" slots could never both be rendered by the one chart id each renderer owns - a real
    architectural limit, not an oversight. In practice this is also the common real-world shape: a
    dataset confirms ONE quantitative measure (whichever kind it happens to be) and/or ONE small
    categorical split, not two of each - so falling back, rather than adding parallel slots nothing could
    render, is the honest fit.

    `filter_rows`, when not `None`, restricts every candidate's row universe to rows also in that set
    (the Filters feature's entire mechanism - see `resolve_filter_rows` below: every downstream per-kind
    loop already iterates `for r in rows`, so narrowing `rows` once here is enough to filter score/segment/
    trend consistently, with zero changes to `build_score_data`/`build_segment_data`/`build_trend_data`
    themselves)."""
    context = StructuredContext()
    rows = theme_answer_rows(themes)
    if filter_rows is not None:
        rows = [r for r in rows if r in filter_rows]

    for score_col in columns.get("score", []):
        step = next(
            (s for s in plan.steps if s.key == "check_score_range" and s.column == score_col), None,
        )
        if step is None:
            # No `check_score_range` step for this candidate: do not guess a scale from observed data
            # (explicitly out of scope) - try the next candidate instead of giving up on "score" entirely.
            continue
        scale = tuple(step.params["scale"])
        raw_by_row: dict[int, float] = {}
        for r in rows:
            try:
                raw_by_row[r] = clean_df.at[r, score_col]
            except KeyError:
                continue
        score_data = build_score_data(score_col, scale, raw_by_row, nodes, floor)
        if score_data is not None:
            context.score = score_data
            context.score_column_name = score_col
            context.score_raw_by_row = raw_by_row
            context.score_scale = scale
            break

    # `numeric` fallback - only reached if no real `score` candidate above won. No `unit` lookup here
    # (this module is deliberately pure - no database access, per its own docstring): `build_numeric_data`'s
    # `unit` only controls label formatting ($ vs plain numbers), defaulting to plain numbers is honest
    # either way, never wrong, just less decorated.
    if context.score is None:
        for numeric_col in columns.get("numeric", []):
            raw_numeric: dict[int, float] = {}
            for r in rows:
                try:
                    v = clean_df.at[r, numeric_col]
                except KeyError:
                    continue
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if math.isnan(fv):
                    continue
                raw_numeric[r] = fv
            numeric_data = build_numeric_data(numeric_col, raw_numeric, nodes, floor)
            if numeric_data is not None:
                context.score = numeric_data
                context.score_column_name = numeric_col
                # No `score_raw_by_row`/`score_scale` here - `resolve_filter_rows`'s score-band filter
                # applies `band_score(structured.score_scale)`, a fixed-scale banding scheme a numeric
                # column was never confirmed against; leaving these at their `None` default means a score-
                # band filter request against a numeric-backed `context.score` honestly yields "no rows
                # match" (see `resolve_filter_rows`'s own docstring) rather than banding it wrongly.
                break

    for segment_col in columns.get("segment", []):
        raw_seg: dict[int, str] = {}
        for r in rows:
            try:
                v = clean_df.at[r, segment_col]
            except KeyError:
                continue
            if v is None or (isinstance(v, float) and math.isnan(v)):
                continue  # a blank/missing cell is not a real segment group (confirmed bug, 2026-10-21:
                # an unguarded NaN here became a literal `SegmentGroup(label=nan, ...)`, which crashed the
                # WHOLE report response's JSON serialization, not just the segment/heatmap block - see
                # docs/DECISIONS.md)
            raw_seg[r] = v
        # Cap to the 8 largest groups by row count before ever calling build_segment_data - a cosmetic cap
        # for heatmap grid readability, not a suppression rule (see B1's module docstring).
        counts: dict[str, int] = {}
        for v in raw_seg.values():
            counts[v] = counts.get(v, 0) + 1
        top_groups = {g for g, _ in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:8]}
        raw_seg_capped = {r: v for r, v in raw_seg.items() if v in top_groups}
        segment_data = build_segment_data(segment_col, raw_seg_capped, nodes, floor)
        if segment_data is not None:
            context.segment = segment_data
            context.segment_column_name = segment_col
            context.segment_raw_by_row = raw_seg_capped
            break

    # `yes_no` fallback - only reached if no real `segment` candidate above won. A yes/no column is just
    # a 2-value categorical, so `build_segment_data` applies unmodified; still capped the same cosmetic
    # way (though a genuine yes/no column is already <=2 groups by construction, so the cap never
    # actually trims it).
    if context.segment is None:
        for yes_no_col in columns.get("yes_no", []):
            raw_yn: dict[int, str] = {}
            for r in rows:
                try:
                    v = clean_df.at[r, yes_no_col]
                except KeyError:
                    continue
                if v is None or (isinstance(v, float) and math.isnan(v)):
                    continue
                raw_yn[r] = v
            yes_no_data = build_segment_data(yes_no_col, raw_yn, nodes, floor)
            if yes_no_data is not None:
                context.segment = yes_no_data
                context.segment_column_name = yes_no_col
                context.segment_raw_by_row = raw_yn
                break

    for date_col in columns.get("date", []):
        parsed_by_row: dict[int, date] = {}
        for r in rows:
            try:
                v = clean_df.at[r, date_col]
            except KeyError:
                continue
            if isinstance(v, str):
                ts = pd.to_datetime(v, errors="coerce")
            elif isinstance(v, date):
                ts = pd.Timestamp(v)
            else:
                ts = pd.to_datetime(v, errors="coerce")
            if ts is None or pd.isna(ts):
                continue
            parsed_by_row[r] = ts.date()

        try:
            date_bands, date_note = band_dates(list(parsed_by_row.values()))
        except ValueError:
            continue  # this candidate's dates don't band usefully - try the next one

        raw_ordinals = {r: float(d.toordinal()) for r, d in parsed_by_row.items()}
        trend_data = build_trend_data(date_col, raw_ordinals, nodes, date_bands, date_note, floor)
        if trend_data is not None:
            context.trend = trend_data
            context.trend_column_name = date_col
            context.date_raw_by_row = parsed_by_row
            break

    # chart-block stream, 2026-10-24: ranked_answers/ranked_list. Independent of the score/segment/trend
    # loops above - a short_text column's own frequency table has nothing to do with themes or the floor
    # candidates already won for other roles, so there is no "already won" early-exit to mirror here.
    for freq_col in columns.get("short_text", []):
        raw_freq: dict[int, str] = {}
        for r in rows:
            try:
                v = clean_df.at[r, freq_col]
            except KeyError:
                continue
            if isinstance(v, str) and v.strip():
                raw_freq[r] = v
        freq_data = build_frequency_data(freq_col, raw_freq, floor)
        if freq_data is not None:
            context.frequency = freq_data
            context.frequency_column_name = freq_col
            break

    # chart-block stream, 2026-10-24, batch 2: vs_average. Independent of whichever short_text/numeric
    # candidate already won the frequency/score roles above - this is a genuinely different question (one
    # column's average BY another column's categories), so the same two columns can serve double duty.
    for cat_col in columns.get("short_text", []):
        raw_cat: dict[int, str] = {}
        for r in rows:
            try:
                v = clean_df.at[r, cat_col]
            except KeyError:
                continue
            if isinstance(v, str) and v.strip():
                raw_cat[r] = v
        found = False
        for num_col in columns.get("numeric", []):
            raw_num: dict[int, float] = {}
            for r in rows:
                try:
                    v = clean_df.at[r, num_col]
                except KeyError:
                    continue
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if math.isnan(fv):
                    continue
                raw_num[r] = fv
            avg_data = build_category_avg_data(cat_col, num_col, raw_cat, raw_num, floor)
            if avg_data is not None:
                context.category_avg = avg_data
                found = True
                break
        if found:
            break

    # chart-block stream, 2026-10-24, batch 2: trend_groups/trend_styled. Independent of whichever
    # segment/date candidate already won the segment/trend roles above (same "two columns can serve
    # double duty" reasoning as vs_average/category_avg).
    for seg_col in columns.get("segment", []):
        raw_grp: dict[int, str] = {}
        for r in rows:
            try:
                v = clean_df.at[r, seg_col]
            except KeyError:
                continue
            if v is None or (isinstance(v, float) and math.isnan(v)):
                continue
            raw_grp[r] = v
        found = False
        for date_col in columns.get("date", []):
            parsed_by_row: dict[int, date] = {}
            for r in rows:
                try:
                    v = clean_df.at[r, date_col]
                except KeyError:
                    continue
                ts = pd.Timestamp(v) if isinstance(v, date) else pd.to_datetime(v, errors="coerce")
                if ts is None or pd.isna(ts):
                    continue
                parsed_by_row[r] = ts.date()
            try:
                date_bands, date_note = band_dates(list(parsed_by_row.values()))
            except ValueError:
                continue
            period_by_row = apply_bands({r: float(d.toordinal()) for r, d in parsed_by_row.items()}, date_bands)
            periods = [b.label for b in date_bands]
            gt_data = build_group_trend_data(seg_col, raw_grp, period_by_row, periods, date_note, nodes)
            if gt_data is not None:
                context.group_trend = gt_data
                found = True
                break
        if found:
            break

    # chart-block stream, 2026-10-24, batch 3: binned_grid. Needs TWO distinct numeric columns - tries
    # every real pair (never a column against itself), independent of whichever numeric candidate already
    # won the score role above.
    numeric_cols = columns.get("numeric", [])
    for i, row_col in enumerate(numeric_cols):
        row_raw: dict[int, float] = {}
        for r in rows:
            try:
                v = clean_df.at[r, row_col]
            except KeyError:
                continue
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if math.isnan(fv):
                continue
            row_raw[r] = fv
        found = False
        for col_col in numeric_cols[i + 1:]:
            col_raw: dict[int, float] = {}
            for r in rows:
                try:
                    v = clean_df.at[r, col_col]
                except KeyError:
                    continue
                try:
                    fv = float(v)
                except (TypeError, ValueError):
                    continue
                if math.isnan(fv):
                    continue
                col_raw[r] = fv
            bg_data = build_binned_grid_data(row_col, col_col, row_raw, col_raw, nodes, floor)
            if bg_data is not None:
                context.binned_grid = bg_data
                found = True
                break
        if found:
            break

    return context


def resolve_filter_rows(
    structured: StructuredContext,
    segment: str | None,
    score_band: str | None,
    date_from: date | None,
    date_to: date | None,
) -> set[int] | None:
    """Turns a Filters request (SPEC.md section 5: "a global filter (segment, score band, date range)")
    into the row-index set `build_structured_context`'s `filter_rows` param expects, using the raw per-row
    dicts an UNFILTERED `StructuredContext` already stashed (`score_raw_by_row`/`segment_raw_by_row`/
    `date_raw_by_row`, set by `build_structured_context` above). Returns `None` only when every argument is
    `None` - the caller's signal to skip filtering entirely (byte-identical to today's behaviour). Multiple
    active constraints are AND'd together (one combined filter, not three independent ones - matching
    SPEC's single "a global filter" wording, not "filters").

    A constraint naming a column that never resolved to a chart-worthy result (its `*_raw_by_row` is
    `None`) yields an empty set for that constraint rather than being silently ignored - "filter by a
    segment group that isn't actually shown anywhere" should honestly produce "no rows match," not quietly
    fall back to unfiltered."""
    if segment is None and score_band is None and date_from is None and date_to is None:
        return None

    rows: set[int] | None = None

    def _intersect(candidate: set[int]) -> None:
        nonlocal rows
        rows = candidate if rows is None else (rows & candidate)

    if segment is not None:
        if structured.segment_raw_by_row is None:
            _intersect(set())
        else:
            _intersect({r for r, v in structured.segment_raw_by_row.items() if v == segment})

    if score_band is not None:
        if structured.score_raw_by_row is None or structured.score_scale is None:
            _intersect(set())
        else:
            band_by_row = apply_bands(structured.score_raw_by_row, band_score(structured.score_scale))
            _intersect({r for r, label in band_by_row.items() if label == score_band})

    if date_from is not None or date_to is not None:
        if structured.date_raw_by_row is None:
            _intersect(set())
        else:
            _intersect({
                r for r, d in structured.date_raw_by_row.items()
                if (date_from is None or d >= date_from) and (date_to is None or d <= date_to)
            })

    return rows if rows is not None else set()


# ==================================================================== B3 - new candidate-finding kinds
#
# Three new SPEC.md section 9.3 finding kinds ("a theme raised more by one group", "a number that moves
# with sentiment or score", "a trend over time"), built directly on B2's `StructuredContext.segment`/
# `.score`/`.trend` rather than re-deriving anything from raw rows. Each has its own gate/solid threshold
# pair, named and commented the same way `app/findings.py`'s existing `TONE_GAP_MIN`/`TONE_GAP_SOLID` etc.
# are - see that module's own threshold-constant block for the convention this mirrors.
#
# Score-scale consistency (a deliberate, already-made decision - see docs/DECISIONS.md's 2026-09-29 entry):
# `app/findings.py::candidate_findings`'s own existing kinds are NOT all on one scale already -
# `dominant_theme`'s score is a bare percentage-point margin (`score=margin`) and `long_tail`'s is a bare
# percentage-point share (`score=share`), NEITHER with any size-bonus multiplier; only `tone_contrast` uses
# an effect-size-times-size-bonus shape, on its own -1..+1 sentiment-gap scale (the pre-existing mismatch
# this stream deliberately leaves alone). So "matching the existing ones" for these 3 new kinds means
# matching `dominant_theme`/`long_tail` exactly: every `Candidate.score` below is a BARE percentage-point
# effect size, with NO size-bonus multiplier - not `tone_contrast`'s shape, and not a third, new hybrid
# shape either (an earlier draft of this module multiplied by the same bonus `tone_contrast` uses, which
# would have made these 3 kinds systematically outrank `dominant_theme`/`long_tail` on an equivalent-sized
# effect, not merely compete fairly with them - caught in review and reverted). The ratio/percentage-point
# numbers used for the GATE/SOLID checks (ratios for `segment_skew`, percentage points for
# `score_correlation`/`trend_shift`) are unaffected either way, matching SPEC.md's own example sentence
# style.
#
# Circular-import note: `Candidate` (and, for `score_correlation_candidates`, `theme_nodes`) live in
# `app/findings.py`, which already imports `StructuredContext` from this module at module level - a
# top-level `from .findings import Candidate` here would therefore be a real import cycle (this module
# would need `app.findings` fully initialised before `app.findings` finishes initialising itself). Each
# function below does that import inside its own body instead: by the time any of these functions is
# actually CALLED, both modules have finished loading, so the deferred import always succeeds - no
# restructuring of either module needed, and `python -c "import app.findings"` /
# `python -c "import app.findings_structured"` both still work standalone.

SEGMENT_SKEW_RATIO_MIN = 1.5  # group-vs-overall share ratio (either direction) to raise a segment-skew candidate at all
SEGMENT_SKEW_RATIO_SOLID = 2.0  # ratio needed (with the group-size floor below) to call it "Solid"

SCORE_SPREAD_MIN = 8.0  # percentage-point spread across score bands to raise a score-correlation candidate at all
SCORE_SPREAD_SOLID = 15.0  # spread needed (with the band-size floor below) to call it "Solid"

TREND_SHIFT_MIN = 6.0  # percentage-point change from first to last period to raise a trend-shift candidate at all
TREND_SHIFT_SOLID = 12.0  # change needed (with the theme-size floor below) to call it "Solid"


def segment_skew_candidates(segment: SegmentData, themes: list["Theme"], floor: int) -> list["Candidate"]:
    """One candidate per surviving `(row, group)` heatmap cell whose group share diverges from that row's
    theme's overall share by at least `SEGMENT_SKEW_RATIO_MIN`x in either direction - every cell, not just
    `segment.highlight` (which is only the single most-extreme cell, kept for the chart's own hover UI).
    Rows whose `overall` is 0 are skipped (nothing to divide by). `group.n < floor` is a defensive check
    only: every group in `segment.groups` already survived `build_segment_data`'s own stricter
    `heatmap_group_floor`, so this should never actually trigger in practice.

    `Candidate.score` is the group-vs-overall percentage-point gap (`abs(group_share - overall_share)`),
    a bare percentage point with no size-bonus multiplier - the same shape `dominant_theme`'s `score=margin`
    already uses, not `tone_contrast`'s effect-times-bonus shape - see the module-section comment above."""
    from .findings import Candidate, theme_nodes  # deferred - see the module-section comment above

    total = sum(t.size for t in themes)
    nodes_by_name = {n.name: n for n in theme_nodes(themes, total)}
    candidates: list[Candidate] = []

    for row in segment.rows:
        if row.overall == 0:
            continue
        node = nodes_by_name.get(row.theme)
        theme_id = node.theme_id if node is not None else None
        for gi, group in enumerate(segment.groups):
            if group.n < floor:  # defensive - see docstring
                continue
            cell_value = row.values[gi]
            ratio = cell_value / row.overall
            gated = ratio >= SEGMENT_SKEW_RATIO_MIN or ratio <= 1 / SEGMENT_SKEW_RATIO_MIN
            if not gated:
                continue
            gap_pp = abs(cell_value - row.overall)
            candidates.append(Candidate(
                kind="segment_skew", id=f"segment_skew:{theme_id}:{gi}", theme_id=theme_id,
                theme_name=row.theme, count=group.n, score=gap_pp,
                numbers={
                    "column": segment.name, "group": group.label, "theme": row.theme,
                    "group_share_pct": cell_value, "overall_share_pct": row.overall,
                    "ratio": round(ratio, 3), "group_n": group.n,
                },
            ))
    return candidates


def score_correlation_candidates(score: ScoreData, themes: list["Theme"], floor: int) -> list["Candidate"]:
    """One candidate per theme whose share of answers moves notably across score bands (`ScoreBand.mix`,
    positionally aligned per-theme - see `build_score_data`'s own docstring): the spread between that
    theme's highest-mix band and lowest-mix band, by real value not by band position (a theme's mix can
    peak in a middle band, so this never assumes `score.bands[0]`/`[-1]` are the extremes).

    `themes` need not already be in `nodes` order: `theme_nodes(themes, total)` re-sorts real themes by
    size internally regardless of input order (real-first largest-to-smallest, "Other" last), so recomputing
    it here from the same `themes` list `build_structured_context` was given reproduces the exact positional
    order `ScoreBand.mix` was built against.

    `Candidate.score` is `spread_pct` itself, unmultiplied - already real percentage points, the same bare
    shape `dominant_theme`'s `score=margin` uses, not `tone_contrast`'s effect-times-bonus shape - see the
    module-section comment above."""
    from .findings import Candidate, theme_nodes  # deferred - see the module-section comment above

    if not score.bands:
        return []

    total = sum(t.size for t in themes)
    nodes = theme_nodes(themes, total)
    candidates: list[Candidate] = []

    for i, node in enumerate(nodes):
        per_band = [(band, band.mix[i]) for band in score.bands]
        max_band, max_pct = max(per_band, key=lambda bm: bm[1])
        min_band, min_pct = min(per_band, key=lambda bm: bm[1])
        spread_pct = round(max_pct - min_pct, 1)
        if spread_pct < SCORE_SPREAD_MIN:
            continue
        if max_band.answers < floor or min_band.answers < floor:
            continue
        theme_id = node.theme_id
        constraining = min(max_band.answers, min_band.answers)
        candidates.append(Candidate(
            kind="score_correlation", id=f"score_correlation:{theme_id}", theme_id=theme_id,
            theme_name=node.name, count=constraining, score=spread_pct,
            numbers={
                "column": score.name, "theme": node.name,
                "low_band": min_band.label, "low_pct": min_pct,
                "high_band": max_band.label, "high_pct": max_pct,
                "spread_pct": spread_pct,
            },
        ))
    return candidates


def trend_shift_candidates(
    trend: TrendData, themes: list["Theme"], floor: int, column: str = "",
) -> list["Candidate"]:
    """One candidate per theme whose share of answers moves notably from the first to the last surviving
    period (`TrendSeries.values[0]` to `[-1]`). `TrendData`/`TrendSeries` carry no per-period answer count
    (only each period's aggregate `sentiment`/theme-share, per `app/chart_data.py`) - every surviving period
    already cleared `build_trend_data`'s own per-period floor (SPEC.md's trend-specific "under 30" skip
    row), so this gate instead checks the theme's own overall stored `Theme.size` against `floor`, a
    documented, deliberate substitution rather than a per-period recomputation this module has no data for.

    `column` is accepted separately because (unlike `ScoreData.name`/`SegmentData.name`) `TrendData` itself
    carries no column-name field - `app/findings.py::candidate_findings` passes
    `structured.trend_column_name` through here so `numbers["column"]` is still populated; the default
    keeps this callable with exactly the 3-argument shape the rest of this module's B3 functions share.

    `Candidate.score` is `abs(change_pct)` itself, unmultiplied - already real percentage points, the same
    bare shape `dominant_theme`'s `score=margin` uses, not `tone_contrast`'s effect-times-bonus shape - see
    the module-section comment above."""
    from .findings import Candidate, theme_nodes  # deferred - see the module-section comment above

    if not trend.series or not trend.labels:
        return []

    total = sum(t.size for t in themes)
    nodes_by_name = {n.name: n for n in theme_nodes(themes, total)}
    candidates: list[Candidate] = []

    for series in trend.series:
        if not series.values:
            continue
        first_pct, last_pct = series.values[0], series.values[-1]
        change_pct = round(last_pct - first_pct, 1)
        if abs(change_pct) < TREND_SHIFT_MIN:
            continue
        node = nodes_by_name.get(series.theme)
        count = node.count if node is not None else 0
        if count < floor:
            continue
        theme_id = node.theme_id if node is not None else None
        candidates.append(Candidate(
            kind="trend_shift", id=f"trend_shift:{theme_id}", theme_id=theme_id,
            theme_name=series.theme, count=count, score=abs(change_pct),
            numbers={
                "column": column, "theme": series.theme,
                "first_period": trend.labels[0], "first_pct": first_pct,
                "last_period": trend.labels[-1], "last_pct": last_pct,
                "change_pct": change_pct, "direction": "rising" if change_pct > 0 else "fading",
            },
        ))
    return candidates
