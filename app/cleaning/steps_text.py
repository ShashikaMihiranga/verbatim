"""Cleaning steps for open_text and short_text columns, plus the reusable merge table.

Each run_* is a small function over the distinct values of one column. Thresholds that depend on the data
(vowel floor for keyboard mash, length outlier bounds, fuzzy cut-off) are computed in build_* at plan time and
stored in the step's params, so the review screen can show them and apply reuses exactly the same numbers.
"""
from __future__ import annotations

import math
import re
import unicodedata
from typing import Any

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process
from rapidfuzz.distance import OSA

from .common import MAX_CELL_CHARS, Ctx, Outcome, is_blank, map_uniques, safe_text
from .models import Step
from .redact import LABELS, redact_text, summarise

_WS = re.compile(r"\s+")
_HIDDEN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁠⁦-⁩﻿]")


def mk(key: str, col: str | None, title: str, description: str, params: dict | None = None, enabled: bool = True) -> Step:
    return Step(id=f"{key}:{col}" if col else key, key=key, column=col, title=title, description=description,
                enabled=enabled, params=params or {})


# ------------------------------------------------------------------ normalise
def normalise_value(v: Any) -> Any:
    if not isinstance(v, str):
        return str(v)
    s = unicodedata.normalize("NFKC", v)
    s = _HIDDEN.sub("", s)
    s = _WS.sub(" ", s).strip()
    if len(s) > MAX_CELL_CHARS:
        s = s[:MAX_CELL_CHARS]
    return s


def build_normalise_text(ctx: Ctx, col: str, pov: dict) -> Step:
    return mk("normalise_text", col, f"Tidy the spacing and characters in \"{col}\"",
              "Trim spaces, collapse repeated spaces and line breaks, standardise unicode (for example curly or "
              "full-width characters), remove hidden control characters, and turn stray numbers into text.")


def run_normalise_text(ctx: Ctx, step: Step) -> Outcome:
    col = step.column
    out = map_uniques(ctx, col, lambda v, c: normalise_value(v))
    # a cell that is only spaces becomes blank
    blanks = ctx.df[col].map(lambda v: isinstance(v, str) and not v)
    n = int(blanks.sum())
    if n:
        ctx.df.loc[blanks, col] = None
        out.cells += n
        out.rows += n
        out.details["emptied"] = n
    return out


# ------------------------------------------------------------------ PII
def build_mask_pii(ctx: Ctx, col: str, pov: dict) -> Step:
    return mk("mask_pii", col, f"Mask personal details in \"{col}\"",
              "Replace emails, phone numbers, links and obvious ID numbers with [email], [phone], [link] and [id]. "
              "Text is masked before it can be sent to any model. Names and addresses are not detected.")


def run_mask_pii(ctx: Ctx, step: Step) -> Outcome:
    col, totals = step.column, {k: 0 for k in LABELS}
    hits: list[tuple[int, str, str]] = []

    def fn(v: Any, c: int) -> Any:
        if not isinstance(v, str):
            return v
        masked, counts = redact_text(v)
        for k, n in counts.items():
            totals[k] += n * c
        if masked != v:
            hits.append((c, v, masked))
        return masked

    out = map_uniques(ctx, col, fn)
    out.examples = []
    if not ctx.sensitive(col):
        # "before" keeps two characters of each hidden item so a reviewer can recognise it; masking happens
        # before truncation so a cut-off email can never leak.
        for c, v, masked in sorted(hits, key=lambda t: (-t[0], t[1]))[:3]:
            out.examples.append({"before": safe_text(redact_text(v, partial=True)[0]), "after": safe_text(masked)})
    for k, n in totals.items():
        ctx.pii[k] += n
    out.details.update({"counts": totals, "summary": summarise(totals)})
    return out


# ------------------------------------------------------------------ non-answers
_NA = {
    "na", "none", "nothing", "nil", "null", "idk", "dunno", "i dont know", "i do not know", "dont know",
    "do not know", "no comment", "not applicable", "no answer", "nothing to add", "nothing else", "none at all",
    "no idea", "nothing really", "n a",
}


def _na_key(s: str) -> str:
    s = s.lower().replace("'", "").replace("’", "")
    s = re.sub(r"[^\w\s]", "", s)
    return _WS.sub(" ", s).strip()


def is_non_answer(v: Any) -> bool:
    if not isinstance(v, str):
        return False
    if all(unicodedata.category(ch)[0] in "PZC" for ch in v):
        return True  # only punctuation or spaces: "-", "...", "?"
    k = _na_key(v)
    return k in _NA or (len(k) == 1 and k.isalpha())


def build_blank_non_answers(ctx: Ctx, col: str, pov: dict) -> Step:
    return mk("blank_non_answers", col, f"Blank non-answers in \"{col}\"",
              "Treat answers like n/a, none, nothing, idk, - and ... as blank. The row stays (its other columns still "
              "count); only this cell becomes blank so it is left out of the themes.")


def run_blank_non_answers(ctx: Ctx, step: Step) -> Outcome:
    return map_uniques(ctx, step.column, lambda v, c: None if is_non_answer(v) else v)


