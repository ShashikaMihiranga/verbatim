"""Dynamic-report API (stream 8): wires `app/findings.py` (built, tested and merged already) to storage
and an owner-only HTTP layer, matching `app/api_themes.py`'s conventions exactly rather than inventing a
second style for the same kind of route.

POST /api/datasets/{id}/report/build   body {"column": str} -> validates ownership/themes-exist/Claude key
                                        synchronously, then starts `app.findings.build_findings` (the real
                                        work: candidate scoring, one batched Claude call for headlines,
                                        building `ReportData`, writing `Finding`/`Report` rows) in a
                                        background thread and returns 202 {job_id, status: "running"}
                                        immediately - replacing any job/report already stored for that
                                        dataset + column. Poll `GET /api/datasets/{id}/jobs/{job_id}`, then
                                        call the GET route below once it is "done".
GET  /api/datasets/{id}/report?column=...   returns the most recently stored report for this dataset+column,
                                        with every block's chart re-rendered fresh from the current `Theme`/
                                        `Finding` rows (see app/findings.py's `build_findings` docstring,
                                        "Render-vs-store-HTML" - this route is the caller it describes).

Everything is owner-only (same `current_user`/`_own_dataset` as every other data route). Only
`REPORT_CONCURRENCY` report-building jobs run at once - see the constant below for why this stream's
default differs from `app.api_themes.THEMES_CONCURRENCY` and `app.api_cleaning.CLEAN_CONCURRENCY`, and
docs/DECISIONS.md for the reasoning written out in full.

Reuse, not duplication (per the brief this stream was built from):
  - `app.api_themes._load_clean_df` loads the cleaned dataframe exactly the way `api_themes.py`/
    `api_cleaning.py` already do - a second copy of that loader was not written.
  - `app.api_themes.get_claude_client` is reused AS-IS for this router's own `Depends`: it already turns
    `LabelingClaudeNotConfigured` (re-exported from `app.findings` as `FindingsClaudeNotConfigured` - see
    that module's docstring) into a clean 503 before this route's body ever runs, so no second "no key
    configured" translation was written here either.
  - "See answers" is `app.api_themes.theme_answers` (`GET /api/datasets/{id}/themes/{theme_id}/answers`),
    unchanged. This module returns each finding's `theme_id` so the frontend can call that existing route
    directly; verbatim-fetching logic is not duplicated here.
"""
from __future__ import annotations

import dataclasses
import os
import threading
from datetime import date
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db as _db
from .api_themes import _load_clean_df, get_claude_client
from .api_upload import _own_dataset, current_user
from .charts import TITLES, render_parts
from .export import ExportBlock, build_report_pdf, build_report_pptx, render_report_png
from .cleaning.suppression import min_group_size as _suppression_min_group_size
from .db import get_db
from .findings import (
    FindingsClaudeNotConfigured,
    NoThemesForColumn,
    build_findings,
    build_report_data,
    other_breakdown,
    theme_nodes,
)
from .findings_structured import (
    StructuredContext,
    build_structured_context,
    pick_structured_columns,
    resolve_filter_rows,
)
from .jobs import create_job, start_job
from .models import Column, Dataset, Finding, Report, Theme, User
from .report_medium import comparison_groups, complete_numeric_grid, finding_views, numeric_explorations, theme_views
from .text_pipeline import ClaudeClient
from .text_pipeline.labeling import OTHER_LABEL

router = APIRouter(prefix="/api")

# Report building's own network cost is ONE batched Claude call for headlines (see
# `app.findings.write_headline`) - everything else (loading stored `Theme` rows, scoring candidates,
# rendering charts) is in-process. That is lighter than `app.api_themes`'s build-themes route (real
# embedding calls plus a Claude labelling call plus clustering), whose default (`THEMES_CONCURRENCY=1`) is
# deliberately conservative for exactly that heavier cost - but still real network, unlike
# `app.api_cleaning`'s pure-pandas jobs (`CLEAN_CONCURRENCY=2`). Default 2, matching cleaning's number
# rather than inventing a third convention: this route's heaviest step is a single small batched call, not
# the multi-step pipeline themes-building runs. See docs/DECISIONS.md.
_SLOTS = threading.BoundedSemaphore(max(1, int(os.environ.get("REPORT_CONCURRENCY", "2") or 2)))


class BuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = Field(max_length=255)


# ---------------------------------------------------------------- helpers

def _cleaning_report_for(ds: Dataset) -> dict:
    return dict(((ds.profile or {}).get("cleaning") or {}).get("report") or {})


def _answer_lengths_for(clean_df, column: str, themes: list[Theme]) -> list[int]:
    """Real per-answer word counts for exactly the rows these themes were built from (`Theme.answer_refs`) -
    the cheap-once-you-already-have-the-dataframe histogram input `build_report_data`'s docstring asks a
    caller like this one to supply (see app/findings.py: "a caller that already has the cleaned text loaded
    ... can pass the word counts through here for a real histogram")."""
    rows = sorted({r for t in themes for r in (t.answer_refs or [])})
    lengths: list[int] = []
    for r in rows:
        try:
            v = clean_df.at[r, column]
        except KeyError:
            continue
        if isinstance(v, str) and v.strip():
            lengths.append(len(v.split()))
    return lengths


def _answer_texts_for(clean_df, column: str, themes: list[Theme]) -> list[str]:
    """Real cleaned answer strings for the `top_phrases` block (chart-block stream, 2026-10-24) - same
    "a caller that already has the dataframe loaded can pass the real thing through" shape as
    `_answer_lengths_for` above, feeding `app.text_pipeline.phrases.build_phrase_data` via
    `build_report_data`'s `answer_texts` param. Not the masked/model-safe text: this never reaches a
    model (phrase extraction is pure code, see that module's own docstring), and the report's own
    "See answers" drill-down already shows raw verbatim text to the same viewer, so there is no extra
    trust boundary to cross here that the rest of this app doesn't already cross."""
    rows = sorted({r for t in themes for r in (t.answer_refs or [])})
    texts: list[str] = []
    for r in rows:
        try:
            v = clean_df.at[r, column]
        except KeyError:
            continue
        if isinstance(v, str) and v.strip():
            texts.append(v)
    return texts


def _quote_theme_texts_for(clean_df, column: str, themes: list[Theme]) -> list[tuple[str, list[str]]]:
    """Real answer texts GROUPED BY theme, largest theme first, for the `quotes` block (chart-block
    stream, 2026-10-24) - unlike `_answer_texts_for`'s flattened list (phrase extraction aggregates across
    every answer regardless of theme), a quote needs its own theme attribution, and the merged "Other"
    bucket is deliberately excluded - a quote attributed to "Other" would misleadingly imply it represents
    one real idea when that bucket is a mix of unrelated small themes (same reasoning `app/charts.py`'s
    `f_sentsun` highlight fallback already documents for a different block)."""
    real_themes = sorted((t for t in themes if t.label != OTHER_LABEL), key=lambda t: t.size, reverse=True)
    out: list[tuple[str, list[str]]] = []
    for t in real_themes:
        texts: list[str] = []
        for r in sorted(t.answer_refs or []):
            try:
                v = clean_df.at[r, column]
            except KeyError:
                continue
            if isinstance(v, str) and v.strip():
                texts.append(v)
        if texts:
            out.append((t.label, texts))
    return out


def _answer_positions_for(db: Session, dataset_id: int, column: str) -> dict[int, tuple[float, float]]:
    """Real sampled per-answer positions for the `answer_map` block (chart-block stream, 2026-10-24,
    batch 4) - `Column.answer_positions` (set once at theme-build time,
    `app.api_themes._sample_answer_positions`), JSON-decoded back from `{"row": [x, y]}` string keys to a
    real `dict[int, tuple[float, float]]`. `{}` when no Column row exists yet, or no positions were ever
    stored for it (every column built before this stream, or a dataset too small to sample)."""
    col_row = db.scalar(select(Column).where(Column.dataset_id == dataset_id, Column.name == column))
    if col_row is None or not col_row.answer_positions:
        return {}
    return {int(r): (xy[0], xy[1]) for r, xy in col_row.answer_positions.items()}


