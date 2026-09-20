"""Whole-file steps: empty rows/columns, repeated answers, identical rows, and excluded columns."""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .common import Ctx, Outcome, is_blank, safe_text
from .models import Step
from .steps_text import mk


# ------------------------------------------------------------------ empty rows and columns
def build_drop_empty_rows(ctx: Ctx, col: None = None, pov: dict | None = None) -> Step:
    return mk("drop_empty_rows", None, "Remove completely empty rows",
              "Rows where every cell is blank are removed from the cleaned copy. Each one is listed by row number in the report.")


def run_drop_empty_rows(ctx: Ctx, step: Step) -> Outcome:
    if ctx.df.empty:
        return Outcome()
    blank = ctx.df.map(is_blank).all(axis=1)
    idx = list(ctx.df.index[blank])
    ctx.remove_rows(idx, step.id, "the whole row was empty")
    return Outcome(rows=len(idx), cells=len(idx) * ctx.df.shape[1], details={"row_numbers": [i + 1 for i in idx[:20]]})


def build_drop_empty_columns(ctx: Ctx, col: None = None, pov: dict | None = None) -> Step:
    return mk("drop_empty_columns", None, "Remove completely empty columns",
              "Columns with no answers at all are left out of the cleaned copy. Your original file is never changed.")


def run_drop_empty_columns(ctx: Ctx, step: Step) -> Outcome:
    empty = [c for c in ctx.df.columns if ctx.df[c].map(is_blank).all()]
    for c in empty:
        ctx.removed_columns.append({"name": safe_text(c, 120), "reason": "every cell was empty"})
    ctx.df = ctx.df.drop(columns=empty)
    return Outcome(rows=0, cells=len(empty), details={"columns": [safe_text(c, 120) for c in empty]})


# ------------------------------------------------------------------ repeated answers
def build_collapse_duplicate_answers(ctx: Ctx, col: None = None, pov: dict | None = None) -> Step | None:
    cols = [c for c in ctx.df.columns if ctx.kind(c) == "open_text"]
    if not cols:
        return None
    words = []
    for c in cols:
        words.extend(len(v.split()) for v in ctx.df[c].dropna().unique()[:20_000] if isinstance(v, str))
    if not words:
        return None
    p75 = float(np.percentile(words, 75))
    min_words = int(min(10, max(3, round(p75))))
    return mk("collapse_duplicate_answers", None, "Collapse exact repeats of the same long answer",
              f"When several rows contain exactly the same open-ended answer of at least {min_words} words (the limit is set from "
              "how long answers usually are in this file), keep the first row and remove the repeats. The kept row records how "
              "many copies there were. Short answers such as \"Price\" are never collapsed because many people genuinely say them.",
              {"columns": cols, "min_words": min_words})


def run_collapse_duplicate_answers(ctx: Ctx, step: Step) -> Outcome:
    cols = [c for c in step.params["columns"] if c in ctx.df.columns]
    min_words = int(step.params["min_words"])
    if not cols or ctx.df.empty:
        return Outcome()
    parts = ctx.df[cols].map(lambda v: " ".join(v.casefold().split()) if isinstance(v, str) else "")
    key = parts.iloc[:, 0] if len(cols) == 1 else parts.apply(lambda r: "\x1f".join(r), axis=1)
    eligible = key.str.count(r"\S+") >= min_words
    idx_series = pd.Series(ctx.df.index, index=ctx.df.index)
    first = idx_series.groupby(key).transform("first")
    size = key.map(key.value_counts())
    dup = eligible & (idx_series != first)
    kept = eligible & (idx_series == first) & (size > 1)
    for i, n in zip(ctx.df.index[kept], size[kept]):
        ctx.dup_counts[i] = int(n)
    removed = list(ctx.df.index[dup])
    for i in removed:
        ctx.removed[i] = (step.id, f"exact repeat of the answer in row {int(first[i]) + 1}")
    out = Outcome(rows=len(removed), cells=len(removed), details={"answers_repeated": int(kept.sum()),
                                                                 "columns": [safe_text(c, 120) for c in cols]})
    if not any(ctx.sensitive(c) for c in cols):
        top = size[kept].sort_values(ascending=False).head(3)
        for i, n in top.items():
            out.examples.append({"before": f"{n} rows: {safe_text(ctx.df.loc[i, cols[0]])}",
                                 "after": f"1 row kept, {n - 1} repeat(s) removed"})
    if removed:
        ctx.df = ctx.df.drop(index=removed)
    return out


# ------------------------------------------------------------------ identical rows (report only)
def build_report_duplicate_rows(ctx: Ctx, col: None = None, pov: dict | None = None) -> Step:
    return mk("report_duplicate_rows", None, "Report rows that are identical in every column",
              "Rows that match an earlier row in every column are flagged, not removed: without an ID column we cannot "
              "tell a double submission from two people giving the same answers.")


def run_report_duplicate_rows(ctx: Ctx, step: Step) -> Outcome:
    if ctx.df.empty:
        return Outcome()
    dup = ctx.df.astype(str).duplicated(keep="first")
    idx = list(ctx.df.index[dup])
    ctx.flag_rows(idx, "identical to an earlier row")
    return Outcome(rows=len(idx), cells=len(idx), details={"row_numbers": [i + 1 for i in idx[:20]]})


# ------------------------------------------------------------------ ignored columns
def build_exclude_columns(ctx: Ctx, col: None = None, pov: dict | None = None) -> Step | None:
    cols = [c for c in ctx.df.columns if ctx.kind(c) == "id_or_junk"]
    if not cols:
        return None
    return mk("exclude_columns", None, "Leave ID and junk columns out of the analysis",
              "Columns marked as IDs, personal details or junk are kept in the file but not used for themes, charts or "
              "findings. Nothing is deleted.", {"columns": cols})


def run_exclude_columns(ctx: Ctx, step: Step) -> Outcome:
    cols = [c for c in step.params.get("columns", []) if c in ctx.df.columns]
    ctx.excluded = cols
    return Outcome(details={"columns": [safe_text(c, 120) for c in cols], "always_report": True})
