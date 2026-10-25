"""Which Claude model each step uses (user's decision, 2026-10-25).

Naming themes (Find themes, Look inside Other, splitting a theme) decides what the whole report is about,
so it keeps the stronger model: `text_pipeline.labeling.DEFAULT_MODEL`, overridable with
`VERBATIM_CLAUDE_MODEL`. The small, rule-bound steps use the cheapest model: column hints at upload,
report headlines (written from numbers only) and theme grouping. Override them with
`VERBATIM_CLAUDE_LIGHT_MODEL`.
"""
from __future__ import annotations

import os

LIGHT_MODEL = "claude-haiku-5-5"
LIGHT_MODEL_SETTING = "VERBATIM_CLAUDE_LIGHT_MODEL"


def light_model() -> str:
    """The model for column hints, report headlines and theme grouping."""
    return os.environ.get(LIGHT_MODEL_SETTING) or LIGHT_MODEL
