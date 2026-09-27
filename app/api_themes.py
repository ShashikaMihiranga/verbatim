"""Build-themes API (stream 6, now running as an async background job): wires the text pipeline (embed,
cluster, label, sentiment - all already built in `app/text_pipeline/`) to storage and an owner-only API.

POST /api/datasets/{id}/themes/build           validates everything cheap/instant (ownership, column,
                                                Jev/embedding/Claude keys) synchronously, then starts the
                                                real embed + cluster + label + score pipeline in a
                                                background thread and returns 202 {job_id, status:
                                                "running"} immediately - replacing any job/themes already
                                                stored for that dataset + column, same as before
GET  /api/datasets/{id}/themes?column=...      list stored themes for a column (poll this once the job for
                                                that column is "done" - see app/api_jobs.py)
GET  /api/datasets/{id}/themes/{tid}/answers   paginated, REAL (unmasked) verbatim text behind one theme

Everything is owner-only (same `current_user`/`_own_dataset` as uploads and cleaning). Only one or two
build jobs run at once (`THEMES_CONCURRENCY`) - this is much heavier than cleaning (real embedding and
Claude calls, not just in-process pandas work), so the default cap is lower. `app/jobs.py::start_job` is
the shared thread/status-update helper this module shares with `app/api_report.py`. See docs/DECISIONS.md
(2026-09-25 entry for the original concurrency/schema/DI choices; the dated "async build jobs" entry for
why the request no longer blocks on the pipeline at all).

Masking: `embed_and_cluster`/`label_clusters` only ever see text through `model_safe_column` (the pipeline's
own contract - this module never touches `clean_df[column]` directly for that). The `/answers` route is
different: the dataset's OWNER is looking at their own data, so it returns the real cleaned text, never the
masked version - masking exists only for the boundary to an external model (SPEC.md section 9.6 only asks
for suppression on sensitive/demographic columns and small groups, not on the owner's own view of their
own open-text answers).
"""
from __future__ import annotations

import io
import os
import re
import threading
from typing import Callable

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db as _db
from .api_upload import _own_dataset, current_user
from .chart_data import (
    ContextData, FreqData, MapData, OverviewData, PhraseData, QualityData, QuoteData, ReportData,
    ScoreData, SegmentData, TrendData,
)
from .charts import render_parts
from .cleaning import CleaningError, CleaningPlan
from .db import get_db
from .findings import question_for, theme_nodes
from .jobs import create_job, start_job
from .models import CleanedFile, Column, Dataset, Theme, User
from .text_pipeline import (
    AnthropicClaudeClient,
    ClaudeClient,
    EmbeddingClient,
    EmbeddingNotConfigured,
    HttpJevClient,
    JevClient,
    JevError,
    JevNotConfigured,
    LabelingClaudeNotConfigured,
    LabelingError,
    TooFewAnswers,
    VoyageEmbeddingClient,
    embed_and_cluster,
    label_clusters,
    score_column,
    score_column_with_jev,
    score_text,
    tone_split,
)

router = APIRouter(prefix="/api")

# Embedding + Claude labelling of a full column means real network round trips, not just in-process pandas
# work like cleaning - so the default concurrency cap is lower than `CLEAN_CONCURRENCY`'s.
_SLOTS = threading.BoundedSemaphore(max(1, int(os.environ.get("THEMES_CONCURRENCY", "1") or 1)))
# Kept as a background-thread watchdog, not retired: nothing blocks on it from the request side any more
# (the route returns as soon as the job is created), but a truly hung embedding/Claude call could otherwise
# leave a job stuck at "running" forever with no one ever told. `_watchdog` below marks the job failed with
# a clear message if the pipeline itself does not finish inside this many seconds - see docs/DECISIONS.md.
THEMES_DEADLINE_SECONDS = float(os.environ.get("THEMES_DEADLINE_SECONDS", "300") or 300)
_HEX64 = re.compile(r"[0-9a-f]{64}")


# ---------------------------------------------------------------- client DI (see docs/DECISIONS.md)
# Each provider defaults to building the real, env-configured client, translating that client's own
# *NotConfigured exception into a clear 503 - never a generic 500 stack trace. Tests override these via
# `app.dependency_overrides`, the same mechanism already used for `current_user` in this codebase.

def get_embedding_client() -> EmbeddingClient:
    try:
        return VoyageEmbeddingClient()
    except EmbeddingNotConfigured as e:
        raise HTTPException(
            503, "Theme building needs an embedding key (VOYAGE_API_KEY) that is not configured yet."
        ) from e