# ------------------------------------------------------------------ keyboard mash
_ROWS = ("qwertyuiop", "asdfghjkl", "zxcvbnm")
_RUNS = {r[i:i + 4] for row in _ROWS for r in (row, row[::-1]) for i in range(len(row) - 3)}
_LAUGH = re.compile(r"^(?:ha|he|ho|hi|lol|lo|ah|eh)+$")
_VOWELS = set("aeiouy")


def _vowel_ratio(t: str) -> float:
    return sum(ch in _VOWELS for ch in t) / len(t)


def vowel_floor(values: list[str]) -> float | None:
    """Data-derived: a quarter of this column's typical vowel share, kept between 0.05 and 0.12."""
    ratios = []
    for v in values:
        for t in re.findall(r"[A-Za-z]{4,}", v)[:8]:
            ratios.append(_vowel_ratio(t.lower()))
        if len(ratios) > 20_000:
            break
    if len(ratios) < 30:
        return None
    return float(min(0.12, max(0.05, 0.25 * float(np.median(ratios)))))


def is_mash_token(tok: str, floor: float | None) -> bool:
    t = tok.lower()
    if not (t.isascii() and t.isalpha()) or _LAUGH.match(t):
        return False
    if len(t) >= 2 and len(set(t)) == 1:
        return True
    if len(t) >= 4 and any(t[i:i + 4] in _RUNS for i in range(len(t) - 3)):
        return True
    if len(t) >= 6 and len(set(t)) <= 2:
        return True
    return bool(floor is not None and len(t) >= 6 and _vowel_ratio(t) < floor)


def is_mash(text: Any, floor: float | None) -> bool:
    if not isinstance(text, str):
        return False
    squashed = re.sub(r"\s", "", text)
    if len(squashed) >= 2 and len(set(squashed)) == 1:
        return True  # "....", "!!!!", "xxxx", "0000"
    toks = re.findall(r"[^\W_]+", text)
    return 0 < len(toks) <= 3 and all(is_mash_token(t, floor) for t in toks)


def build_blank_keyboard_mash(ctx: Ctx, col: str, pov: dict) -> Step:
    vals = [v for v in ctx.df[col].dropna().unique()[:20_000] if isinstance(v, str)]
    floor = vowel_floor(vals)
    return mk("blank_keyboard_mash", col, f"Blank keyboard mash in \"{col}\"",
              "Treat answers such as asdf, hjkl, aaaaa or xxxx (one repeated character, a run of neighbouring keys, "
              "or a long word with almost no vowels for this column) as blank. "
              + (f"The vowel cut-off ({floor:.2f}) comes from how vowels appear in this column's answers."
                 if floor is not None else "This column has too few words to set a vowel cut-off, so only the first two rules apply."),
              {"vowel_floor": None if floor is None else round(floor, 3)})


def run_blank_keyboard_mash(ctx: Ctx, step: Step) -> Outcome:
    floor = step.params.get("vowel_floor")
    return map_uniques(ctx, step.column, lambda v, c: None if is_mash(v, floor) else v)


# ------------------------------------------------------------------ length outliers
def _words(v: Any) -> int | None:
    return len(v.split()) if isinstance(v, str) else None


def build_flag_length_outliers(ctx: Ctx, col: str, pov: dict) -> Step | None:
    w = ctx.df[col].dropna().map(_words).dropna().astype(int)
    if len(w) < 20:
        return None
    lw = np.log1p(w.to_numpy())
    q1, q3 = np.percentile(lw, [25, 75])
    iqr = q3 - q1
    if iqr <= 0:
        return None
    lo = int(math.floor(math.expm1(q1 - 1.5 * iqr)))
    hi = int(math.ceil(math.expm1(q3 + 3 * iqr)))
    lo = lo if lo >= 1 else 0
    return mk("flag_length_outliers", col, f"Flag very short and very long answers in \"{col}\"",
              f"Mark answers under {lo + 1} words or over {hi} words (limits worked out from how long answers "
              "usually are in this column). They are flagged for review, not removed.",
              {"min_words": lo, "max_words": hi})


def run_flag_length_outliers(ctx: Ctx, step: Step) -> Outcome:
    col, lo, hi = step.column, int(step.params["min_words"]), int(step.params["max_words"])
    s = ctx.df[col]
    w = s.map(_words)
    short = (w < lo) if lo else pd.Series(False, index=s.index)
    long_ = w > hi
    short, long_ = short.fillna(False), long_.fillna(False)
    ctx.flag_rows(s.index[short], f"{col}: very short answer")
    ctx.flag_rows(s.index[long_], f"{col}: very long answer")
    n_s, n_l = int(short.sum()), int(long_.sum())
    out = Outcome(rows=n_s + n_l, cells=n_s + n_l, details={"very_short": n_s, "very_long": n_l})
    if not ctx.sensitive(col):
        for label, mask in (("very short", short), ("very long", long_)):
            for v in s[mask].head(1):
                out.examples.append({"before": safe_text(v), "after": f"{safe_text(v, 60)} (flagged: {label})"})
    return out


