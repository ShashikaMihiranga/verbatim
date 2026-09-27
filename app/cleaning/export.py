"""Guarded export of cleaned data to spreadsheet formats (CSV/Excel formula injection).

A cell that starts with =, +, - or @ (or a tab or carriage return) is run as a formula by Excel, LibreOffice and
Google Sheets when a person opens the file, e.g. `=HYPERLINK("http://evil","click")` or a DDE call. Survey
answers are untrusted, so any file a person can download and open in a spreadsheet must go through
`csv_safe_frame` / `csv_safe_bytes` first: such cells get a single quote prefix, which spreadsheets show as plain
text. Values after leading whitespace are treated the same way (" =1+1"), and so are the full-width look-alikes.

The internal analysis copy (`app.models.CleanedFile`, keyed by the sha256 of its bytes) is deliberately NOT
changed: the pipeline reads it back and needs the real values. There is no download route yet; any future
one must use this module.

This module itself does no disk (or database) I/O at all - `csv_safe_frame`/`csv_safe_bytes` are pure
in-memory pandas transforms, so it needed no change for the move off disk storage; only this comment did.
"""
from __future__ import annotations

from typing import Any

import pandas as pd

_TRIGGERS = "=+-@\t\r＝＋－＠"
_LEADING_WS = " \t\r\n\v\f   ﻿​"


def needs_guard(s: str) -> bool:
    """True when a spreadsheet could read this text as a formula. A lone '-', '+' or '=' is harmless."""
    if len(s) < 2:
        return bool(s) and s in "\t\r"
    if s[0] in "\t\r":
        return True
    stripped = s.lstrip(_LEADING_WS)
    return len(stripped) >= 2 and stripped[0] in _TRIGGERS


def csv_safe_cell(value: Any) -> Any:
    """Return value unchanged unless it is a string a spreadsheet would run as a formula; then prefix a single quote."""
    if isinstance(value, str) and needs_guard(value):
        return "'" + value
    return value


def csv_safe_frame(df: pd.DataFrame) -> pd.DataFrame:
    """A copy of df that is safe to write as CSV/XLSX: text cells and column names are guarded, numbers untouched."""
    out = df.copy()
    for c in out.columns:
        if out[c].dtype == object or pd.api.types.is_string_dtype(out[c]):
            out[c] = out[c].map(csv_safe_cell)
    out.columns = [csv_safe_cell(c) if isinstance(c, str) else c for c in out.columns]
    return out


def csv_safe_bytes(df: pd.DataFrame) -> bytes:
    """UTF-8 CSV of the guarded frame, ready to send as a download."""
    return csv_safe_frame(df).to_csv(index=False).encode("utf-8")
