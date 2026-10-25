"""Time periods written as text: "FY19", "2019", "Q3 2022", "2022-Q3", "Mar 2021".

Survey files often carry when an answer was given as a year, fiscal year or quarter instead of a full
date. `app.profiling.columns` uses `period_kind` to call such a column a date column, and
`app.findings_structured` uses `parse_period` to read its values, so these columns get the same
change-over-time charts as real dates. Each value maps to the first day of its period, and `granularity`
says how wide the period is, so a year column is shown per year, not as twelve months with one filled.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Literal

import pandas as pd

Granularity = Literal["year", "quarter", "month", "day"]

_FY = re.compile(r"^\s*fy\s*'?(\d{2}|\d{4})\s*$", re.I)
_YEAR = re.compile(r"^\s*(\d{4})(?:\.0+)?\s*$")
_QUARTER = re.compile(r"^\s*(?:q([1-4])[\s\-/]*(\d{4})|(\d{4})[\s\-/]*q([1-4]))\s*$", re.I)
_MONTH_YEAR = re.compile(r"^\s*(?:[a-z]{3,9}[\s\-/]+\d{4}|\d{4}-\d{1,2})\s*$", re.I)
# Plain numbers only count as years inside this range, and only in a column whose name says so
# (`period_kind`): a bare 2019 is just as often a count or a code.
YEAR_MIN, YEAR_MAX = 1950, 2100
_NAME_HINT = re.compile(r"(year|fy|fiscal|wave|period|cycle|quarter|qtr)", re.I)


def _full_year(two_or_four: str) -> int:
    y = int(two_or_four)
    return 2000 + y if y < 100 else y


def parse_period(value: Any) -> tuple[date, Granularity] | None:
    """The first day of the period `value` names, and how wide that period is; None if it is not one.
    A real date or datetime is a day; "FY19" or 2019 a year (FY counts by its label year); "Q3 2022" a
    quarter; "Mar 2021" or "2021-03" a month; any other date text that pandas reads is a day."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, datetime):
        return value.date(), "day"
    if isinstance(value, date):
        return value, "day"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if float(value).is_integer() and YEAR_MIN <= value <= YEAR_MAX:
            return date(int(value), 1, 1), "year"
        return None
    text = str(value).strip()
    if not text:
        return None
    if m := _FY.match(text):
        return date(_full_year(m.group(1)), 1, 1), "year"
    if (m := _YEAR.match(text)) and YEAR_MIN <= int(m.group(1)) <= YEAR_MAX:
        return date(int(m.group(1)), 1, 1), "year"
    if m := _QUARTER.match(text):
        q, y = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
        return date(int(y), 3 * (int(q) - 1) + 1, 1), "quarter"
    if _MONTH_YEAR.match(text):
        ts = pd.to_datetime(text, errors="coerce")
        return (ts.date().replace(day=1), "month") if not pd.isna(ts) else None
    ts = pd.to_datetime(text, errors="coerce")
    return (ts.date(), "day") if not pd.isna(ts) else None


def period_kind(name: str, values: list[Any]) -> Granularity | None:
    """The granularity when at least 85% of a column's distinct values are years, fiscal years, quarters
    or months, else None. Plain numbers count as years only when the column's name says so ("Year",
    "FY", "Wave", ...); "FY19" or "Q3 2022" speak for themselves."""
    if not values:
        return None
    hinted = bool(_NAME_HINT.search(name))
    kinds: list[Granularity] = []
    for v in values:
        if isinstance(v, (date, datetime)):
            return None  # real dates: the ordinary date detection handles these
        is_number = isinstance(v, (int, float)) and not isinstance(v, bool) or bool(_YEAR.match(str(v)))
        if is_number and not hinted:
            continue
        got = parse_period(v)
        if got is not None and got[1] != "day":
            kinds.append(got[1])
    if len(kinds) < 0.85 * len(values):
        return None
    # A mixed column ("2021", "Q3 2022") is read at its finest named period.
    order: list[Granularity] = ["year", "quarter", "month"]
    return max(set(kinds), key=order.index)