# ------------------------------------------------------------------ merge tables
def _key(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = re.sub(r"[^\w\s]", " ", s.casefold())
    return _WS.sub(" ", s).strip()


def fuzzy_cutoff(distinct: int) -> int:
    """More distinct values means more risk of false merges, so the bar goes up."""
    return 86 if distinct <= 30 else 90 if distinct <= 300 else 93


FUZZY_MAX_DISTINCT = 3000
TABLE_CAP = 500


def _safe_merge(k: str, target: str, total: dict[str, int]) -> bool:
    """Reject merges that would join genuinely different answers: different digits (Model 3 / Model Y), a rarer
    answer that is not rarer than its target, or names that differ only in a one- or two-letter token (Model X / Model Y)."""
    if re.sub(r"\D", "", k) != re.sub(r"\D", "", target) or total[k] > total[target]:
        return False
    a, b = k.split(), target.split()
    if len(a) == len(b) and any(x != y and max(len(x), len(y)) <= 2 for x, y in zip(a, b)):
        return False
    return True


def build_merge_table(vc: pd.Series, cutoff: int | None) -> tuple[list[dict[str, Any]], list[str]]:
    """Group values whose normalised key is the same (case, spacing, punctuation, accents), then optionally
    join rare spelling variants to a more common value with rapidfuzz ratio >= cutoff.
    Returns (entries, notes). Entry: {from, to, count, how, enabled}."""
    groups: dict[str, list[tuple[str, int]]] = {}
    for v, c in vc.items():
        if isinstance(v, str) and len(v) <= 200:  # very long values are never offered for merging
            groups.setdefault(_key(v) or v, []).append((v, int(c)))
    canon: dict[str, str] = {}
    total: dict[str, int] = {}
    entries: list[dict[str, Any]] = []
    for k, items in groups.items():
        best = max(items, key=lambda t: (t[1], t[0].istitle(), t[0]))[0]
        canon[k], total[k] = best, sum(c for _, c in items)
        for raw, c in items:
            if raw != best:
                entries.append({"from": raw, "to": best, "count": c, "how": "same after ignoring case and spacing", "enabled": True})
    notes: list[str] = []
    if cutoff is not None:
        if len(groups) > FUZZY_MAX_DISTINCT:
            notes.append(f"More than {FUZZY_MAX_DISTINCT:,} different values, so only case and spacing were merged.")
        else:
            keep: list[str] = []
            one_edit_ok = len(groups) <= 300  # single-letter typos are only trusted when there are few answers
            for k in sorted(groups, key=lambda x: (-total[x], x)):
                target, how = None, ""
                if len(k) >= 5 and keep:
                    m = process.extractOne(k, keep, scorer=fuzz.ratio, score_cutoff=cutoff)
                    if m:
                        target, how = m[0], f"looks like a spelling variant (match {round(m[1])}%)"
                    elif one_edit_ok:
                        m = process.extractOne(k, keep, scorer=OSA.distance, score_cutoff=1)
                        if m:
                            target, how = m[0], "one letter different (typo or swapped letters)"
                    if target is not None and not _safe_merge(k, target, total):
                        target = None
                if target is None:
                    keep.append(k)
                    continue
                for raw, c in groups[k]:
                    entries.append({"from": raw, "to": canon[target], "count": c, "how": how, "enabled": True})
    entries.sort(key=lambda e: (-e["count"], e["from"]))
    if len(entries) > TABLE_CAP:
        notes.append(f"Showing the {TABLE_CAP} most common of {len(entries)} merges; the rest are left as they are.")
        entries = entries[:TABLE_CAP]
    return entries, notes


def hide_small_counts(ctx: Ctx, col: str, entries: list[dict[str, Any]]) -> None:
    """Sensitive columns: a count under the minimum group size is never shown."""
    if ctx.sensitive(col):
        m = int(ctx.settings["min_group_size"])
        for e in entries:
            if e.get("count") is not None and e["count"] < m:
                e["count"] = None


def build_merge_variants(ctx: Ctx, col: str, pov: dict) -> Step | None:
    vc = ctx.df[col].value_counts()
    cutoff = fuzzy_cutoff(len(vc))
    entries, notes = build_merge_table(vc, cutoff)
    hide_small_counts(ctx, col, entries)
    return mk("merge_variants", col, f"Merge spelling variants in \"{col}\"",
              "Join answers that differ only by capital letters, spacing or a typo (for example \"Tesla\", \"tesla\", "
              f"\"Telsa\") into the most common form. Review the table below and untick or edit any merge. "
              f"Typos are matched at {cutoff}% similarity, stricter when there are many different answers.",
              {"cutoff": cutoff, "merges": entries, "table_notes": notes})


def run_merge_table(ctx: Ctx, step: Step) -> Outcome:
    mapping = {e["from"]: e["to"] for e in step.params.get("merges", []) if e.get("enabled", True) and e.get("to")}
    out = map_uniques(ctx, step.column, lambda v, c: mapping.get(v, v) if isinstance(v, str) else v)
    out.details["merged_values"] = out.details.pop("distinct_changed", 0)
    return out


run_merge_variants = run_merge_table
