"""Column profiler (SPEC sections 3 and 9.1). Pure functions, no network.

Every guess carries a confidence and a one-sentence reason, because the user
confirms each one on the Check columns screen. Work is done on distinct values
(Counter) so 50,000 rows profile in well under a second.
"""
from __future__ import annotations

import re
import statistics
from collections import Counter
from datetime import date, datetime
from typing import Any

import pandas as pd

def _segment_max_distinct(n: int) -> int:
    """Segment's distinct-value ceiling scales with row count instead of staying fixed at 12 - a column
    with 15-20 distinct, heavily-repeated values in a 1,000+-row dataset is exactly as categorical as one
    with <=12 distinct values in a small dataset; a cap that never grows was blind to dataset scale.
    Floor 12 (today's behaviour, unchanged for every existing small-dataset case), ceiling 30 (past that,
    a heatmap/filter with this many groups stops being a useful "small number of groups" breakdown
    regardless of how repetitive the underlying text is - SPEC.md section 3's own "2 to 12" framing)."""
    return max(12, min(30, round(n / 80)))


KINDS = ["open_text", "short_text", "score", "date", "segment", "numeric", "yes_no", "id_or_junk"]
KIND_LABELS = {
    "open_text": "Open-ended text",
    "short_text": "Short text",
    "score": "Score",
    "date": "Date",
    "segment": "Segment",
    "numeric": "Number",
    "yes_no": "Yes / no",
    "id_or_junk": "Ignored",
}

# ------------------------------------------------------------ name hints
_SCORE_HINT = re.compile(r"score|rating|rate|likelihood|likely|satisf|nps|recommend|agree|scale|stars?|rank")
_ID_TOKENS = {"id", "uuid", "guid", "ref", "reference", "index", "serial", "record", "respondent", "row", "key"}
_PERSON_TOKENS = {"name", "firstname", "lastname", "surname", "email", "phone", "mobile", "address", "ip"}
_QUESTION_HINT = re.compile(r"question|prompt")
_DATE_HINT = re.compile(r"date|time|timestamp|month|created|submitted|day$")
_SENSITIVE_TOKENS = {
    "age": "age", "agegroup": "age", "ageband": "age", "agerange": "age", "dob": "date of birth", "birth": "date of birth",
    "birthday": "date of birth", "gender": "gender", "sex": "sex", "income": "income", "salary": "income", "wage": "income",
    "earnings": "income", "ethnicity": "ethnicity", "ethnic": "ethnicity", "race": "race", "religion": "religion",
    "disability": "disability", "marital": "marital status", "orientation": "sexual orientation",
    "postcode": "location", "zip": "location", "zipcode": "location", "nationality": "nationality",
}
_UNIT_HINT = [
    ("currency", re.compile(r"income|salary|wage|price|cost|spend|revenue|pay|earn|budget|fee")),
    ("percent", re.compile(r"percent|pct|share|rate_of|%")),
    ("years", re.compile(r"\bage\b|years?|tenure|yrs|seniority")),
]

_MALE_FEMALE = {"male", "female", "m", "f", "man", "woman", "men", "women", "non-binary", "nonbinary", "non binary",
                "other", "prefer not to say", "prefer to self-describe", "trans", "transgender"}
_YES = {"yes", "y", "true", "t", "yeah", "yep"}
_NO = {"no", "n", "false", "f", "nope"}
_AGE_BAND = re.compile(r"^(under\s*)?\d{1,2}\s*(-|to|–)\s*\d{1,2}$|^\d{2}\s*\+$|^(over|under)\s*\d{2}$", re.I)

_NUM_RE = re.compile(r"^[-+]?\s*[$€£¥]?\s*[-+]?(\d[\d,]*)?(\.\d+)?\s*%?$")
_DECIMAL_COMMA = re.compile(r"^[-+]?\d+,\d{1,2}$")
_DATE_LIKE = re.compile(
    r"(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4})|(\d{4}-\d{2}-\d{2}T)|"
    r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b",
    re.I,
)
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _tokens(name: str) -> list[str]:
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
    return [t for t in re.split(r"[^A-Za-z0-9]+", spaced.lower()) if t]


def _parse_number(v: Any) -> float | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if not isinstance(v, str):
        return None
    s = v.strip()
    if not s or not _NUM_RE.match(s) or not any(ch.isdigit() for ch in s):
        if _DECIMAL_COMMA.match(s):
            return float(s.replace(",", "."))
        return None
    core = re.sub(r"[$€£¥%\s]", "", s)
    if _DECIMAL_COMMA.match(core):
        return float(core.replace(",", "."))
    try:
        return float(core.replace(",", ""))
    except ValueError:
        return None


