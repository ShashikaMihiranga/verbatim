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

__all__ = ["Band", "band_score", "band_age", "band_quartiles", "band_dates", "apply_bands"]


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
