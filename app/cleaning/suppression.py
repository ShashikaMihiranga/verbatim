"""Small-group suppression metadata for sensitive columns (age, gender, income and similar).

The counts of groups under the minimum size are withheld (None) and the group is marked hidden. Raw rows of
sensitive columns never appear in the report; only labels of categories and, for visible groups, counts.
"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd

from .common import safe_text

DEFAULT_MIN_GROUP_SIZE = 30
CATEGORICAL = {"segment", "yes_no", "short_text"}


def min_group_size() -> int:
    try:
        return max(2, int(os.environ.get("MIN_GROUP_SIZE", DEFAULT_MIN_GROUP_SIZE)))
    except ValueError:
        return DEFAULT_MIN_GROUP_SIZE


def build_suppression(df: pd.DataFrame, columns: dict[str, dict[str, Any]], m: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for col, meta in columns.items():
        if not meta.get("sensitive") or col not in df.columns or meta.get("kind") == "id_or_junk":
            continue
        kind = meta.get("kind")
        info: dict[str, Any] = {
            "min_group_size": m, "kind": kind, "raw_rows_in_report": False,
            "column_hidden": int(df[col].notna().sum()) < m,
        }
        if kind in CATEGORICAL:
            vc = df[col].value_counts()
            groups = [{"label": safe_text(v, 80), "count": int(c) if c >= m else None, "hidden": bool(c < m)}
                      for v, c in vc.items()]
            groups.sort(key=lambda g: (g["hidden"], -(g["count"] or 0)))
            info["groups"] = groups[:1000]
            info["hidden_groups"] = sum(g["hidden"] for g in groups)
        else:
            info["groups"] = None
            info["note"] = (f"Numbers and dates in this column may only be shown as summaries or bands built from "
                            f"groups of at least {m}.")
        out[col] = info
    return out
