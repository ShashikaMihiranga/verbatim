"""Shared pieces for the cleaning steps: context, outcome, uniques-based mapping, number parsing.

Every step works on the distinct values of a column (value_counts) and maps them once, so 50,000 rows
cost about as much as the number of different answers. Nothing here evaluates user content.
"""
from __future__ import annotations

import math
import numbers
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

MAX_EXAMPLE_CHARS = 160
MAX_CELL_CHARS = 20_000
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁠⁦-⁩﻿]")


class CleaningError(ValueError):
    """A problem whose message is safe to show to the user."""


class CleaningTimeout(CleaningError):
    pass


class Deadline:
    def __init__(self, seconds: float):
        self.end = time.monotonic() + seconds
        self.seconds = seconds

    def check(self) -> None:
        if time.monotonic() > self.end:
            raise CleaningTimeout(
                f"Cleaning took longer than {self.seconds:g} seconds, so it was stopped. Try a smaller file."
            )


def safe_text(v: Any, n: int = MAX_EXAMPLE_CHARS) -> str:
    """Text for echoing back to the browser: control characters removed, length capped. JSON string only."""
    s = _CTRL.sub("", str(v)).replace("\n", " ").replace("\r", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def is_blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    try:
        return bool(pd.isna(v))
    except (TypeError, ValueError):
        return False


@dataclass
class Outcome:
    rows: int = 0
    cells: int = 0
    examples: list[dict[str, str]] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)


class Ctx:
    def __init__(self, df: pd.DataFrame, columns: dict[str, dict], settings: dict, deadline: Deadline):
        self.df = df
        self.columns = columns
        self.settings = settings
        self.deadline = deadline
        self.flags: dict[int, list[str]] = defaultdict(list)
        self.removed: dict[int, tuple[str, str]] = {}
        self.dup_counts: dict[int, int] = {}
        self.removed_columns: list[dict[str, str]] = []
        self.excluded: list[str] = []
        self.warnings: list[str] = []
        self.pii: dict[str, int] = defaultdict(int)

    def sensitive(self, col: str) -> bool:
        return bool(self.columns.get(col, {}).get("sensitive"))

    def kind(self, col: str) -> str:
        return self.columns.get(col, {}).get("kind", "id_or_junk")

    def flag_rows(self, idx, text: str) -> None:
        for i in idx:
            self.flags[i].append(text)

    def remove_rows(self, idx, step_id: str, reason: str) -> None:
        idx = list(idx)
        for i in idx:
            self.removed[i] = (step_id, reason)
        if idx:
            self.df = self.df.drop(index=idx)


def _changed(old: Any, new: Any) -> bool:
    if new is None:
        return True
    if isinstance(old, numbers.Real) and isinstance(new, numbers.Real) and not isinstance(old, bool):
        return old != new
    return type(old) is not type(new) or old != new


def map_uniques(
    ctx: Ctx,
    col: str,
    fn: Callable[[Any, int], Any],
    flagger: Callable[[Any], str | None] | None = None,
) -> Outcome:
    """Apply fn(value, count) to each distinct value of a column. Returns counts and examples.

    fn returns the new value (None blanks the cell). flagger(value) may return a flag text; flagged rows
    are recorded so the reason is kept next to the row instead of the value being silently fixed.
    """
    s = ctx.df[col]
    vc = s.value_counts(dropna=True)
    mapping: dict[Any, Any] = {}
    flagged: dict[Any, str] = {}
    changed: list[tuple[int, Any, Any]] = []
    cells = 0
    for k, (v, c) in enumerate(vc.items()):
        if k % 2000 == 0:
            ctx.deadline.check()
        new = fn(v, int(c))
        if flagger is not None:
            f = flagger(v)
            if f:
                flagged[v] = f
        if _changed(v, new):
            mapping[v] = new
            cells += int(c)
            changed.append((int(c), v, new))
    if flagged:
        mask = s.isin(list(flagged))
        for i, v in s[mask].items():
            ctx.flags[i].append(f"{col}: {flagged[v]}")
    if mapping:
        mask = s.isin(list(mapping))
        new_s = s.copy()
        new_s[mask] = s[mask].map(mapping)
        ctx.df[col] = new_s
    out = Outcome(rows=cells, cells=cells)
    if not ctx.sensitive(col):
        changed.sort(key=lambda t: (-t[0], safe_text(t[1])))
        seen = set()
        for c, v, new in changed:
            pair = (safe_text(v), "" if new is None else safe_text(new))
            if pair in seen:
                continue
            seen.add(pair)
            out.examples.append({"before": pair[0], "after": pair[1]})
            if len(out.examples) == 3:
                break
    out.details["distinct_changed"] = len(mapping)
    out.details["flagged_cells"] = sum(int(vc[v]) for v in flagged)
    return out


# ------------------------------------------------------------------ numbers
_CUR = re.compile(r"(?i)(?:usd|aud|eur|gbp|nzd|cad|us\$|au\$|nz\$|a\$|c\$|[$€£¥₹])")
_INT_THOU = re.compile(r"\d{1,3}(,\d{3})+")
_DEC_COMMA = re.compile(r"\d+,\d{1,2}")
_DOT_THOU = re.compile(r"\d{1,3}(\.\d{3}){2,}")
_SLASH = re.compile(r"^(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)$")


def parse_number(v: Any, allow_ratio: bool = False) -> float | None:
    """Read currency, percent, thousand separators, (negatives), 50k. Strict regexes only; None if unsure."""
    if isinstance(v, bool):
        return None
    if isinstance(v, numbers.Real):
        f = float(v)
        return f if math.isfinite(f) else None
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s or len(s) > 40:
        return None
    if allow_ratio:
        m = _SLASH.match(s)
        if m:
            return float(m.group(1))
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1].strip()
    s = _CUR.sub("", s).strip()
    if s.endswith("%"):
        s = s[:-1].strip()
    mult = 1.0
    if len(s) > 1 and s[-1] in "kKmM" and s[-2].isdigit():
        mult = 1e3 if s[-1] in "kK" else 1e6
        s = s[:-1]
    s = s.replace(" ", "").replace(" ", "").replace(" ", "").replace("'", "")
    if s[:1] in ("+", "-"):
        neg ^= s[0] == "-"
        s = s[1:]
    if not s or not re.fullmatch(r"[\d.,]+", s) or not any(ch.isdigit() for ch in s):
        return None
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        if s.count(dec) > 1:
            return None
        s2 = s.replace(thou, "").replace(dec, ".")
    elif "," in s:
        if _INT_THOU.fullmatch(s):
            s2 = s.replace(",", "")
        elif _DEC_COMMA.fullmatch(s):
            s2 = s.replace(",", ".")
        else:
            return None
    elif "." in s:
        if _DOT_THOU.fullmatch(s):
            s2 = s.replace(".", "")
        elif s.count(".") == 1:
            s2 = s
        else:
            return None
    else:
        s2 = s
    try:
        f = float(s2) * mult
    except ValueError:
        return None
    if not math.isfinite(f):
        return None
    return -f if neg else f


def tidy_number(f: float) -> int | float:
    f = round(f, 10)
    return int(f) if float(f).is_integer() and abs(f) < 1e15 else f
