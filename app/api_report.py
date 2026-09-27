"""Dynamic-report API (stream 8): wires `app/findings.py` (built, tested and merged already) to storage
and an owner-only HTTP layer, matching `app/api_themes.py`'s conventions exactly rather than inventing a
second style for the same kind of route.

POST /api/datasets/{id}/report/build   body {"column": str} -> builds/rebuilds the report for that column
                                        (embeds no new network step of its own: themes must already exist -
                                        `app.findings.build_findings` does the real work, one batched Claude
                                        call for headlines only) and returns it fully rendered, same shape
                                        as the GET below.
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
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api_themes import _load_clean_df, get_claude_client
from .api_upload import _own_dataset, current_user
from .charts import TITLES, render
from .db import get_db
from .findings import (
    FindingsClaudeNotConfigured,
    NoThemesForColumn,
    build_findings,
    build_report_data,
)
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


class _Slot:
    def __enter__(self):
        if not _SLOTS.acquire(blocking=False):
            raise HTTPException(429, "Report building is busy with other jobs. Try again in a few seconds.")

    def __exit__(self, *exc):
        _SLOTS.release()


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


def _latest_report_for_column(db: Session, dataset_id: int, column: str) -> Report | None:
    # `build_findings` deletes any prior report for this dataset+column before writing a new one (see its
    # docstring), so at most one row should ever match - `order_by(id.desc())` is defensive, not load-bearing.
    rows = db.scalars(select(Report).where(Report.dataset_id == dataset_id).order_by(Report.id.desc())).all()
    for r in rows:
        if isinstance(r.content, dict) and r.content.get("column") == column:
            return r
    return None


def _render_report(db: Session, ds: Dataset, column: str, report: Report) -> dict[str, Any]:
    """Builds the JSON body for both routes below: one `build_report_data` call, reused for every block's
    `render()` (per app/findings.py's own instruction - never rebuilt per block)."""
    content = report.content or {}
    themes = list(db.scalars(
        select(Theme).where(Theme.dataset_id == ds.id, Theme.column_name == column).order_by(Theme.id)
    ).all())
    clean_df, _plan = _load_clean_df(ds, db)
    answer_lengths = _answer_lengths_for(clean_df, column, themes)
    question = content.get("question") or column
    report_data = build_report_data(ds, themes, _cleaning_report_for(ds), question, answer_lengths=answer_lengths)

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
        block: dict[str, Any] = {
            "kind": b["kind"],
            "chart_id": chart_id,
            "chart_title": TITLES.get(chart_id, chart_id),
            "chart_html": render(chart_id, report_data),
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

    return {
        "dataset_id": ds.id,
        "column": column,
        "question": question,
        "summary": summary,
        "also_checked_nothing_notable": bool(content.get("also_checked_nothing_notable")),
        "blocks": blocks_out,
    }


# ---------------------------------------------------------------- routes

@router.post("/datasets/{dataset_id}/report/build")
def build_report(
    dataset_id: int,
    body: BuildRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    claude_client: ClaudeClient = Depends(get_claude_client),
):
    ds = _own_dataset(db, user, dataset_id)
    column = body.column

    themes = list(db.scalars(
        select(Theme).where(Theme.dataset_id == ds.id, Theme.column_name == column).order_by(Theme.id)
    ).all())
    answer_lengths = None
    if themes:
        clean_df, _plan = _load_clean_df(ds, db)
        answer_lengths = _answer_lengths_for(clean_df, column, themes)

    with _Slot():
        try:
            report = build_findings(
                ds, column, db, claude_client,
                cleaning_report=_cleaning_report_for(ds), answer_lengths=answer_lengths,
            )
        except NoThemesForColumn as e:
            raise HTTPException(422, str(e)) from e
        except FindingsClaudeNotConfigured as e:
            # Defence in depth only: `get_claude_client` above already turns a missing key into a 503
            # before this route body ever runs (same provider `app.api_themes` uses), so this path is not
            # expected to be reachable in practice - kept because the brief this stream was built from asks
            # for it explicitly. See docs/DECISIONS.md.
            raise HTTPException(
                503, "Report building needs a Claude key (ANTHROPIC_API_KEY) that is not configured yet."
            ) from e

    return _render_report(db, ds, column, report)


@router.get("/datasets/{dataset_id}/report")
def get_report(
    dataset_id: int,
    column: str,
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

    return _render_report(db, ds, column, report)
