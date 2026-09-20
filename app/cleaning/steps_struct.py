"""Cleaning steps for score, date, numeric, segment and yes/no columns.

Principle: never repair a value we cannot be sure about. Out-of-range scores and impossible dates are blanked
and flagged with the original value kept in the row's flag text; outliers are flagged and left in place.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from .common import Ctx, Outcome, map_uniques, parse_number, safe_text, tidy_number
from .models import Step
from .steps_text import TABLE_CAP, build_merge_table, hide_small_counts, mk, run_merge_table

# ------------------------------------------------------------------ numbers and scores
def _coerce_fn(allow_ratio: bool):
    def fn(v: Any, c: int) -> Any:
        f = parse_number(v, allow_ratio=allow_ratio)
        return None if f is None else tidy_number(f)
    return fn


def _unreadable_flagger(col: str, ctx: Ctx):
    hide = ctx.sensitive(col)

    def flagger(v: Any) -> str | None:
        if parse_number(v, allow_ratio=True) is not None:
            return None
        return "not a number" if hide else f"not a number (was \"{safe_text(v, 40)}\")"
    return flagger


def build_coerce_numbers(ctx: Ctx, col: str, pov: dict) -> Step:
    kind = ctx.kind(col)
    what = "scores" if kind == "score" else "numbers"
    return mk("coerce_numbers", col, f"Read \"{col}\" as {what}",
              "Turn text such as $1,250, 45%, 1.250,50, (300) or 50k into plain numbers, and 4/5 into 4. "
              "Cells that cannot be read as a number become blank and are flagged (nothing is guessed).")


def run_coerce_numbers(ctx: Ctx, step: Step) -> Outcome:
    col = step.column
    ratio = ctx.kind(col) == "score"
    out = map_uniques(ctx, col, _coerce_fn(ratio), flagger=_unreadable_flagger(col, ctx))
    out.details["unreadable"] = out.details.pop("flagged_cells", 0)
    return out


SCALES = [(1, 5), (0, 5), (1, 7), (0, 10), (1, 10)]


def detect_scale(values: pd.Series) -> tuple[tuple[int, int] | None, float]:
    vals = values.dropna().astype(float)
    if len(vals) < 5:
        return None, 0.0
    cover = {s: float(((vals >= s[0]) & (vals <= s[1]) & (vals == vals.round())).mean()) for s in SCALES}
    best = max(cover.values())
    ok = [s for s in SCALES if cover[s] >= 0.95 and cover[s] >= best - 0.02]
    if not ok:
        return None, best
    s = min(ok, key=lambda x: (x[1] - x[0], x[0] == 0))
    return s, cover[s]


_HINT_RANGE = re.compile(r"(?<![\d.])([01])\s*(?:-|–|—|to)\s*(\d{1,3})(?![\d.])", re.I)
_HINT_OUTOF = re.compile(r"(?:out of|/)\s*(\d{1,3})(?![\d.])", re.I)


def header_scale(col: str, nums: pd.Series) -> tuple[int, int] | None:
    """A scale named in the column header: "0-10", "1 to 5", "out of 10", "/10". "out of N" and "/N" start at 0
    only if someone actually answered 0, otherwise at 1. Returns None when the header says nothing clear."""
    name = str(col)[:300]
    m = _HINT_RANGE.search(name)
    if m:
        lo, hi = int(m.group(1)), int(m.group(2))
        return (lo, hi) if 3 <= hi <= 100 and lo < hi else None
    m = _HINT_OUTOF.search(name)
    if m:
        hi = int(m.group(1))
        if 3 <= hi <= 100:
            vals = nums.dropna().astype(float)
            return (0 if len(vals) and float(vals.min()) == 0 else 1, hi)
    return None


def build_check_score_range(ctx: Ctx, col: str, pov: dict) -> Step | None:
    """Scale sources, most to least trusted: the user's own edit, a hint in the column header, then the observed
    values (lowest confidence: a 1 to 10 question where nobody picked above 7 looks like 1 to 7). Only the first
    two may blank values; a scale that came only from the data flags out-of-range answers and asks for confirmation."""
    nums = ctx.df[col].map(lambda v: parse_number(v, allow_ratio=True) if v is not None else None)
    chosen = pov.get("scale")
    detected, cov = detect_scale(nums)
    hint = header_scale(col, nums)
    if chosen:
        scale, source = tuple(chosen), "user"
        basis = "You set this scale."
    elif hint:
        scale, source = hint, "header"
        basis = f"The column name says {hint[0]} to {hint[1]}. If that is wrong, change it here."
    elif detected:
        scale, source = detected, "observed"
        basis = (f"Guessed from the answers only ({cov:.0%} fall inside it), so nothing is blanked. Answers outside it are "
                 "flagged; confirm or change the scale here, and only then will out-of-range answers be blanked.")
    else:
        return None
    action = ("are marked invalid (blank plus a flag with the original value)" if source != "observed"
              else "are flagged and kept until you confirm the scale")
    return mk("check_score_range", col, f"Check \"{col}\" is on a {scale[0]} to {scale[1]} scale",
              f"Answers outside {scale[0]} to {scale[1]} {action}. They are not rounded or moved into range. {basis}",
              {"scale": [int(scale[0]), int(scale[1])], "detected": list(detected) if detected else None,
               "scale_source": source})


def run_check_score_range(ctx: Ctx, step: Step) -> Outcome:
    col = step.column
    lo, hi = step.params["scale"]
    source = step.params.get("scale_source", "observed")  # plans stored before this field existed never blank
    blank = source in ("user", "header")
    hide = ctx.sensitive(col)

    def outside(v: Any) -> bool:
        f = parse_number(v)
        return f is not None and not lo <= f <= hi

    def fn(v: Any, c: int) -> Any:
        return None if blank and outside(v) else v

    def flagger(v: Any) -> str | None:
        if not outside(v):
            return None
        if blank:
            return "invalid (outside scale)" if hide else f"invalid, outside {lo} to {hi} (was {safe_text(v, 20)})"
        return ("outside the guessed scale, confirm the scale" if hide else
                f"outside the guessed {lo} to {hi} scale (was {safe_text(v, 20)}), confirm the scale")

    out = map_uniques(ctx, col, fn, flagger=flagger)
    n = out.details.pop("flagged_cells", 0)
    out.details.update({"scale": [lo, hi], "invalid": n if blank else 0, "outside_guessed_scale": 0 if blank else n,
                        "scale_source": source, "needs_confirmation": (not blank) and n > 0})
    if not blank and n:
        out.rows = out.cells = n  # reported as flagged even though nothing changed
        ctx.warnings.append(
            f"\"{safe_text(col, 80)}\": {n} answers look outside the guessed {lo} to {hi} scale. They were kept and "
            "flagged. Confirm the scale for this column; until you do, nothing is blanked.")
    return out


def _bounds(nums: list[float]) -> tuple[float, float] | None:
    if len(nums) < 8:
        return None
    q1, q3 = np.percentile(nums, [25, 75])
    iqr = q3 - q1
    if iqr <= 0:
        return None
    return float(q1 - 1.5 * iqr), float(q3 + 1.5 * iqr)


def build_flag_numeric_outliers(ctx: Ctx, col: str, pov: dict) -> Step | None:
    nums = [f for f in (parse_number(v) for v in ctx.df[col].dropna()) if f is not None]
    b = _bounds(nums)
    if b is None:
        return None
    return mk("flag_numeric_outliers", col, f"Flag unusual numbers in \"{col}\"",
              f"Mark numbers below {b[0]:,.4g} or above {b[1]:,.4g} (1.5 times the middle spread, worked out from this "
              "column). They stay in the data; they are only flagged so you can look at them.",
              {"low": b[0], "high": b[1]})


def run_flag_numeric_outliers(ctx: Ctx, step: Step) -> Outcome:
    col, lo, hi = step.column, float(step.params["low"]), float(step.params["high"])
    s = ctx.df[col]
    f = s.map(lambda v: parse_number(v) if v is not None else None)
    f = pd.to_numeric(f, errors="coerce")
    low, high = f < lo, f > hi
    ctx.flag_rows(s.index[low.fillna(False)], f"{col}: unusually low")
    ctx.flag_rows(s.index[high.fillna(False)], f"{col}: unusually high")
    n_l, n_h = int(low.sum()), int(high.sum())
    out = Outcome(rows=n_l + n_h, cells=n_l + n_h, details={"unusually_low": n_l, "unusually_high": n_h})
    if not ctx.sensitive(col):
        for label, mask in (("unusually low", low), ("unusually high", high)):
            for v in s[mask.fillna(False)].head(1):
                out.examples.append({"before": safe_text(v), "after": f"{safe_text(v, 40)} (flagged: {label})"})
    return out


# ------------------------------------------------------------------ dates
_NUMDATE = re.compile(
    r"^(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{1,4})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?(?:\.\d{1,6})?\s*(?:Z|[+-]\d{2}:?\d{2})?)?$"
)
YEAR_MIN, YEAR_MAX = 1900, 2100


def _classify(s: str) -> tuple[str, tuple[int, int, int, int, int, int] | None]:
    """('iso'|'ambiguous'|'dayfirst'|'monthfirst'|'impossible'|'other', parts). parts=(a,b,y,H,M,S) for slash forms."""
    m = _NUMDATE.match(s.strip())
    if not m:
        return "other", None
    g1, g2, g3, hh, mi, ss = m.groups()
    hh, mi, ss = int(hh or 0), int(mi or 0), int(ss or 0)
    if len(g1) == 4:
        y, mo, d = int(g1), int(g2), int(g3)
        return "iso", (d, mo, y, hh, mi, ss)
    if len(g3) not in (2, 4):
        return "other", None
    a, b = int(g1), int(g2)
    y = int(g3)
    if len(g3) == 2:
        y += 2000 if y <= 50 else 1900
    if a > 12 and b <= 12:
        return "dayfirst", (a, b, y, hh, mi, ss)
    if b > 12 and a <= 12:
        return "monthfirst", (a, b, y, hh, mi, ss)
    if a > 12 and b > 12:
        return "impossible", (a, b, y, hh, mi, ss)
    return ("ambiguous" if a != b else "iso_like"), (a, b, y, hh, mi, ss)


def date_evidence(values: pd.Series) -> Counter:
    vc = values.dropna().value_counts()
    ev: Counter = Counter()
    for v, c in vc.items():
        if isinstance(v, str):
            ev[_classify(v)[0]] += int(c)
    return ev


def build_parse_dates(ctx: Ctx, col: str, pov: dict) -> Step:
    ev = date_evidence(ctx.df[col])
    df_n, mf_n, amb = ev["dayfirst"], ev["monthfirst"], ev["ambiguous"]
    if "day_first" in pov and pov["day_first"] is not None:
        day_first, basis = bool(pov["day_first"]), "You chose this."
    elif df_n and not mf_n:
        day_first, basis = True, f"{df_n:,} date(s) have a first number above 12, so they can only be day first."
    elif mf_n and not df_n:
        day_first, basis = False, f"{mf_n:,} date(s) have a second number above 12, so they can only be month first."
    elif df_n and mf_n:
        day_first = df_n >= mf_n
        basis = (f"The file mixes both orders ({df_n:,} day first, {mf_n:,} month first). Dates that could be either "
                 f"are read as {'day' if day_first else 'month'} first, the more common order here.")
    elif amb:
        day_first = None
        basis = ("Nothing in the file shows which order is used, so slash dates like 03/04/2025 are read as month first "
                 "and flagged as ambiguous. Change the order below if that is wrong.")
    else:
        day_first, basis = None, "No day/month ambiguity found."
    return mk("parse_dates", col, f"Read \"{col}\" as dates",
              "Convert mixed date formats to one format (YYYY-MM-DD). Dates that cannot exist (31/02/2025, month 13) are "
              "blanked and flagged. " + basis,
              {"day_first": day_first, "basis": basis, "evidence": dict(ev)})


def _to_iso(v: Any, day_first: bool | None, stats: Counter) -> tuple[str | None, str | None]:
    """Returns (iso text or None, flag text or None)."""
    if isinstance(v, (datetime, pd.Timestamp)):
        if not YEAR_MIN <= v.year <= YEAR_MAX:
            stats["impossible"] += 1
            return None, "impossible date"
        return (v.date().isoformat() if v.hour == v.minute == v.second == 0 else v.strftime("%Y-%m-%d %H:%M:%S")), None
    if isinstance(v, date):
        if not YEAR_MIN <= v.year <= YEAR_MAX:
            stats["impossible"] += 1
            return None, "impossible date"
        return v.isoformat(), None
    if not isinstance(v, str):
        stats["unreadable"] += 1
        return None, "not a date"
    kind, parts = _classify(v)
    if parts is not None:
        a, b, y, hh, mi, ss = parts
        if kind in ("iso",):
            d, mo = a, b
        elif kind == "dayfirst":
            d, mo = a, b
        elif kind == "monthfirst":
            mo, d = a, b
        elif kind in ("ambiguous", "iso_like"):
            first_day = bool(day_first)
            d, mo = (a, b) if first_day else (b, a)
            if kind == "ambiguous":
                stats["ambiguous"] += 1
        else:
            stats["impossible"] += 1
            return None, "impossible date"
        try:
            dt = datetime(y, mo, d, hh, mi, ss)
        except ValueError:
            stats["impossible"] += 1
            return None, "impossible date"
        if not YEAR_MIN <= dt.year <= YEAR_MAX:
            stats["impossible"] += 1
            return None, "impossible date"
        return (dt.date().isoformat() if (hh, mi, ss) == (0, 0, 0) else dt.strftime("%Y-%m-%d %H:%M:%S")), (
            "ambiguous day/month order" if kind == "ambiguous" else None)
    try:
        ts = pd.to_datetime(v, format="mixed", errors="coerce", dayfirst=bool(day_first))
    except Exception:
        ts = pd.NaT
    if pd.isna(ts):
        stats["unreadable"] += 1
        return None, "not a date"
    return _to_iso(ts.to_pydatetime(), day_first, stats)


def run_parse_dates(ctx: Ctx, step: Step) -> Outcome:
    col, day_first = step.column, step.params.get("day_first")
    hide = ctx.sensitive(col)
    stats: Counter = Counter()
    vc = ctx.df[col].value_counts()
    weights = {v: int(c) for v, c in vc.items()}
    memo: dict[Any, tuple[str | None, str | None]] = {}

    def conv(v: Any) -> tuple[str | None, str | None]:
        if v not in memo:
            local: Counter = Counter()
            memo[v] = _to_iso(v, day_first, local)
            for k, n in local.items():
                stats[k] += n * weights.get(v, 1)
        return memo[v]

    def fn(v: Any, c: int) -> Any:
        return conv(v)[0]

    def flagger(v: Any) -> str | None:
        iso, flag = conv(v)
        if flag is None:
            return None
        if iso is None:
            return flag if hide else f"{flag} (was \"{safe_text(v, 30)}\")"
        return flag  # ambiguous but read: the value stays, the doubt is recorded

    out = map_uniques(ctx, col, fn, flagger=flagger)
    out.details.pop("flagged_cells", None)
    out.details.update({
        "day_first": day_first, "ambiguous": stats["ambiguous"], "impossible": stats["impossible"],
        "unreadable": stats["unreadable"],
    })
    if stats["ambiguous"]:
        order = "day first" if day_first else "month first"
        ctx.warnings.append(
            f"\"{col}\": {stats['ambiguous']:,} date(s) could be day first or month first; they were read as {order} and flagged."
        )
    return out


# ------------------------------------------------------------------ segments and yes/no
_YES = {"yes", "y", "yeah", "yep", "yup", "true", "t", "1", "1.0", "ok"}
_NO = {"no", "n", "nope", "nah", "false", "f", "0", "0.0"}


def build_standardise_labels(ctx: Ctx, col: str, pov: dict) -> Step | None:
    vc = ctx.df[col].map(lambda v: v if isinstance(v, str) else (None if v is None else str(v))).value_counts()
    entries, notes = build_merge_table(vc, None)
    hide_small_counts(ctx, col, entries)
    return mk("standardise_labels", col, f"Standardise the labels in \"{col}\"",
              "Join labels that differ only by capital letters, spacing or punctuation into the most common form. "
              "Review the table below and untick or edit any merge.",
              {"merges": entries, "table_notes": notes})


def build_standardise_yes_no(ctx: Ctx, col: str, pov: dict) -> Step | None:
    vc = ctx.df[col].map(lambda v: None if v is None else str(v).strip()).value_counts()
    entries = []
    for v, c in vc.items():
        k = v.lower()
        to = "Yes" if k in _YES else "No" if k in _NO else None
        if to and v != to:
            entries.append({"from": v, "to": to, "count": int(c), "how": "yes/no label", "enabled": True})
    entries.sort(key=lambda e: (-e["count"], e["from"]))
    hide_small_counts(ctx, col, entries)
    return mk("standardise_yes_no", col, f"Standardise yes/no answers in \"{col}\"",
              "Turn Y, yes, YES, true and 1 into Yes, and N, no, false and 0 into No. Answers that are neither are left "
              "as they are and counted.", {"merges": entries[:TABLE_CAP], "table_notes": []})


def run_standardise_yes_no(ctx: Ctx, step: Step) -> Outcome:
    col = step.column
    mapping = {e["from"]: e["to"] for e in step.params.get("merges", []) if e.get("enabled", True) and e.get("to")}

    def fn(v: Any, c: int) -> Any:
        key = v if isinstance(v, str) else str(v)
        return mapping.get(key.strip(), v if isinstance(v, str) else key.strip())

    out = map_uniques(ctx, col, fn)
    left = ctx.df[col].dropna().map(lambda v: str(v).strip().lower() not in {"yes", "no"}).sum()
    out.details["other_answers_left"] = int(left)
    return out


def build_merge_small_groups(ctx: Ctx, col: str, pov: dict) -> Step | None:
    vc = ctx.df[col].value_counts()
    n = int(vc.sum())
    sensitive = ctx.sensitive(col)
    default_min = int(ctx.settings["min_group_size"]) if sensitive else max(2, math.ceil(0.01 * n))
    min_count = int(pov.get("min_count") or default_min)
    other = next((v for v in vc.index if isinstance(v, str) and v.strip().lower() == "other"), "Other")
    small = [(v, int(c)) for v, c in vc.items() if int(c) < min_count and v != other]
    kept = [v for v, c in vc.items() if int(c) >= min_count]
    if len(small) < 2 and not (small and other in vc.index) or len(kept) < 2:
        return None
    entries = [{"from": v, "to": other, "count": c, "how": f"fewer than {min_count} answers", "enabled": True}
               for v, c in sorted(small, key=lambda t: (-t[1], str(t[0])))][:TABLE_CAP]
    hide_small_counts(ctx, col, entries)
    return mk("merge_small_groups", col, f"Group very small answers in \"{col}\" as \"{other}\"",
              f"Groups with fewer than {min_count} answers are merged into \"{other}\" so charts are not cluttered by tiny "
              f"groups. The limit is {'the minimum group size for sensitive columns' if sensitive else '1% of the answers (at least 2)'}; "
              "change it and the table updates. Untick any group you want to keep.",
              {"min_count": min_count, "merges": entries, "table_notes": []}, enabled=not sensitive)


run_standardise_labels = run_merge_table
run_merge_small_groups = run_merge_table