def get_claude_client() -> ClaudeClient:
    try:
        return AnthropicClaudeClient()
    except LabelingClaudeNotConfigured as e:
        raise HTTPException(
            503, "Theme building needs a Claude key (ANTHROPIC_API_KEY) that is not configured yet."
        ) from e


def get_jev_client_factory() -> Callable[[], JevClient]:
    """A factory, not a client: Jev is opt-in (`use_jev_sentiment`), so building it must not happen (and
    must not fail) on every request - only when a caller actually asks for it. The route calls this factory
    itself, inside a try/except, only when `body.use_jev_sentiment` is true."""
    return HttpJevClient


# ---------------------------------------------------------------- helpers
def _load_clean_df(ds: Dataset, db: Session) -> tuple[pd.DataFrame, CleaningPlan]:
    stored = dict((ds.profile or {}).get("cleaning") or {})
    if "plan" not in stored:
        raise HTTPException(409, "Clean this dataset (see /cleaning) before building themes.")
    if "clean_hash" not in stored:
        raise HTTPException(409, "Apply cleaning before building themes.")
    plan = CleaningPlan.from_dict(stored["plan"])
    clean_hash = stored.get("clean_hash") or ""
    if not _HEX64.fullmatch(clean_hash):
        raise HTTPException(404, "The cleaned file for this dataset is not available.")
    row = db.get(CleanedFile, clean_hash)
    if row is None:
        raise HTTPException(404, "The cleaned file for this dataset is not available.")
    try:
        # No temp file needed here (unlike _load_df in app/api_cleaning.py): pandas reads BytesIO natively.
        df = pd.read_csv(io.BytesIO(row.content))
    except Exception as e:  # pragma: no cover - a malformed internal file should never happen
        raise HTTPException(400, "We could not read the cleaned file for this dataset.") from e
    return df, plan


def _theme_dict(t: Theme, total: int) -> dict:
    # "Other" is always the locally-synthesized catch-all (see app/text_pipeline/labeling.py), never a
    # real theme - identified by its label text, which that module fixes to exactly "Other".
    is_other = t.label == "Other"
    solid = (not is_other) and total > 0 and t.size >= max(20, round(0.08 * total))
    return {
        "id": t.id,
        "label": t.label,
        "description": t.description,
        "size": t.size,
        "size_pct": round((t.size / total) * 100, 1) if total else 0.0,
        "sentiment": t.sentiment,
        "tone": t.tone,
        "confidence": "tentative" if is_other or not solid else "solid",
    }


class BuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = Field(max_length=255)
    use_jev_sentiment: bool = False


def _write_theme_rows(
    db: Session, dataset_id: int, column: str, result, labels, scores,
) -> list[Theme]:
    """The row-building/replace step `build_themes` used to run inline, synchronously, at the end of its
    request. Factored out so the background job thread (see `app/jobs.py`) can call it with its OWN
    short-lived `Session` once the real pipeline work finishes - the request's own `db` session is long
    gone by then, since the request itself returned as soon as the job was created."""
    scores_by_row = {s.row: s for s in scores if s is not None}

    def _aggregate(rows: list[int]) -> tuple[dict, float]:
        theme_scores = [scores_by_row[r] for r in rows if r in scores_by_row]
        ts = tone_split(theme_scores)
        sentiment = sum(s.polarity for s in theme_scores) / len(theme_scores) if theme_scores else 0.0
        return {"neg": ts.neg, "neu": ts.neu, "pos": ts.pos}, sentiment

    # `label_clusters` returns one entry per `result.clusters` (same order), plus at most one extra
    # "Other" entry appended at the end iff `result.noise` is non-empty - see its docstring.
    real_labels = labels[: len(result.clusters)]
    other_labels = labels[len(result.clusters):]

    column_row = db.scalar(select(Column).where(Column.dataset_id == dataset_id, Column.name == column))
    column_id = column_row.id if column_row else None

    new_rows: list[Theme] = []
    for cluster, label in zip(result.clusters, real_labels):
        rows = [m.row for m in cluster.members]
        tone, sentiment = _aggregate(rows)
        new_rows.append(Theme(
            dataset_id=dataset_id, column_id=column_id, column_name=column,
            label=label.label, description=label.description, size=label.size,
            sentiment=sentiment, tone=tone, answer_refs=rows,
        ))
    for label in other_labels:
        rows = [m.row for m in result.noise]
        tone, sentiment = _aggregate(rows)
        new_rows.append(Theme(
            dataset_id=dataset_id, column_id=column_id, column_name=column,
            label=label.label, description=label.description, size=label.size,
            sentiment=sentiment, tone=tone, answer_refs=rows,
        ))

    # A rebuild replaces old themes with new ones atomically: either every step above succeeded and this
    # commits, or an exception was already raised and nothing here runs, leaving any previously-stored
    # themes untouched.
    for old in db.scalars(select(Theme).where(Theme.dataset_id == dataset_id, Theme.column_name == column)).all():
        db.delete(old)
    db.add_all(new_rows)
    db.commit()
    return new_rows


