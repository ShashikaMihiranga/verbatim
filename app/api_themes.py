"""Build-themes API (stream 6): wires the text pipeline (embed, cluster, label, sentiment - all already
built in `app/text_pipeline/`) to storage and an owner-only API.

POST /api/datasets/{id}/themes/build           embed + cluster + label + score one open-text column, replacing
                                                any themes already stored for that dataset + column
GET  /api/datasets/{id}/themes?column=...      list stored themes for a column
GET  /api/datasets/{id}/themes/{tid}/answers   paginated, REAL (unmasked) verbatim text behind one theme

Everything is owner-only (same `current_user`/`_own_dataset` as uploads and cleaning). Only one or two
build jobs run at once (`THEMES_CONCURRENCY`) - this is much heavier than cleaning (real embedding and
Claude calls, not just in-process pandas work), so the default cap is lower. See docs/DECISIONS.md
(2026-09-25 entry) for the concurrency, deadline, schema and DI choices made here.

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
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Callable

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api_upload import _own_dataset, current_user
from .cleaning import CleaningError, CleaningPlan
from .db import get_db
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
# A generous but finite deadline: embedding + clustering + one batched Claude call on a large column can
# genuinely take a while. 300s (5 min) is a judgement call, not a measurement - see docs/DECISIONS.md.
THEMES_DEADLINE_SECONDS = float(os.environ.get("THEMES_DEADLINE_SECONDS", "300") or 300)
_HEX64 = re.compile(r"[0-9a-f]{64}")


class _Slot:
    def __enter__(self):
        if not _SLOTS.acquire(blocking=False):
            raise HTTPException(429, "Theme building is busy with other jobs. Try again in a few seconds.")

    def __exit__(self, *exc):
        _SLOTS.release()


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


def _run_with_deadline(fn: Callable[[], object]) -> object:
    """Runs `fn` in a worker thread and waits at most `THEMES_DEADLINE_SECONDS` for it.

    This is a SOFT deadline: Python cannot forcibly kill a running thread, so a timed-out call keeps
    running in the background (its result is simply discarded) rather than being interrupted mid-network-
    call. Good enough to stop a single slow request from hanging forever; a real background job queue
    (Celery/RQ/etc.) is the right fix at scale - see docs/DECISIONS.md.
    """
    ex = ThreadPoolExecutor(max_workers=1)
    future = ex.submit(fn)
    try:
        return future.result(timeout=THEMES_DEADLINE_SECONDS)
    except FutureTimeoutError:
        raise HTTPException(
            504,
            f"Building themes took longer than {int(THEMES_DEADLINE_SECONDS)} seconds and was stopped. "
            "Try again, or with a smaller file.",
        ) from None
    finally:
        ex.shutdown(wait=False)


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


# ---------------------------------------------------------------- routes
@router.post("/datasets/{dataset_id}/themes/build")
def build_themes(
    dataset_id: int,
    body: BuildRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
    claude_client: ClaudeClient = Depends(get_claude_client),
    jev_factory: Callable[[], JevClient] = Depends(get_jev_client_factory),
):
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

    def _pipeline():
        result = embed_and_cluster(clean_df, plan, column, embedding_client)
        labels = label_clusters(result, question, claude_client)
        if body.use_jev_sentiment:
            scores = score_column_with_jev(clean_df, plan, column, jev_client)
        else:
            scores = score_column(clean_df, plan, column)
        return result, labels, scores

    with _Slot():
        try:
            result, labels, scores = _run_with_deadline(_pipeline)
        except TooFewAnswers as e:
            raise HTTPException(422, str(e)) from e
        except CleaningError as e:
            raise HTTPException(422, str(e)) from e
        except LabelingError as e:
            raise HTTPException(502, f"Theme labelling failed: {e}") from e
        except JevError as e:
            raise HTTPException(502, f"Jev sentiment scoring failed: {e}") from e

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

        column_row = db.scalar(select(Column).where(Column.dataset_id == ds.id, Column.name == column))
        column_id = column_row.id if column_row else None

        new_rows: list[Theme] = []
        for cluster, label in zip(result.clusters, real_labels):
            rows = [m.row for m in cluster.members]
            tone, sentiment = _aggregate(rows)
            new_rows.append(Theme(
                dataset_id=ds.id, column_id=column_id, column_name=column,
                label=label.label, description=label.description, size=label.size,
                sentiment=sentiment, tone=tone, answer_refs=rows,
            ))
        for label in other_labels:
            rows = [m.row for m in result.noise]
            tone, sentiment = _aggregate(rows)
            new_rows.append(Theme(
                dataset_id=ds.id, column_id=column_id, column_name=column,
                label=label.label, description=label.description, size=label.size,
                sentiment=sentiment, tone=tone, answer_refs=rows,
            ))

        # Nothing above touched the database - a rebuild replaces old themes with new ones atomically:
        # either every step above succeeded and this commits, or an exception was already raised and
        # nothing here runs, leaving any previously-stored themes untouched.
        for old in db.scalars(select(Theme).where(Theme.dataset_id == ds.id, Theme.column_name == column)).all():
            db.delete(old)
        db.add_all(new_rows)
        db.commit()

    total = result.total_answers
    return {
        "dataset_id": ds.id, "column": column, "total_answers": total,
        "themes": [_theme_dict(t, total) for t in new_rows],
    }


@router.get("/datasets/{dataset_id}/themes")
def list_themes(dataset_id: int, column: str, db: Session = Depends(get_db), user: User = Depends(current_user)):
    ds = _own_dataset(db, user, dataset_id)
    rows = db.scalars(
        select(Theme).where(Theme.dataset_id == ds.id, Theme.column_name == column).order_by(Theme.id)
    ).all()
    total = sum(t.size for t in rows)
    return {
        "dataset_id": ds.id, "column": column, "total_answers": total,
        "themes": [_theme_dict(t, total) for t in rows],
    }


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
