"""Planner and executor.

plan_cleaning(df, profile) proposes steps per column from its (confirmed or detected) kind. The plan is built by
running the steps in order on a working copy, so thresholds and merge tables come from the data as it looks at
that point in the pipeline, and steps that would change nothing are left out (a file with no text column never
gets a text step). apply_plan(df, plan) replays exactly the stored steps and returns (clean_df, CleaningReport).
"""
from __future__ import annotations

import os
from collections import Counter
from typing import Any, Callable

import pandas as pd

from . import steps_dataset as D
from . import steps_struct as S
from . import steps_text as T
from .common import CleaningError, Ctx, Deadline, Outcome, is_blank, safe_text
from .models import CleaningPlan, CleaningReport, Step, StepReport
from .suppression import build_suppression, min_group_size

# key -> (build(ctx, col, pov) -> Step | None, run(ctx, step) -> Outcome)
REGISTRY: dict[str, tuple[Callable, Callable]] = {
    "drop_empty_rows": (D.build_drop_empty_rows, D.run_drop_empty_rows),
    "drop_empty_columns": (D.build_drop_empty_columns, D.run_drop_empty_columns),
    "normalise_text": (T.build_normalise_text, T.run_normalise_text),
    "mask_pii": (T.build_mask_pii, T.run_mask_pii),
    "blank_non_answers": (T.build_blank_non_answers, T.run_blank_non_answers),
    "blank_keyboard_mash": (T.build_blank_keyboard_mash, T.run_blank_keyboard_mash),
    "flag_length_outliers": (T.build_flag_length_outliers, T.run_flag_length_outliers),
    "merge_variants": (T.build_merge_variants, T.run_merge_variants),
    "coerce_numbers": (S.build_coerce_numbers, S.run_coerce_numbers),
    "check_score_range": (S.build_check_score_range, S.run_check_score_range),
    "flag_numeric_outliers": (S.build_flag_numeric_outliers, S.run_flag_numeric_outliers),
    "parse_dates": (S.build_parse_dates, S.run_parse_dates),
    "standardise_labels": (S.build_standardise_labels, S.run_standardise_labels),
    "standardise_yes_no": (S.build_standardise_yes_no, S.run_standardise_yes_no),
    "merge_small_groups": (S.build_merge_small_groups, S.run_merge_small_groups),
    "collapse_duplicate_answers": (D.build_collapse_duplicate_answers, D.run_collapse_duplicate_answers),
    "report_duplicate_rows": (D.build_report_duplicate_rows, D.run_report_duplicate_rows),
    "exclude_columns": (D.build_exclude_columns, D.run_exclude_columns),
}

CANDIDATES: dict[str, list[str]] = {
    "open_text": ["normalise_text", "mask_pii", "blank_non_answers", "blank_keyboard_mash", "flag_length_outliers"],
    "short_text": ["normalise_text", "mask_pii", "blank_non_answers", "merge_variants"],
    "score": ["coerce_numbers", "check_score_range"],
    "numeric": ["coerce_numbers", "flag_numeric_outliers"],
    "date": ["parse_dates"],
    "segment": ["standardise_labels", "merge_small_groups"],
    "yes_no": ["standardise_yes_no"],
}
ALWAYS = {"mask_pii", "exclude_columns"}  # shown even when they find nothing, so the user sees they ran
EDITABLE_PARAMS = {"merge_small_groups": {"min_count"}, "check_score_range": {"scale"}, "parse_dates": {"day_first"}}
MAX_REMOVED_LISTED = 1000


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


def default_settings(extra: dict | None = None) -> dict[str, Any]:
    s = {
        "min_group_size": min_group_size(),
        "max_rows": _int_env("CLEAN_MAX_ROWS", 200_000),
        "max_columns": _int_env("CLEAN_MAX_COLUMNS", 300),
        "timeout_seconds": float(_int_env("CLEAN_TIMEOUT_SECONDS", 30)),
    }
    s.update(extra or {})
    return s


def columns_meta(df: pd.DataFrame, profile: dict | None) -> dict[str, dict[str, Any]]:
    profile = profile or {}
    detected = {c["name"]: c for c in profile.get("columns", [])}
    confirmed = (profile.get("confirmed") or {}).get("columns", {})
    meta = {}
    for name in df.columns:
        d = detected.get(name, {})
        kind = (confirmed.get(name) or {}).get("kind") or d.get("kind") or "id_or_junk"
        meta[name] = {"kind": kind, "sensitive": bool(d.get("sensitive"))}
    return meta


def _prepare(df: pd.DataFrame, settings: dict) -> pd.DataFrame:
    if df.columns.duplicated().any():
        raise CleaningError("Two columns have the same name, so the file cannot be cleaned.")
    if len(df) > settings["max_rows"]:
        raise CleaningError(f"Cleaning is limited to {settings['max_rows']:,} rows; this file has {len(df):,}.")
    if df.shape[1] > settings["max_columns"]:
        raise CleaningError(f"Cleaning is limited to {settings['max_columns']} columns; this file has {df.shape[1]}.")
    out = df.copy()
    out.columns = [str(c) for c in out.columns]
    out = out.astype(object).reset_index(drop=True)
    return out.where(out.notna(), None)