def _theme_build_error(e: BaseException) -> str | None:
    """Maps each exception `build_themes`'s pipeline can raise to the exact human-readable message a
    caller used to receive as an HTTP error body (422/502) - now `job.error` instead. Returns `None` for
    anything unanticipated, which `app.jobs.start_job` re-raises after marking the job failed with a
    generic message, so it still surfaces in server logs rather than being silently swallowed."""
    if isinstance(e, TooFewAnswers):
        return str(e)
    if isinstance(e, CleaningError):
        return str(e)
    if isinstance(e, LabelingError):
        return f"Theme labelling failed: {e}"
    if isinstance(e, JevError):
        return f"Jev sentiment scoring failed: {e}"
    return None


# ---------------------------------------------------------------- routes
@router.post("/datasets/{dataset_id}/themes/build", status_code=202)
def build_themes(
    dataset_id: int,
    body: BuildRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
    claude_client: ClaudeClient = Depends(get_claude_client),
    jev_factory: Callable[[], JevClient] = Depends(get_jev_client_factory),
):
    """Validates everything that can fail cheaply and instantly BEFORE starting any background work -
    ownership, column exists, Jev key check if requested, embedding/Claude key checks (via the `Depends`
    providers above) - so those stay immediate HTTP errors exactly as before. Once validated, the real
    pipeline (embed, cluster, label, score) runs in a background daemon thread; this route returns as soon
    as the `Job` row exists, never blocking on the pipeline itself. See docs/DECISIONS.md for why this
    returns 202, not 200."""
    ds = _own_dataset(db, user, dataset_id)
    clean_df, plan = _load_clean_df(ds, db)
    column = body.column
    if column not in plan.columns:
        raise HTTPException(422, "Unknown column.")

    jev_client: JevClient | None = None
    if body.use_jev_sentiment:
        try:
            jev_client = jev_factory()
        except JevNotConfigured as e:
            raise HTTPException(
                503, "Jev sentiment needs a TypeSafe key (TYPESAFE_API_KEY) that is not configured yet."
            ) from e

    confirmed = (ds.profile or {}).get("confirmed") or {}
    question = (confirmed.get("question") or "").strip()
    if not question:
        question = ((ds.profile or {}).get("question") or {}).get("text") or column

    # The only check left that can still fail synchronously: a full slot is knowable instantly, with no
    # thread started, so it stays an immediate 429 exactly like before - see app/jobs.py:start_job's
    # docstring for why the slot is acquired here but released inside the thread once real work finishes.
    if not _SLOTS.acquire(blocking=False):
        raise HTTPException(429, "Theme building is busy with other jobs. Try again in a few seconds.")

    dataset_id_ = ds.id
    use_jev = body.use_jev_sentiment
    job = create_job(db, dataset_id_, column, "themes")

    def _work(step: Callable[[str], None]) -> None:
        step("Turning answers into vectors")
        result = embed_and_cluster(clean_df, plan, column, embedding_client)
        step("Naming each group")
        labels = label_clusters(result, question, claude_client)
        step("Scoring tone")
        if use_jev:
            scores = score_column_with_jev(clean_df, plan, column, jev_client)
        else:
            scores = score_column(clean_df, plan, column)
        with _db.SessionLocal() as job_db:
            _write_theme_rows(job_db, dataset_id_, column, result, labels, scores)

    start_job(
        job, _SLOTS, _work, _theme_build_error,
        deadline_seconds=THEMES_DEADLINE_SECONDS,
        deadline_message=(
            f"Building themes took longer than {int(THEMES_DEADLINE_SECONDS)} seconds and did not finish "
            "in time. Try again, or with a smaller file."
        ),
    )

    return {"job_id": job.id, "status": "running"}


def _stored_themes(db: Session, dataset_id: int, column: str) -> list[Theme]:
    """Shared by `list_themes` and `themes_chart` below - one query for "this dataset + column's stored
    Theme rows, largest-first-by-construction (see `_write_theme_rows`: clusters are sorted by size before
    Other is appended)", not duplicated per route."""
    return list(db.scalars(
        select(Theme).where(Theme.dataset_id == dataset_id, Theme.column_name == column).order_by(Theme.id)
    ).all())


