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

import os
import threading
from datetime import date
from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db as _db
from .api_themes import _load_clean_df, get_claude_client
from .api_upload import _own_dataset, current_user
from .charts import TITLES, render_parts
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
from .models import Dataset, Finding, Report, Theme, User
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
    filter_options = _filter_options_for(structured)
    filter_rows = resolve_filter_rows(structured, segment, score_band, date_from, date_to)
    if filter_rows is not None:
        structured = _structured_context_for(db, ds, clean_df, plan, themes, filter_rows=filter_rows)
    answer_lengths = _answer_lengths_for(clean_df, column, themes)
    question = content.get("question") or column
    report_data = build_report_data(
        ds, themes, _cleaning_report_for(ds), question, answer_lengths=answer_lengths, structured=structured,
        filter_rows=filter_rows,
    )
    breakdown, all_themes = other_breakdown(themes, report_data.answered, filter_rows=filter_rows)

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
        # `render_parts` returns the raw body fragment (no `<!doctype html>`/own background/own font load) -
        # see app/charts.py's own docstring split between `render_parts` and `render`. The frontend embeds
        # this fragment straight into the report page's DOM (never an iframe), so it inherits the page's own
        # already-loaded `--bg --surface --ink ...` tokens instead of carrying a second copy of them - see
        # docs/DECISIONS.md ("report page: fragments, not iframed documents").
        chart_html, chart_width, chart_height = render_parts(chart_id, report_data)
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
        fid = b.get("finding_id")
        if b["kind"] == "finding" and fid is not None and fid in findings_by_id:
            f = findings_by_id[fid]
            block["finding"] = {
                "id": f.id, "theme_id": f.theme_id, "sentence": f.sentence, "confidence": f.confidence,
            }
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
        columns_used.append({"name": structured.score_column_name, "role": "score"})
    if structured.segment is not None:
        columns_used.append({"name": structured.segment_column_name, "role": "segment"})
    if structured.trend is not None:
        columns_used.append({"name": structured.trend_column_name, "role": "date"})

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
    ds = _own_dataset(db, user, dataset_id)
    column = body.column

    themes = list(db.scalars(
        select(Theme).where(Theme.dataset_id == ds.id, Theme.column_name == column).order_by(Theme.id)
    ).all())
    answer_lengths = None
    structured = None
    if themes:
        clean_df, plan = _load_clean_df(ds, db)
        answer_lengths = _answer_lengths_for(clean_df, column, themes)
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
                cleaning_report=cleaning_report, answer_lengths=answer_lengths, structured=structured,
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