def _execute(ctx: Ctx, step: Step) -> StepReport:
    rep = StepReport(id=step.id, key=step.key, column=step.column, title=step.title, description=step.description,
                     enabled=step.enabled, status="skipped")
    if not step.enabled:
        return rep
    ctx.deadline.check()
    try:
        out: Outcome = REGISTRY[step.key][1](ctx, step)
    except CleaningError:
        raise
    except Exception:  # never leak internals; the step is reported as failed and the data left as it was
        rep.status = "failed"
        rep.notes.append("This step could not run on this data, so it was skipped.")
        return rep
    rep.rows_affected, rep.cells_affected = out.rows, out.cells
    rep.examples, rep.notes = out.examples[:3], out.notes
    rep.details = {k: v for k, v in out.details.items() if not k.startswith("_")}
    changed = out.rows or out.cells or out.details.get("always_report")
    rep.status = "applied" if changed else "no_change"
    return rep


def _apply_override(step: Step, ov: dict) -> None:
    if "enabled" in ov:
        step.enabled = bool(ov["enabled"])
    merges = ov.get("merges") or {}
    if merges and "merges" in step.params:
        for e in step.params["merges"]:
            o = merges.get(e["from"])
            if not o:
                continue
            if o.get("to"):
                e["to"] = str(o["to"])
            if "enabled" in o:
                e["enabled"] = bool(o["enabled"])


def _finish(ctx: Ctx, reports: list[StepReport], rows_in: int, cols_in: int, want_df: bool):
    df = ctx.df
    m = int(ctx.settings["min_group_size"])
    clean = None
    flagged_rows = sum(1 for i in ctx.flags if i in df.index)
    if want_df:
        clean = df.copy()
        clean.insert(0, "_verbatim_row", [int(i) + 1 for i in clean.index])
        if flagged_rows:
            clean["_verbatim_flags"] = [
                "; ".join(list(dict.fromkeys(ctx.flags.get(i, [])))[:6]) or None for i in df.index]
        if ctx.dup_counts:
            clean["_verbatim_dup_count"] = [ctx.dup_counts.get(i) for i in df.index]
        clean = clean.reset_index(drop=True)
    removed = sorted(ctx.removed.items())
    by_step = Counter(sid for _, (sid, _) in removed)
    report = CleaningReport(
        rows_in=rows_in, rows_out=len(df), columns_in=cols_in, columns_out=df.shape[1], steps=reports,
        removed_rows_total=len(removed), removed_by_step=dict(by_step),
        removed_rows=[{"row": i + 1, "step": sid, "reason": reason} for i, (sid, reason) in removed[:MAX_REMOVED_LISTED]],
        removed_rows_truncated=len(removed) > MAX_REMOVED_LISTED, removed_columns=ctx.removed_columns,
        excluded_columns=[safe_text(c, 120) for c in ctx.excluded], flagged_rows=flagged_rows, pii=dict(ctx.pii),
        suppression=build_suppression(df, ctx.columns, m), warnings=ctx.warnings,
        accounted_for=(rows_in - len(df) == len(removed)),
    )
    return clean, report


def _plan(df: pd.DataFrame, profile: dict | None, overrides: dict | None, settings: dict | None):
    settings = default_settings(settings)
    overrides = overrides or {}
    work = _prepare(df, settings)
    rows_in, cols_in = len(work), work.shape[1]
    columns = columns_meta(work, profile)
    ctx = Ctx(work, columns, settings, Deadline(settings["timeout_seconds"]))
    steps: list[Step] = []
    reports: list[StepReport] = []

    def add(key: str, col: str | None) -> None:
        sid = f"{key}:{col}" if col else key
        ov = overrides.get(sid) or {}
        allowed = EDITABLE_PARAMS.get(key, set())
        pov = {k: v for k, v in (ov.get("params") or {}).items() if k in allowed}
        step = REGISTRY[key][0](ctx, col, pov)
        if step is None:
            return
        _apply_override(step, ov)
        rep = _execute(ctx, step)
        if rep.status == "no_change" and key not in ALWAYS:
            return
        steps.append(step)
        reports.append(rep)

    add("drop_empty_rows", None)
    add("drop_empty_columns", None)
    for col in list(ctx.df.columns):
        if col not in ctx.df.columns:
            continue
        for key in CANDIDATES.get(columns[col]["kind"], []):
            add(key, col)
    add("collapse_duplicate_answers", None)
    add("report_duplicate_rows", None)
    add("exclude_columns", None)

    plan = CleaningPlan(steps=steps, settings=settings, columns=columns, overrides=overrides)
    return plan, ctx, reports, rows_in, cols_in


def plan_with_preview(df: pd.DataFrame, profile: dict | None, overrides: dict | None = None,
                      settings: dict | None = None) -> tuple[CleaningPlan, CleaningReport]:
    plan, ctx, reports, rows_in, cols_in = _plan(df, profile, overrides, settings)
    _, report = _finish(ctx, reports, rows_in, cols_in, want_df=False)
    return plan, report


def plan_cleaning(df: pd.DataFrame, profile: dict | None, overrides: dict | None = None,
                  settings: dict | None = None) -> CleaningPlan:
    return plan_with_preview(df, profile, overrides, settings)[0]


def apply_plan(df: pd.DataFrame, plan: CleaningPlan) -> tuple[pd.DataFrame, CleaningReport]:
    settings = default_settings(plan.settings)
    work = _prepare(df, settings)
    ctx = Ctx(work, plan.columns, settings, Deadline(settings["timeout_seconds"]))
    reports = []
    for step in plan.steps:
        if step.key not in REGISTRY:
            raise CleaningError("The stored plan has a step this version does not know. Build the plan again.")
        reports.append(_execute(ctx, step))
    clean, report = _finish(ctx, reports, len(work), work.shape[1], want_df=True)
    return clean, report