def _structured_context_for(
    db: Session, ds: Dataset, clean_df, plan, themes: list[Theme], filter_rows: set[int] | None = None,
) -> StructuredContext:
    """B3 wiring: resolves this dataset's confirmed score/segment/date column candidates
    (`pick_structured_columns`, tried in order until one produces usable data - see
    `build_structured_context`'s own docstring) against the cleaned dataframe and the cleaning plan
    actually applied (`plan` - previously discarded as `_plan` by both call sites below, see
    docs/DECISIONS.md), producing the `StructuredContext` both
    `app.findings.candidate_findings` (the 3 new finding kinds) and `app.findings.build_report_data` (the
    `byScore`/`heatmap`/`trend` chart data) need. Never raises: a dataset with no usable score/segment/date
    column simply gets a `StructuredContext` with every field at its `None`/`""` default (see that
    dataclass's own docstring).

    `filter_rows` (Filters feature): threaded into both `theme_nodes` (so node counts/answer_refs reflect
    the filter) and `build_structured_context` (so the cross-tab row universe does too). `ThemeNode.share`
    (read by `build_segment_data`'s "deviation from overall share" highlight) needs the FILTERED total to
    be correct, which is itself only known after filtering - same two-pass shape
    `app.findings.build_report_data` uses for the identical reason."""
    if filter_rows is None:
        total = sum(t.size for t in themes)
        nodes = theme_nodes(themes, total)
    else:
        nodes = theme_nodes(themes, total_answered=1, filter_rows=filter_rows)
        total = sum(n.count for n in nodes)
        nodes = theme_nodes(themes, total, filter_rows=filter_rows)
    cols = pick_structured_columns(ds.id, db)
    return build_structured_context(
        clean_df, plan, themes, nodes, cols, _suppression_min_group_size(), filter_rows=filter_rows,
    )


def _column_role(db: Session, dataset_id: int, column_name: str, primary_kind: str) -> str:
    """The "Columns used" chip's honest role label (docs/DECISIONS.md's 2026-09-28 "honest 'Columns
    used'" entry): `structured.score`/`.segment` can now be won by a `numeric`/`yes_no`-kind column
    falling back into that same slot (docs/TODO.md, fixed 2026-10-22 - see
    `build_structured_context`'s own docstring for why there's no separate slot), so the chip must say
    what kind the WINNING column actually is, not always "score"/"segment" regardless. Falls back to
    `primary_kind` itself if the `Column` row can't be found (should not happen in practice - defensive
    only, never a user-visible error)."""
    col = db.scalar(select(Column).where(Column.dataset_id == dataset_id, Column.name == column_name))
    return col.kind if col is not None else primary_kind


def _latest_report_for_column(db: Session, dataset_id: int, column: str) -> Report | None:
    # `build_findings` deletes any prior report for this dataset+column before writing a new one (see its
    # docstring), so at most one row should ever match - `order_by(id.desc())` is defensive, not load-bearing.
    rows = db.scalars(select(Report).where(Report.dataset_id == dataset_id).order_by(Report.id.desc())).all()
    for r in rows:
        if isinstance(r.content, dict) and r.content.get("column") == column:
            return r
    return None