def _words(v: Any) -> int:
    return len(str(v).split())


def _samples(cnt: Counter, sensitive: bool) -> list[str]:
    # Most common distinct values (not row order), so no row can be pinpointed.
    out = []
    for v, _ in cnt.most_common(5):
        s = v.isoformat() if isinstance(v, (date, datetime)) else str(v)
        out.append(s if len(s) <= 90 else s[:87] + "...")
    return out if not sensitive else out[:3]


def _parse_dates(distinct: list[Any]) -> list[date] | None:
    """Return parsed dates if >=85% of the distinct values parse as dates, else None."""
    if not distinct:
        return None
    if all(isinstance(v, (date, datetime)) for v in distinct):
        return [v.date() if isinstance(v, datetime) else v for v in distinct]
    strs = [v for v in distinct if isinstance(v, str)]
    if len(strs) < 0.85 * len(distinct):
        return None
    if sum(1 for v in strs if _DATE_LIKE.search(v)) < 0.85 * len(strs):
        return None
    step = max(1, len(strs) // 400)
    sample = strs[::step][:400]
    parsed = pd.to_datetime(pd.Series(sample), format="mixed", errors="coerce", dayfirst=False)
    if parsed.notna().mean() < 0.85:
        return None
    parsed_all = pd.to_datetime(pd.Series(strs), format="mixed", errors="coerce")
    return [d.date() for d in parsed_all.dropna()]


def _header_looks_like_data(name: str, kind: str, cnt: Counter) -> bool:
    """True when the header cell itself reads as a data value of this column's own kind, not a label -
    the "this sheet has no real header row" signal (docs/TODO.md, 2026-10-21). `_header_like`
    (loader.py) already decides, at the whole-ROW level, whether the first row of the sheet is used as
    the header at all; this is the per-COLUMN check layered on top of that decision - a row can be
    text-majority overall (so loader.py accepts it as a header) while individual cells are still data
    (a name, a date, a yes/no answer), not labels."""
    probe = name.strip()
    if not probe:
        return False
    low = probe.lower()
    if kind in ("numeric", "score"):
        return _parse_number(probe) is not None
    if kind == "date":
        return bool(_DATE_LIKE.search(probe)) and _parse_dates([probe]) is not None
    if kind == "yes_no":
        return low in (_YES | _NO) or low in _MALE_FEMALE
    if kind in ("segment", "short_text", "open_text"):
        return any(str(v).strip().lower() == low for v in cnt)  # header repeats as its own data value
    return False  # id_or_junk: too ambiguous to call either way


def _sensitive_by_name(name: str) -> str | None:
    for t in _tokens(name):
        if t in _SENSITIVE_TOKENS:
            return f"The name looks like {_SENSITIVE_TOKENS[t]}."
    joined = "".join(_tokens(name))
    for key in ("agegroup", "ageband", "agerange", "dateofbirth", "yearofbirth"):
        if key in joined:
            return "The name looks like age or date of birth."
    return None


def _sensitive_by_values(cnt: Counter, n: int) -> str | None:
    strs = [(str(v).strip().lower(), c) for v, c in cnt.items() if isinstance(v, str)]
    if not strs or not n:
        return None
    if sum(c for v, c in strs if v in _MALE_FEMALE) >= 0.6 * n and any(v in ("male", "female", "m", "f", "man", "woman") for v, _ in strs):
        return "The answers look like gender."
    if sum(c for v, c in strs if _AGE_BAND.match(v)) >= 0.6 * n:
        return "The answers look like age bands."
    return None


def profile_column(name: str, values: list[Any], position: int = 0, total_rows: int | None = None) -> dict[str, Any]:
    """Profile one column. `values` includes None for missing cells."""
    total = total_rows if total_rows is not None else len(values)
    non_missing = [v for v in values if v is not None]
    n = len(non_missing)
    cnt: Counter = Counter(non_missing)
    distinct = len(cnt)
    missing = total - n
    toks = _tokens(name)
    lname = name.lower()
    # Computed here (not just where open_text/short_text use it below) so every returned column - any
    # kind - carries it: the frontend's open-text auto-pick (Themes.tsx::pickOpenTextColumn) uses it as a
    # tie-break between multiple genuinely-unique open_text candidates (prefer the richer, longer-answer
    # one), which needs this on every open_text candidate's own profile, not just whichever branch below
    # happens to already compute it for its own reason text.
    wcounts = [_words(v) for v in non_missing[:5000]]
    med_words = statistics.median(wcounts) if wcounts else 0

    sens = _sensitive_by_name(name) or _sensitive_by_values(cnt, n)
    kind, conf, reason, unit = "id_or_junk", 0.9, "", None
    is_question = False

    def out() -> dict[str, Any]:
        return {
            "name": name, "position": position, "kind": kind, "confidence": round(conf, 2), "reason": reason,
            "unit": unit, "distinct": distinct, "missing": missing, "samples": _samples(cnt, bool(sens)),
            "sensitive": bool(sens), "sensitive_reason": sens, "is_question": is_question,
            "median_words": round(med_words, 1),
            "looks_headerless": _header_looks_like_data(name, kind, cnt),
        }

    if n == 0:
        reason = "Every cell in this column is empty."
        conf = 0.99
        return out()

    # ---- the survey question repeated on every row
    top_val, top_c = cnt.most_common(1)[0]
    if isinstance(top_val, str) and n >= 2 and top_c / n >= 0.95 and (
        top_val.rstrip().endswith("?") or _words(top_val) >= 5 or (_QUESTION_HINT.search(lname) and distinct == 1)
    ):
        kind, conf, is_question = "id_or_junk", 0.9, True
        reason = "The same question is repeated on every row, so we use it as the question text and ignore the column."
        return out()

    # ---- native or text dates
    parsed = _parse_dates(list(cnt))
    if parsed is not None and len(set(parsed)) >= 3:
        kind = "date"
        conf = 0.95 if (_DATE_HINT.search(lname) or all(isinstance(v, (date, datetime)) for v in cnt)) else 0.85
        span = f"{min(parsed).isoformat()} to {max(parsed).isoformat()}"
        reason = f"Values read as dates, {span}, so we can show change over time."
        if sens and "birth" in sens:
            conf = 0.8
        return out()

    # ---- yes / no
    lowered = {str(v).strip().lower() for v in cnt}
    if 1 <= distinct <= 2 or lowered <= (_YES | _NO):
        if distinct >= 2 and lowered <= (_YES | _NO) and lowered & _YES and lowered & _NO:
            kind, conf = "yes_no", 0.95
            reason = "Only two answers, yes and no, so it works as a group split."
            return out()

    # ---- numbers
    num = {v: _parse_number(v) for v in cnt}
    num_weight = sum(c for v, c in cnt.items() if num[v] is not None)
    if num_weight / n >= 0.9:
        nums = [num[v] for v in cnt if num[v] is not None]
        lo, hi = min(nums), max(nums)
        all_int = all(float(x).is_integer() for x in nums)
        half_steps = all((x * 2).is_integer() for x in nums)
        raw_strs = [v for v in cnt if isinstance(v, str)]
        if raw_strs:
            if sum(1 for v in raw_strs if re.search(r"[$€£¥]", v)) >= 0.5 * len(raw_strs):
                unit = "currency"
            elif sum(1 for v in raw_strs if "%" in v) >= 0.5 * len(raw_strs):
                unit = "percent"
        if unit is None:
            for u, rx in _UNIT_HINT:
                if rx.search(lname) or any(rx.search(t) for t in toks):
                    unit = u
                    break
        person_hint = bool(sens) and not _SCORE_HINT.search(lname)
        id_hint = any(t in _ID_TOKENS for t in toks) or lname.endswith("id")

        if distinct == n and n >= 5 and all_int and (id_hint or (n >= 20 and sorted(nums) == list(range(int(lo), int(lo) + n)))):
            kind, conf, unit = "id_or_junk", 0.9 if id_hint else 0.8, None
            reason = "Whole numbers that are all different and count up, so it looks like a row or respondent number."
            return out()

        # 0/1 flag
        if set(nums) <= {0.0, 1.0} and distinct == 2 and not _SCORE_HINT.search(lname):
            kind, conf = "yes_no", 0.7
            reason = "Only 0 and 1, so it looks like a yes/no flag."
            return out()

        hint = bool(_SCORE_HINT.search(lname))
        in_scale = lo >= 0 and hi in (5, 7, 10) or (lo >= 0 and hi <= 10)
        if not person_hint and not id_hint and half_steps and in_scale and distinct <= 11 and (hint or distinct >= 3):
            kind = "score"
            rng = f"{lo:g} to {hi:g}"
            standard = (lo, hi) in {(0, 10), (1, 5), (1, 10), (1, 7), (0, 5)}
            conf = 0.92 if hint and standard else 0.85 if standard or hint else 0.7
            reason = f"Whole-number answers from {rng}, which reads like a rating scale."
            unit = None
            return out()
        if hint and not person_hint and lo >= 0 and hi <= 100 and all_int and distinct > 11:
            kind, conf = "score", 0.7
            reason = f"Numbers from {lo:g} to {hi:g} under a score-like name, so it reads like a 0-100 score."
            unit = None
            return out()

        kind = "numeric"
        conf = 0.9
        reason = f"Numbers from {lo:g} to {hi:g}" + (f" ({unit})" if unit else "") + ", so we show a spread or group them into bands."
        if distinct <= 6 and all_int and not person_hint:
            conf = 0.6
            reason = f"Only {distinct} different whole numbers; could be a small-group column (Segment) instead."
        if sens and not unit and "age" in (sens or ""):
            unit = "years"
        return out()

    # ---- text from here
    strs = [v for v in cnt if isinstance(v, str)]
    if strs and sum(1 for v in strs if _EMAIL.match(v)) >= 0.8 * len(strs):
        kind, conf = "id_or_junk", 0.95
        reason = "Looks like email addresses, which are personal and not useful for the story, so they are ignored."
        sens = None
        return out()
    if (any(t in _PERSON_TOKENS for t in toks) or "".join(toks) in _PERSON_TOKENS) and distinct >= 0.5 * n:
        kind, conf = "id_or_junk", 0.8
        reason = "The name says this holds personal details, and most values are different, so it is ignored."
        return out()

    id_hint = any(t in _ID_TOKENS for t in toks) or lname.endswith("id")
    uniq_ratio = distinct / n

    if distinct == n and n >= 3 and med_words <= 1 and (
        id_hint or (any(ch.isdigit() for v in strs for ch in v[:20]) and all(" " not in v for v in strs))
    ):
        kind, conf = "id_or_junk", 0.95 if id_hint else 0.8
        reason = "Every value is different and there are no words in it, so it looks like an ID or reference code."
        return out()

    if 2 <= distinct <= _segment_max_distinct(n) and distinct <= 0.5 * n:
        kind = "segment"
        conf = 0.9 if med_words <= 3 else 0.7
        reason = f"{distinct} different answers repeated across rows, so it can split the answers into groups."
        return out()
    if distinct == 1 and n >= 2:
        kind, conf = "id_or_junk", 0.85
        reason = "The same value in every row, so it tells us nothing."
        return out()

    if med_words >= 4:
        kind = "open_text"
        conf = 0.95 if uniq_ratio >= 0.6 else 0.8 if uniq_ratio >= 0.3 else 0.65
        reason = f"Most answers are sentences (about {med_words:g} words) and most are different, so we find themes in them."
        if uniq_ratio < 0.3:
            reason = f"Longer answers (about {med_words:g} words), but many repeat, so it may be a group column."
        return out()

    kind = "short_text"
    conf = 0.8 if uniq_ratio < 0.9 else 0.65
    reason = f"Short answers (usually {max(1, int(med_words))} to 3 words) with {distinct} different values, so we count and rank them."
    return out()


def detect_question(columns: list[dict[str, Any]], df: pd.DataFrame) -> dict[str, Any] | None:
    """Find the survey question. Returns {text, source, column} or None."""
    for c in columns:
        if c["is_question"]:
            col = df[c["name"]].dropna()
            text = str(col.mode().iloc[0]) if len(col) else ""
            return {"text": text, "source": "column", "column": c["name"]}
    texts = [c for c in columns if c["kind"] == "open_text"]
    for c in texts:
        h = c["name"].strip()
        if h.endswith("?") or len(h.split()) >= 5:
            return {"text": h, "source": "header", "column": c["name"]}
    return None


def profile_dataframe(df: pd.DataFrame) -> dict[str, Any]:
    total = len(df)
    cols = [profile_column(str(name), df[name].tolist(), i, total) for i, name in enumerate(df.columns)]
    # Dataset-wide "this sheet probably has no real header row" signal: requires a PATTERN across most
    # columns (>=60% of eligible ones), not one coincidentally data-like header (e.g. a column titled
    # "2024") - mirrors loader.py's own `_header_like` requiring row-level consensus, not single-cell
    # evidence. `id_or_junk`/sensitive columns are excluded: too ambiguous or too masked to judge.
    eligible = [c for c in cols if c["kind"] != "id_or_junk" and not c["sensitive"]]
    flagged = [c for c in eligible if c["looks_headerless"]]
    headerless_suspected = len(eligible) >= 2 and len(flagged) / len(eligible) >= 0.6
    return {
        "row_count": total,
        "column_count": len(cols),
        "columns": cols,
        "question": detect_question(cols, df),
        "headerless_suspected": headerless_suspected,
    }
