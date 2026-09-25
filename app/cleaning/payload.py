"""The only door text should leave the cleaned data through on its way to a model.

Refuses sensitive columns and non-text columns, and always masks personal details again (defence in depth,
even if the user switched the masking step off).
"""
from __future__ import annotations

import pandas as pd

from .common import CleaningError
from .models import CleaningPlan
from .redact import bare_digits_for_kind, redact_text


def _checked_text_column(clean_df: pd.DataFrame, plan: CleaningPlan, column: str) -> dict:
    """Shared refusal rules for every function in this module: unknown, sensitive and non-text
    columns never get past here. Returns the column's plan metadata (kind, sensitive, ...)."""
    meta = plan.columns.get(column)
    if meta is None or column not in clean_df.columns:
        raise CleaningError("Unknown column.")
    if meta.get("sensitive"):
        raise CleaningError("Sensitive columns are never sent to a model.")
    if meta.get("kind") not in ("open_text", "short_text"):
        raise CleaningError("Only text columns can be sampled.")
    return meta


def _mask(value: object, kind: str) -> str | None:
    """Redact one cell for a model. None (not a string) for anything that is not real text, so callers
    can tell a blank/NaN row apart from a masked-but-present answer."""
    if not isinstance(value, str):
        return None
    bare = bare_digits_for_kind(kind)
    return redact_text(value, bare_digits=bare)[0]


def model_safe_samples(clean_df: pd.DataFrame, plan: CleaningPlan, column: str, limit: int = 30) -> list[str]:
    meta = _checked_text_column(clean_df, plan, column)
    kind = meta.get("kind", "")
    values = clean_df[column].dropna()
    values = values[values.map(lambda v: isinstance(v, str))]
    # Always the full set of masks: emails, links, phones (bare digit runs too), IDs, cue-based names, addresses.
    return [_mask(v, kind) for v in values.head(max(0, min(limit, 200)))]


def model_safe_column(clean_df: pd.DataFrame, plan: CleaningPlan, column: str) -> list[str | None]:
    """Every row of `column`, masked, in original row order — unlike `model_safe_samples`, which caps at
    `limit` rows and is meant for Claude-facing calls. This is for embeddings, which need every answer.

    A row that is missing/NaN or not a string comes back as None (never an empty string), so a caller can
    zip this list against the dataframe's row positions and know exactly which rows had no answer, instead
    of the list silently shrinking and answers appearing to shift to the wrong row."""
    meta = _checked_text_column(clean_df, plan, column)
    kind = meta.get("kind", "")
    return [_mask(v, kind) for v in clean_df[column]]
