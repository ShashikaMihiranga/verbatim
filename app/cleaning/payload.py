"""The only door text should leave the cleaned data through on its way to a model.

Refuses sensitive columns and non-text columns, and always masks personal details again (defence in depth,
even if the user switched the masking step off).
"""
from __future__ import annotations

import pandas as pd

from .common import CleaningError
from .models import CleaningPlan
from .redact import redact_text


def model_safe_samples(clean_df: pd.DataFrame, plan: CleaningPlan, column: str, limit: int = 30) -> list[str]:
    meta = plan.columns.get(column)
    if meta is None or column not in clean_df.columns:
        raise CleaningError("Unknown column.")
    if meta.get("sensitive"):
        raise CleaningError("Sensitive columns are never sent to a model.")
    if meta.get("kind") not in ("open_text", "short_text"):
        raise CleaningError("Only text columns can be sampled.")
    values = clean_df[column].dropna()
    values = values[values.map(lambda v: isinstance(v, str))]
    return [redact_text(v)[0] for v in values.head(max(0, min(limit, 200)))]
