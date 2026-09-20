"""Understand an uploaded spreadsheet: load it, then guess what each column is."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .columns import KIND_LABELS, KINDS, profile_column, profile_dataframe
from .loader import LoadedTable, LoadError, load_table


def profile_file(path: str | Path) -> tuple[dict[str, Any], LoadedTable]:
    """Load a file and profile it. Returns (profile dict, loaded table)."""
    loaded = load_table(path)
    profile = profile_dataframe(loaded.df)
    profile["notes"] = list(loaded.notes)
    profile["source"] = dict(loaded.meta)
    return profile, loaded


__all__ = [
    "KINDS", "KIND_LABELS", "LoadError", "LoadedTable", "load_table",
    "profile_column", "profile_dataframe", "profile_file",
]