def _filter_options_for(structured: StructuredContext) -> dict[str, Any]:
    """Filter dropdown option values (Filters feature, SPEC.md section 5), built from an UNFILTERED
    `StructuredContext`'s already-suppressed `segment.groups`/`score.bands` labels (not a fresh raw-value
    scan) - every offered option is guaranteed to already be a group/band genuinely shown in that chart,
    never one that would immediately collapse to "not enough data" if picked."""
    segment_opts = None
    if structured.segment is not None:
        segment_opts = {
            "column": structured.segment_column_name,
            "groups": [g.label for g in structured.segment.groups],
        }
    score_opts = None
    if structured.score is not None:
        score_opts = {
            "column": structured.score_column_name,
            "bands": [b.label for b in structured.score.bands],
        }
    date_opts = None
    if structured.trend is not None and structured.date_raw_by_row:
        values = structured.date_raw_by_row.values()
        date_opts = {
            "column": structured.trend_column_name,
            "min": min(values).isoformat(),
            "max": max(values).isoformat(),
        }
    return {"segment": segment_opts, "score_band": score_opts, "date_range": date_opts}


def _render_report(
    db: Session, ds: Dataset, column: str, report: Report, *,
    segment: str | None = None, score_band: str | None = None,
    date_from: date | None = None, date_to: date | None = None,
) -> dict[str, Any]:
    """Builds the JSON body for both routes below: one `build_report_data` call, reused for every block's
    `render_parts()` (per app/findings.py's own instruction - never rebuilt per block).

    `segment`/`score_band`/`date_from`/`date_to` (Filters feature, SPEC.md section 5) are optional and
    AND'd together. The UNFILTERED `StructuredContext` is always built first - it supplies `filter_options`
    (so dropdown choices never shrink as a filter narrows the view) and the raw per-row dicts
    `resolve_filter_rows` needs. Only when at least one filter arg is given is a second, filtered
    `StructuredContext` built and used for the actual chart data - a dataset with no filter params active
    behaves byte-for-byte like it did before this feature existed."""
    content = report.content or {}
    themes = list(db.scalars(
        select(Theme).where(Theme.dataset_id == ds.id, Theme.column_name == column).order_by(Theme.id)
    ).all())
    clean_df, plan = _load_clean_df(ds, db)
    structured = _structured_context_for(db, ds, clean_df, plan, themes)
    source_columns = {'score_correlation': structured.score_column_name,
                      'segment_skew': structured.segment_column_name, 'trend_shift': structured.trend_column_name}
    filter_options = _filter_options_for(structured)
    filter_rows = resolve_filter_rows(structured, segment, score_band, date_from, date_to)
    if filter_rows is not None:
        structured = _structured_context_for(db, ds, clean_df, plan, themes, filter_rows=filter_rows)
    current_columns = {'score_correlation': structured.score_column_name,
                       'segment_skew': structured.segment_column_name, 'trend_shift': structured.trend_column_name}
    answer_lengths = _answer_lengths_for(clean_df, column, themes)
    answer_texts = _answer_texts_for(clean_df, column, themes)
    quote_theme_texts = _quote_theme_texts_for(clean_df, column, themes)
    answer_positions = _answer_positions_for(db, ds.id, column)
    question = content.get("question") or column
    report_data = build_report_data(
        ds, themes, _cleaning_report_for(ds), question, answer_lengths=answer_lengths,
        answer_texts=answer_texts, quote_theme_texts=quote_theme_texts, answer_positions=answer_positions,
        structured=structured, filter_rows=filter_rows,
    )
    breakdown, all_themes = other_breakdown(themes, report_data.answered, filter_rows=filter_rows)
    comparison_data = comparison_groups(report_data, clean_df)
    report_data = complete_numeric_grid(report_data, clean_df, pick_structured_columns(ds.id, db))
    explorations = numeric_explorations(report_data)

    # Chart-type switcher (docs/TODO.md, 2026-10-21 Stage 2): alternate views of the SAME theme data the
    # treemap above already shows, rendered from the ONE already-built `report_data` (never rebuilt per
    # tab, same "one report_data, reused for every block" rule the blocks loop below already follows).
    # "arc" (theme co-occurrence) is deliberately NOT included: it needs an answer to belong to MULTIPLE
    # themes at once to mean anything, but this pipeline's clustering is a hard partition - every answer
    # belongs to exactly one theme by construction, so `data.cooccurrence` has no real signal to compute
    # it from (not a missing wiring step, a genuinely new kind of analysis this pipeline does not do
    # today). Shipping an always-empty arc diagram would be exactly the kind of misleading chart this
    # project's own design discipline avoids elsewhere (see e.g. the sub-theme coverage gate) - deferred,
    # not faked. "sankey" is also excluded here: that existing chart needs a real score column
    # (`data.score.bands`) and is unrelated to the mockup's own "Known themes" tab (a bespoke, separate
    # Stage 3 build, not a reuse of this renderer - see docs/DECISIONS.md).
    # "diverge"/"sunburst" added (docs/DECISIONS.md, 2026-10-24 chart-block stream, "reuse group"): both
    # renderers already existed in app/charts.py but were gallery-only (never fed real report_data) -
    # app/report_blocks.py's new "tone_split"/"theme_hierarchy" blocks name them as their chart_id. This
    # is the SAME "just expose it as a variant tab" treatment icicle/sentsun/rank already got - no new
    # finding-selection logic, that stage is explicitly deferred (see the plan's reordering note).
    theme_chart_variants = theme_views(report_data)

    blocks_content = content.get("blocks") or []
    finding_ids = [b["finding_id"] for b in blocks_content if b.get("finding_id") is not None]
    findings_by_id: dict[int, Finding] = {}
    if finding_ids:
        findings_by_id = {
            f.id: f for f in db.scalars(select(Finding).where(Finding.id.in_(finding_ids))).all()
        }

    blocks_out: list[dict[str, Any]] = []
    for b in blocks_content:
        chart_id = b["chart_id"]
        fid = b.get("finding_id")
        finding_row = findings_by_id.get(fid) if b["kind"] == "finding" and fid is not None else None

        # Finding-aware sentsun/diverge/sunburst (fixes two findings sharing one chart_id rendering the
        # byte-identical, globally-same chart - see docs/DECISIONS.md): `report_data` is built ONCE and
        # reused for every block (comment above, "never rebuilt per block") - that rule is about not
        # re-running the expensive build_report_data pass, not about every block seeing identical data.
        # `dataclasses.replace` makes a cheap, un-shared view with just `selected_theme` swapped to THIS
        # finding's own theme for this one render call; `report_data` itself (and every other block's
        # render) is untouched. "diverge"/"sunburst" (chart-block stream, 2026-10-24, Stage 3) joined this
        # list once `app.findings.pick_chart` started actually choosing them for real findings (tone_
        # contrast's sentsun-vs-diverge swap, long_tail's treemap-vs-sunburst swap) - both renderers read
        # `data.selected_theme` the exact same way sentsun does (see app/charts.py's f_diverge/f_sunburst),
        # so leaving them out here would reintroduce the identical "wrong theme highlighted" bug sentsun's
        # own fix (confirmed live, see below) already closed, just for two new chart ids instead of one.
        block_data = report_data
        if chart_id in ("sentsun", "diverge", "sunburst") and finding_row is not None and finding_row.theme_id is not None:
            node = next((t for t in report_data.themes if t.theme_id == finding_row.theme_id), None)
            if node is not None:
                block_data = dataclasses.replace(report_data, selected_theme=node.name)
            else:
                # The finding's own theme is real but too small to get its own node - `theme_nodes` folds
                # any real theme past the top 7 into the merged "Other" node (app/findings.py's own
                # docstring on that). Falling through to the default `report_data.selected_theme` here
                # would silently outline some UNRELATED theme (confirmed live: a "parking and access"
                # finding's chart outlined "Space, layout & crowding" instead) - exactly the kind of
                # misleading chart this fix exists to stop. "Other" is where this finding's data actually
                # sits in THIS chart, so that is what gets outlined instead.
                block_data = dataclasses.replace(report_data, selected_theme="Other")

        # `render_parts` returns the raw body fragment (no `<!doctype html>`/own background/own font load) -
        # see app/charts.py's own docstring split between `render_parts` and `render`. The frontend embeds
        # this fragment straight into the report page's DOM (never an iframe), so it inherits the page's own
        # already-loaded `--bg --surface --ink ...` tokens instead of carrying a second copy of them - see
        # docs/DECISIONS.md ("report page: fragments, not iframed documents").
        chart_html, chart_width, chart_height = render_parts(chart_id, block_data)
        block: dict[str, Any] = {
            "kind": b["kind"],
            "chart_id": chart_id,
            "chart_title": TITLES.get(chart_id, chart_id),
            "chart_html": chart_html,
            "chart_width": chart_width,
            "chart_height": chart_height,
            "priority": b["priority"],
            "finding_id": b.get("finding_id"),
            "finding": None,
        }
        if finding_row is not None:
            f = finding_row
            block["finding"] = {
                "id": f.id, "theme_id": f.theme_id, "sentence": f.sentence, "confidence": f.confidence,
            }
            finding_data = f.data if isinstance(f.data, dict) else {}
            kind = finding_data.get("kind", "")
            block["chart_variants"] = finding_views(
                block_data, finding_data.get("kind", ""), finding_data.get("theme", ""), comparison_data,
            ) if source_columns.get(kind) == current_columns.get(kind) else {}
            if chart_id == "sunburst" and "icicle" in theme_chart_variants:
                block["compact_chart_id"] = "icicle"
                block["chart_variants"]["icicle"] = theme_chart_variants["icicle"]
        blocks_out.append(block)

    # SPEC.md section 2's "aggregated numbers only" rule applies to this header line too: it is plain
    # arithmetic on numbers `build_report_data` already computed, never a second Claude call.
    real_theme_count = sum(1 for t in themes if t.label != OTHER_LABEL)
    overall = report_data.overall_sentiment
    tone_word = "positive" if overall >= 0.05 else "negative" if overall <= -0.05 else "mixed"
    plural = "" if real_theme_count == 1 else "s"
    summary = f"{real_theme_count} theme{plural} found, overall tone {tone_word} ({overall:+.2f})."

    # "Columns used": the report's own open-text column first, then only the structured columns that
    # actually survived suppression and produced real chart data (never one merely confirmed but unused) -
    # matching docs/DECISIONS.md's 2026-09-28 "honest 'Columns used' chip row" entry's own stated philosophy.
    columns_used: list[dict[str, str]] = [{"name": column, "role": "open-ended text"}]
    if structured.score is not None:
        columns_used.append({"name": structured.score_column_name, "role": _column_role(db, ds.id, structured.score_column_name, "score")})
    if structured.segment is not None:
        columns_used.append({"name": structured.segment_column_name, "role": _column_role(db, ds.id, structured.segment_column_name, "segment")})
    if structured.trend is not None:
        columns_used.append({"name": structured.trend_column_name, "role": "date"})
    if explorations:
        used = {c["name"] for c in columns_used}
        for name in (report_data.binned_grid.row_name, report_data.binned_grid.col_name):
            if name not in used:
                columns_used.append({"name": name, "role": _column_role(db, ds.id, name, "numeric")})
                used.add(name)

    return {
        "dataset_id": ds.id,
        "column": column,
        "question": question,
        "summary": summary,
        "also_checked_nothing_notable": bool(content.get("also_checked_nothing_notable")),
        "blocks": blocks_out,
        "columns_used": columns_used,
        "filter_options": filter_options,
        "filters_applied": {
            "segment": segment, "score_band": score_band,
            "date_from": date_from.isoformat() if date_from else None,
            "date_to": date_to.isoformat() if date_to else None,
        },
        # "Other" exploration section (docs/TODO.md, 2026-10-21 Phase 1): `other_breakdown` is None when
        # there is nothing genuinely folded into "Other" to explain - the frontend's callout/breakdown
        # tiles render nothing in that case. `all_themes` is the uncapped list for the "see all themes"
        # ranked list, always present (possibly empty), independent of whether there is anything in Other.
        "other_breakdown": None if breakdown is None else {
            "noise_count": breakdown.noise_count, "noise_share": breakdown.noise_share,
            "hidden_real_count": breakdown.hidden_real_count, "hidden_real_share": breakdown.hidden_real_share,
            "hidden_real_theme_count": breakdown.hidden_real_theme_count,
            "total_real_theme_count": breakdown.total_real_theme_count,
        },
        "all_themes": [
            {"name": t.name, "share": t.share, "count": t.count, "sentiment": t.sentiment} for t in all_themes
        ],
        "theme_chart_variants": theme_chart_variants,
        "explorations": explorations,
    }