@router.get("/datasets/{dataset_id}/themes")
def list_themes(dataset_id: int, column: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ds = _own_dataset(db, user, dataset_id)
    rows = _stored_themes(db, ds.id, column)
    total = sum(t.size for t in rows)
    return {
        "dataset_id": ds.id, "column": column, "total_answers": total,
        "themes": [_theme_dict(t, total) for t in rows],
    }


@router.get("/datasets/{dataset_id}/themes/chart")
def themes_chart(
    dataset_id: int, column: str, db: Session = Depends(get_db), user: User = Depends(current_user),
):
    """Lightweight companion to `list_themes` above, for the Themes screen's "one chart at a glance instead
    of a wall of cards" browse view (the user's standing complaint - see docs/DECISIONS.md): same
    ownership/theme-lookup as `list_themes` (`_own_dataset` + `_stored_themes`, not a second copy of that
    check), but returns a ready-to-embed treemap fragment - `app.charts.render_parts`'s exact wire shape
    (`chart_html`/`chart_width`/`chart_height`) - instead of a JSON theme list, so the frontend can reuse
    one fragment-rendering component (`ThemeChart.tsx`) for both this screen and the report page's overview
    block.

    Builds only enough of a `ReportData` for `render_parts("treemap", ...)` to actually need: `themes`
    (via `app.findings.theme_nodes`, the same colour-assignment logic `build_report_data` uses - not
    reimplemented here) and `question` (via `app.findings.question_for`, ditto). Every other `ReportData`
    field is an innocuous placeholder (empty list, zero, empty string) since this route only ever calls the
    treemap renderer, never the full `render_parts` dispatch table's other chart ids - unlike
    `app.api_report._render_report`, which needs a fully-populated `ReportData` because it renders whatever
    chart id each report block asks for.
    """
    ds = _own_dataset(db, user, dataset_id)
    rows = _stored_themes(db, ds.id, column)
    if not rows:
        raise HTTPException(404, "No themes have been built yet for this column. Build themes first.")

    total = sum(t.size for t in rows)
    nodes = theme_nodes(rows, total)
    question = question_for(ds, column)
    placeholder_theme = nodes[0].name if nodes else ""

    data = ReportData(
        question=question, total=total, answered=total, overall_sentiment=0.0, themes=nodes,
        selected_theme=placeholder_theme, hover_theme=placeholder_theme,
        overview=OverviewData(stats=[], insights=[]),
        score=ScoreData(name="", bands=[]),
        segment=SegmentData(name="", groups=[], rows=[]),
        trend=TrendData(labels=[], series=[], sentiment=[], hover_index=0, note=""),
        cooccurrence=[],
        answer_map=MapData(seed=0, tip_text="", tip_note=""),
        frequency=FreqData(question="", answered=0, items=[], highlight="", footnote=""),
        phrases=PhraseData(phrases=[], highlight=""),
        quotes=QuoteData(quotes=[], highlight_index=0),
        quality=QualityData(bins=[], typical_bin="", typical_note="", notes=[]),
        context=ContextData(kind="", kind_options=[], kind_hover="", framing="", length="", columns_note=""),
    )
    chart_html, chart_width, chart_height = render_parts("treemap", data)
    return {"chart_html": chart_html, "chart_width": chart_width, "chart_height": chart_height}


@router.get("/datasets/{dataset_id}/themes/{theme_id}/answers")
def theme_answers(
    dataset_id: int, theme_id: int, limit: int = 20, offset: int = 0,
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    ds = _own_dataset(db, user, dataset_id)
    theme = db.get(Theme, theme_id)
    if theme is None or theme.dataset_id != ds.id:
        raise HTTPException(404, "Theme not found.")

    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    refs = theme.answer_refs or []
    page = refs[offset: offset + limit]

    answers: list[dict] = []
    if page:
        # Real, unmasked cleaned text: the dataset's owner is looking at their own answers, not sending
        # them to a model - `model_safe_column` is deliberately NOT used here (see module docstring).
        clean_df, _plan = _load_clean_df(ds, db)
        column = theme.column_name
        for row in page:
            try:
                raw = clean_df.at[row, column] if column else None
            except KeyError:
                raw = None
            if not isinstance(raw, str):
                continue
            # Per-answer tone, computed on the fly with the free lexicon (no network, no stored table) -
            # see docs/DECISIONS.md for why per-row sentiment is not persisted separately from this.
            _polarity, tone = score_text(raw)
            answers.append({"row": int(row), "text": raw, "tone": tone})

    return {"theme_id": theme.id, "total": len(refs), "limit": limit, "offset": offset, "answers": answers}
