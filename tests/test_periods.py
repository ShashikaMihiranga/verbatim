"""Years, fiscal years and quarters written as text read as time (app/periods.py), and get trend bands."""
from datetime import date

import pandas as pd
import pytest

from app.findings_structured import band_dates
from app.periods import parse_period, period_kind
from app.profiling.columns import profile_column


@pytest.mark.parametrize("value, expected", [
    ("FY19", (date(2019, 1, 1), "year")),
    ("fy 2021", (date(2021, 1, 1), "year")),
    ("FY'20", (date(2020, 1, 1), "year")),
    (2019, (date(2019, 1, 1), "year")),
    ("2019", (date(2019, 1, 1), "year")),
    (2019.0, (date(2019, 1, 1), "year")),
    ("Q3 2022", (date(2022, 7, 1), "quarter")),
    ("2022-Q4", (date(2022, 10, 1), "quarter")),
    ("Mar 2021", (date(2021, 3, 1), "month")),
    ("2021-03", (date(2021, 3, 1), "month")),
    ("2021-03-17", (date(2021, 3, 17), "day")),
    (date(2020, 5, 2), (date(2020, 5, 2), "day")),
])
def test_parse_period_reads_each_way_of_writing_when(value, expected):
    assert parse_period(value) == expected


@pytest.mark.parametrize("value", [None, "", "hello", 42, 3000, True, float("nan")])
def test_parse_period_rejects_what_is_not_a_period(value):
    assert parse_period(value) is None


def test_plain_numbers_are_years_only_when_the_name_says_so():
    years = [2017, 2018, 2019, 2020]
    assert period_kind("Survey year", years) == "year"
    assert period_kind("FY", years) == "year"
    assert period_kind("Units sold", years) is None  # a count that happens to look like years
    assert period_kind("Wave", ["FY19", "FY20", "FY21"]) == "year"
    assert period_kind("When", ["Q1 2022", "Q2 2022", "Q3 2022"]) == "quarter"  # speaks for itself
    assert period_kind("Notes", ["great", "bad", "FY19"]) is None


def test_profiling_calls_year_and_quarter_columns_dates():
    def kind(name, values):
        return profile_column(name, values)["kind"]
    assert kind("Fiscal_Year", ["FY19", "FY20", "FY21"] * 20) == "date"
    assert kind("Year", [2017, 2018, 2019, 2020] * 20) == "date"
    assert kind("Quarter", ["Q1 2022", "Q2 2022", "Q3 2022"] * 20) == "date"
    assert kind("Birth year", [1980, 1990, 2000] * 20) != "date"  # sensitive, and not "when"
    assert kind("Age", [2017, 2018, 2019] * 20) != "date"
    assert kind("Units", [2017, 2018, 2019, 2020] * 20) != "date"


def test_years_and_quarters_band_per_period_not_per_month():
    bands, note = band_dates([date(2017, 1, 1), date(2018, 1, 1), date(2019, 1, 1)], "year")
    assert [b.label for b in bands] == ["2017", "2018", "2019"] and note == "Yearly, 2017 to 2019."
    bands, note = band_dates([date(2022, 1, 1), date(2022, 7, 1)], "quarter")
    assert [b.label for b in bands] == ["Q1 2022", "Q2 2022", "Q3 2022"]
    with pytest.raises(ValueError):
        band_dates([date(2018, 1, 1), date(2019, 1, 1)], "year")  # two years: not a trend yet


def test_long_date_spans_band_by_quarter_then_year():
    bands, note = band_dates([date(2014, 2, 3), date(2018, 11, 20)])  # 58 months
    assert bands[0].label == "Q1 2014" and bands[-1].label == "Q4 2018" and note.startswith("Quarterly")
    bands, _ = band_dates([date(2000, 1, 1), date(2010, 6, 1)])  # 42 quarters
    assert [b.label for b in bands][:2] == ["2000", "2001"]
    bands, note = band_dates([date(2020, 1, 5), date(2020, 6, 9)])  # short span stays monthly
    assert note.startswith("Monthly")