def _report_build_error(e: BaseException) -> str | None:
    """Maps each exception `build_report`'s pipeline can raise to the exact human-readable message a
    caller used to receive as an HTTP error body (422/503) - now `job.error` instead. `None` for anything
    unanticipated, which `app.jobs.start_job` re-raises after marking the job failed generically."""
    if isinstance(e, NoThemesForColumn):
        return str(e)
    if isinstance(e, FindingsClaudeNotConfigured):
        # Defence in depth only: `get_claude_client` (the route's own `Depends`) already turns a missing
        # key into a 503 before the route body - and so before any job is even created - runs, so this
        # path is not expected to be reachable in practice. Kept because the brief this stream was built
        # from asks for it explicitly. See docs/DECISIONS.md.
        return "Report building needs a Claude key (ANTHROPIC_API_KEY) that is not configured yet."
    return None


# ---------------------------------------------------------------- routes

@router.post("/datasets/{dataset_id}/report/build", status_code=202)
def build_report(
    dataset_id: int,
    body: BuildRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    claude_client: ClaudeClient = Depends(get_claude_client),
):
    """Validates ownership and the Claude key (via `Depends(get_claude_client)`) synchronously - those stay
    immediate HTTP errors exactly as before. Whether themes exist yet (`NoThemesForColumn`) can only be
    known once `app.findings.build_findings` actually runs, so - like `TooFewAnswers` on the themes side -
    it now surfaces as `job.error` rather than a synchronous 422; `_report_build_error` maps it to the same
    message text a caller used to receive in the HTTP body. See docs/DECISIONS.md for why 202, not 200."""
    ds = _own_dataset(db, user, dataset_id, min_role="editor")
    column = body.column

    themes = list(db.scalars(
        select(Theme).where(Theme.dataset_id == ds.id, Theme.column_name == column).order_by(Theme.id)
    ).all())
    answer_lengths = None
    answer_texts = None
    quote_theme_texts = None
    answer_positions = None
    structured = None
    if themes:
        clean_df, plan = _load_clean_df(ds, db)
        answer_lengths = _answer_lengths_for(clean_df, column, themes)
        answer_texts = _answer_texts_for(clean_df, column, themes)
        quote_theme_texts = _quote_theme_texts_for(clean_df, column, themes)
        answer_positions = _answer_positions_for(db, ds.id, column)
        # Built here (synchronously, alongside answer_lengths above) rather than re-queried inside `_work`'s
        # own job-thread session: `StructuredContext` is plain data once built (no lingering ORM references),
        # so it crosses into the closure below exactly like `answer_lengths` already does - one fewer
        # DataFrame reload/DB round-trip in the background job for the same result.
        structured = _structured_context_for(db, ds, clean_df, plan, themes)

    # The only check left that can still fail synchronously: a full slot is knowable instantly, with no
    # thread started, so it stays an immediate 429 exactly like before.
    if not _SLOTS.acquire(blocking=False):
        raise HTTPException(429, "Report building is busy with other jobs. Try again in a few seconds.")

    dataset_id_ = ds.id
    cleaning_report = _cleaning_report_for(ds)
    job = create_job(db, dataset_id_, column, "report")

    def _work(step: Callable[[str], None]) -> None:
        with _db.SessionLocal() as job_db:
            job_ds = job_db.get(Dataset, dataset_id_)
            # `build_findings` is not modified (out of scope for this stream): candidate scoring, the one
            # batched `write_headline` Claude call, building `ReportData` and writing `Finding`/`Report`
            # rows all happen inside this single un-instrumented call, so this is the only real phase
            # boundary available before it - see docs/DECISIONS.md for why no separate "Writing headlines"
            # step is faked in between.
            step("Deciding what's worth telling")
            report = build_findings(
                job_ds, column, job_db, claude_client,
                cleaning_report=cleaning_report, answer_lengths=answer_lengths, answer_texts=answer_texts,
                quote_theme_texts=quote_theme_texts, answer_positions=answer_positions, structured=structured,
            )
            step("Drawing charts")
            # Rendered here too (and discarded) purely so a rendering bug fails the job with a plain
            # message instead of surfacing only later as a broken GET - `GET .../report` always re-renders
            # fresh from the stored rows regardless (app/findings.py's own "Render-vs-store-HTML" note).
            _render_report(job_db, job_ds, column, report)

    start_job(job, _SLOTS, _work, _report_build_error)

    return {"job_id": job.id, "status": "running"}


