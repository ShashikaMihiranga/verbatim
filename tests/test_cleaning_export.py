"""Spreadsheet formula-injection guard for any future download, and inert report examples."""
import csv
import io

import pandas as pd
import pytest

from app.cleaning import apply_plan, csv_safe_bytes, csv_safe_cell, csv_safe_frame, plan_with_preview
from app.cleaning.common import safe_text

BAD = ["=1+1", "+1+1", "-1+1", "@SUM(A1)", "\t=1", "\r=1", '=HYPERLINK("http://evil.example","x")',
       "=cmd|' /C calc'!A0", "  =1+1", "\t  -2+3", " @x", "﻿=1+1", "＝1+1", "＋1+1"]


@pytest.mark.parametrize("v", BAD)
def test_dangerous_strings_are_prefixed(v):
    assert csv_safe_cell(v) == "'" + v


@pytest.mark.parametrize("v", ["hello", "Price", "a=b", "x+y", "e-mail me", "", " ", "-", "+", "=", "@", "1", "$5",
                               "'already", "5 - 3", "Tesla @ home"])
def test_harmless_strings_are_unchanged(v):
    assert csv_safe_cell(v) == v


def test_non_strings_are_unchanged():
    for v in (None, 5, -5, 2.5, -0.5, float("nan"), True):
        out = csv_safe_cell(v)
        assert out is v or (v != v and out != out)


def test_frame_guards_text_cells_and_headers_and_keeps_numbers_and_original():
    df = pd.DataFrame({"=evil": ["=1+1", "fine", None], "n": [1, -2, 3], "t": ["@x", " +y", "ok"]}).astype(
        {"=evil": object, "t": object})
    before = df.copy(deep=True)
    out = csv_safe_frame(df)
    assert list(out.columns) == ["'=evil", "n", "t"]
    assert list(out["'=evil"][:2]) == ["'=1+1", "fine"] and pd.isna(out["'=evil"][2])
    assert list(out["n"]) == [1, -2, 3] and list(out["t"]) == ["'@x", "' +y", "ok"]
    pd.testing.assert_frame_equal(df, before)  # the input is not modified


def test_written_csv_never_has_a_cell_starting_with_a_trigger():
    df = pd.DataFrame({"a": BAD + ["ok"], "b": [-1] * (len(BAD) + 1)}).astype({"a": object})
    rows = list(csv.reader(io.StringIO(csv_safe_bytes(df).decode("utf-8"))))
    for r in rows[1:]:
        cell = r[0]
        assert cell.lstrip(" \t\r\n ﻿")[:1] not in ("=", "+", "-", "@", "＝", "＋") or cell.startswith("'")
        assert not cell.startswith(("=", "+", "-", "@", "\t", "\r"))


def _hostile_df():
    text = [f"=HYPERLINK(\"http://evil.example/{i}\",\"click\") mail me at a{i}@example.com please" for i in range(12)]
    text += ["-2+3 is what I would pay for the car honestly, contact me on 0412 345 678"] * 4
    text += [f"@SUM(A1:A9) charging is far away from where I live number {i} for now" for i in range(8)]
    df = pd.DataFrame({"Why": text}).astype(object)
    prof = {"columns": [{"name": "Why", "kind": "open_text", "sensitive": False}]}
    return df, prof


def test_report_examples_are_inert():
    df, prof = _hostile_df()
    plan, rep = plan_with_preview(df, prof)
    d = rep.to_dict()
    seen = 0
    for s in d["steps"]:
        for ex in s["examples"]:
            for v in ex.values():
                seen += 1
                assert not v.startswith(("=", "+", "-", "@", "\t", "\r")), v
    assert seen


def test_safe_text_guards_but_leaves_ordinary_text_and_lone_symbols():
    assert safe_text("=1+1") == "'=1+1" and safe_text("-") == "-" and safe_text("Price") == "Price"
    assert safe_text("  @x") == "'  @x" and len(safe_text("=" + "a" * 500, 50)) == 50


def test_internal_clean_file_still_holds_the_real_values():
    df, prof = _hostile_df()
    plan, _ = plan_with_preview(df, prof)
    clean, _ = apply_plan(df, plan)
    danger = clean["Why"].astype(str).str[:1].isin(list("=+-@"))
    assert danger.sum() == 21  # the analysis data keeps the real values; only the exporter changes them
    guarded = csv_safe_frame(clean)
    assert guarded["Why"].astype(str).str.startswith("'").sum() == 21
    assert not guarded["Why"].astype(str).str[:1].isin(list("=+-@")).any()