def _parse_filter_date(value: str | None, param_name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(422, f"{param_name} must be an ISO date (YYYY-MM-DD), got {value!r}.")


@router.get("/datasets/{dataset_id}/report")
def get_report(
    dataset_id: int,
    column: str,
    segment: str | None = None,
    score_band: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    ds = _own_dataset(db, user, dataset_id)

    report = _latest_report_for_column(db, ds.id, column)
    if report is None:
        themes_exist = db.scalar(
            select(Theme.id).where(Theme.dataset_id == ds.id, Theme.column_name == column).limit(1)
        ) is not None
        if not themes_exist:
            raise HTTPException(404, "No themes have been built yet for this column. Build themes first.")
        raise HTTPException(404, "No report has been built yet for this column. Build the report first.")

    parsed_from = _parse_filter_date(date_from, "date_from")
    parsed_to = _parse_filter_date(date_to, "date_to")
    return _render_report(
        db, ds, column, report,
        segment=segment, score_band=score_band, date_from=parsed_from, date_to=parsed_to,
    )


_EXPORT_CONTENT_TYPES = {
    "png": "image/png",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
}


@router.get("/datasets/{dataset_id}/report/export")
def export_report(
    dataset_id: int, column: str, format: str,
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    """Export (docs/TODO.md, fixed 2026-10-22; SPEC.md section 5): PNG/PPTX/PDF only - see
    `app/export.py`'s own module docstring for why SVG is deliberately not offered. Read-only (the
    default `min_role="viewer"` - an editor or viewer collaborator can export the same report the owner
    can, matching every other read route). Reuses `_render_report`'s own block list unchanged (same
    `chart_html`/`chart_width`/`chart_height` the live report page already renders) rather than a second
    rendering path - `app/export.py` only adds the headless-browser screenshot step on top."""
    if format not in _EXPORT_CONTENT_TYPES:
        raise HTTPException(422, f"format must be one of: {', '.join(_EXPORT_CONTENT_TYPES)}.")
    ds = _own_dataset(db, user, dataset_id)

    report = _latest_report_for_column(db, ds.id, column)
    if report is None:
        raise HTTPException(404, "No report has been built yet for this column. Build the report first.")

    body = _render_report(db, ds, column, report)
    blocks = [
        ExportBlock(title=b["chart_title"], html=b["chart_html"], width=b["chart_width"], height=b["chart_height"])
        for b in body["blocks"]
    ]

    if format == "png":
        data = render_report_png(blocks)
    elif format == "pptx":
        data = build_report_pptx(blocks)
    else:
        data = build_report_pdf(blocks)

    filename = f"report-{dataset_id}-{column}.{format}".replace(" ", "_")
    return Response(
        content=data, media_type=_EXPORT_CONTENT_TYPES[format],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
