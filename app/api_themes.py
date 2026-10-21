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
GET  .../themes/{tid}/sub-themes/{i}/answers   same, for one theme's i-th sub-theme (see app/text_pipeline/
                                                subthemes.py - a theme is split into up to 3 sub-themes only
                                                when it qualifies; most themes' `sub_themes` stays `[]`)

Everything is owner-only (same `current_user`/`_own_dataset` as uploads and cleaning). Only one or two
build jobs run at once (`THEMES_CONCURRENCY`) - this is much heavier than cleaning (real embedding and
Claude calls, not just in-process pandas work), so the default cap is lower. `app/jobs.py::start_job` is
the shared thread/status-update helper this module shares with `app/api_report.py`. See docs/DECISIONS.md
(2026-09-25 entry for the original concurrency/schema/DI choices; the dated "async build jobs" entry for
why the request no longer blocks on the pipeline at all).

Masking: `embed_and_cluster_with_vectors`/`label_clusters` only ever see text through `model_safe_column`
(the pipeline's own contract - this module never touches `clean_df[column]` directly for that). The `/answers` route is
different: the dataset's OWNER is looking at their own data, so it returns the real cleaned text, never the
masked version - masking exists only for the boundary to an external model (SPEC.md section 9.6 only asks
for suppression on sensitive/demographic columns and small groups, not on the owner's own view of their
own open-text answers).
"""
from __future__ import annotations

import io
import logging
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
from .cleaning import CleaningError, CleaningPlan, model_safe_column
from .db import get_db
from .findings import question_for, theme_nodes
from .jobs import create_job, start_job
from .models import CleanedFile, Column, Dataset, Job, Theme, User
from .text_pipeline import (
    AnswerScore,
    AnthropicClaudeClient,
    ClaudeClient,
    Cluster,
    EmbeddingClient,
    EmbeddingNotConfigured,
    HttpJevClient,
    JevClient,
    JevError,
    JevNotConfigured,
    LabelingClaudeNotConfigured,
    LabelingError,
    ThemeLabel,
    TooFewAnswers,
    VoyageEmbeddingClient,
    embed_and_cluster_with_vectors,
    label_clusters_with_retry,
    label_sub_clusters_with_retry,
    score_column,
    score_column_with_jev,
    score_text,
    tone_split,
)
from .text_pipeline.clustering import MIN_MIN_CLUSTER_SIZE
from .text_pipeline.merging import apply_merges, apply_sub_merges
from .text_pipeline.other_classify import (
    NONE_OF_THESE,
    build_classification_question,
    classify_other_answers,
    label_and_consolidate,
    recluster_other,
)
from .text_pipeline.subthemes import sub_cluster_themes

router = APIRouter(prefix="/api")
log = logging.getLogger("verbatim.themes")

# Embedding + Claude labelling of a full column means real network round trips, not just in-process pandas
# work like cleaning - so the default concurrency cap is lower than `CLEAN_CONCURRENCY`'s.
_SLOTS = threading.BoundedSemaphore(max(1, int(os.environ.get("THEMES_CONCURRENCY", "1") or 1)))
# Kept as a background-thread watchdog, not retired: nothing blocks on it from the request side any more
# (the route returns as soon as the job is created), but a truly hung embedding/Claude call could otherwise
# leave a job stuck at "running" forever with no one ever told. `_watchdog` below marks the job failed with
# a clear message if the pipeline itself does not finish inside this many seconds - see docs/DECISIONS.md.
# This is the FLOOR, not a flat deadline any more - `_themes_deadline_for` below scales it up for large
# files (see that function's own comment for why a flat 300s was confirmed live to kill real, still-
# progressing large builds before they could finish).
THEMES_DEADLINE_SECONDS = float(os.environ.get("THEMES_DEADLINE_SECONDS", "300") or 300)
# Conservative answers/second floor for the whole embed+cluster+label pipeline, used only to size the
# watchdog - NOT a performance target. Deliberately conservative: production (2026-10-09, Railway, 8 vCPU
# plan) did not finish embedding a 74,681-row file within 300s even with concurrent embedding batches, so
# the true throughput there is unknown but definitely well under this codebase's own unconstrained sandbox
# measurement (~1,170 answers/sec) - 100/sec is a deliberately pessimistic floor so the deadline stays a
# genuine safety net (still catches a truly hung call) without being the thing that kills a slow-but-real
# large build. Env-overridable for the same reason the other knobs here are.
THEMES_ANSWERS_PER_SECOND_FLOOR = float(os.environ.get("THEMES_ANSWERS_PER_SECOND_FLOOR", "100") or 100)


def _themes_deadline_for(n_answers: int) -> float:
    """Scales the watchdog deadline up for large files instead of one flat 300s for every size - a 500-
    answer file keeps today's exact 300s floor (unchanged behaviour for the common case, and still exactly
    what `THEMES_DEADLINE_SECONDS` alone controls when monkeypatched small in tests, see
    test_api_themes.py::test_watchdog_marks_a_truly_stuck_job_failed_without_stopping_the_real_thread); a
    74,681-answer file like the one that motivated this gets roughly 1,047s (~17.4 min:
    `THEMES_DEADLINE_SECONDS` + 74681/100), real headroom instead of a near-certain kill partway through
    embedding. `n_answers` only needs to be a reasonable magnitude, not exact - callers pass a cheap raw
    non-null count, not the real masked/cleaned count `embed_and_cluster_with_vectors` itself computes
    later."""
    return THEMES_DEADLINE_SECONDS + n_answers / THEMES_ANSWERS_PER_SECOND_FLOOR
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


def get_jev_client() -> JevClient:
    """Unlike `get_jev_client_factory` above, Jev is NOT optional for "Look inside Other" - the whole
    feature's per-answer classification step depends on it (see `app/text_pipeline/other_classify.py`'s
    own docstring for why Claude and Jev are each used for what they're good at). Same DI shape as
    `get_embedding_client`/`get_claude_client`: build the real client eagerly, turn its own
    *NotConfigured exception into a clear 503."""
    try:
        return HttpJevClient()
    except JevNotConfigured as e:
        raise HTTPException(
            503, "Looking inside Other needs a TypeSafe key (TYPESAFE_API_KEY) that is not configured yet."
        ) from e


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
        # Never `answer_refs` here - that stays drill-down-only, via GET .../sub-themes/{index}/answers.
        "sub_themes": [
            {
                "index": i, "label": s["label"], "description": s["description"], "size": s["size"],
                "size_pct": round(s["size"] / total * 100, 1) if total else 0.0,
                "sentiment": s["sentiment"], "tone": s["tone"],
            }
            for i, s in enumerate(t.sub_themes or [])
        ],
    }


class BuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = Field(max_length=255)
    use_jev_sentiment: bool = False


def _aggregate_tone(rows: list[int], scores_by_row: dict[int, object]) -> tuple[dict, float]:
    """Shared by `_write_theme_rows` for both a theme's own tone/sentiment and each of its sub-themes' -
    lifted out of what used to be `_write_theme_rows`'s own inner `_aggregate` closure so it can be reused
    for sub-theme rows too, not duplicated."""
    theme_scores = [scores_by_row[r] for r in rows if r in scores_by_row]
    ts = tone_split(theme_scores)
    sentiment = sum(s.polarity for s in theme_scores) / len(theme_scores) if theme_scores else 0.0
    return {"neg": ts.neg, "neu": ts.neu, "pos": ts.pos}, sentiment


def _write_theme_rows(
    db: Session, dataset_id: int, column: str, result, labels, scores,
    sub_clusters: dict[int, list[Cluster]] | None = None,
    sub_labels: dict[int, list[ThemeLabel]] | None = None,
) -> list[Theme]:
    """The row-building/replace step `build_themes` used to run inline, synchronously, at the end of its
    request. Factored out so the background job thread (see `app/jobs.py`) can call it with its OWN
    short-lived `Session` once the real pipeline work finishes - the request's own `db` session is long
    gone by then, since the request itself returned as soon as the job was created.

    `sub_clusters`/`sub_labels` are optional (`None` = today's exact behaviour, every theme's `sub_themes`
    ends up `[]`): `sub_clusters` is `subthemes.sub_cluster_themes`'s own return shape
    (`{parent Cluster.id: [kept sub-Clusters, largest first]}`), `sub_labels` is `label_sub_clusters`'s
    (`{parent Cluster.id: [ThemeLabel, ...]}`, same order as `sub_clusters[parent_id]`). A real theme whose
    `cluster.id` is a key in BOTH gets a real `sub_themes` list; every other real theme, and "Other"
    unconditionally (sub-clustering never touches noise/"Other" - see subthemes.py), gets `[]`."""
    scores_by_row = {s.row: s for s in scores if s is not None}

    # `label_clusters` returns one entry per `result.clusters` (same order), plus at most one extra
    # "Other" entry appended at the end iff `result.noise` is non-empty - see its docstring.
    real_labels = labels[: len(result.clusters)]
    other_labels = labels[len(result.clusters):]

    column_row = db.scalar(select(Column).where(Column.dataset_id == dataset_id, Column.name == column))
    column_id = column_row.id if column_row else None

    new_rows: list[Theme] = []
    for cluster, label in zip(result.clusters, real_labels):
        rows = [m.row for m in cluster.members]
        tone, sentiment = _aggregate_tone(rows, scores_by_row)

        sub_themes_json: list[dict] = []
        if sub_clusters and sub_labels and cluster.id in sub_clusters:
            for sub_cluster, sub_label in zip(sub_clusters[cluster.id], sub_labels[cluster.id]):
                sub_rows = [m.row for m in sub_cluster.members]
                sub_tone, sub_sentiment = _aggregate_tone(sub_rows, scores_by_row)
                sub_themes_json.append({
                    "label": sub_label.label, "description": sub_label.description, "size": sub_label.size,
                    "sentiment": sub_sentiment, "tone": sub_tone, "answer_refs": sub_rows,
                })

        new_rows.append(Theme(
            dataset_id=dataset_id, column_id=column_id, column_name=column,
            label=label.label, description=label.description, size=label.size,
            sentiment=sentiment, tone=tone, answer_refs=rows, sub_themes=sub_themes_json,
        ))
    for label in other_labels:
        rows = [m.row for m in result.noise]
        tone, sentiment = _aggregate_tone(rows, scores_by_row)
        new_rows.append(Theme(
            dataset_id=dataset_id, column_id=column_id, column_name=column,
            label=label.label, description=label.description, size=label.size,
            sentiment=sentiment, tone=tone, answer_refs=rows, sub_themes=[],
        ))

    # A rebuild replaces old themes with new ones atomically: either every step above succeeded and this
    # commits, or an exception was already raised and nothing here runs, leaving any previously-stored
    # themes untouched.
    for old in db.scalars(select(Theme).where(Theme.dataset_id == dataset_id, Theme.column_name == column)).all():
        db.delete(old)
    db.add_all(new_rows)
    db.commit()
    return new_rows


# A newly-discovered sub-theme needs at least this many matched answers to become its own stored `Theme`
# row - MIN_MIN_CLUSTER_SIZE is clustering.py's own floor for "enough answers to mean anything", reused
# here rather than a second magic number, matching subthemes.py's own `sub_cluster_min_size` precedent.
MIN_OTHER_NEW_THEME_SIZE = MIN_MIN_CLUSTER_SIZE


def _apply_other_classification(
    db: Session, dataset_id: int, column: str, other_theme_id: int,
    by_row: dict[int, str], new_label_descriptions: dict[str, str],
    row_text: dict[int, str],
) -> dict | None:
    """Writes "Look inside Other"'s results: UPDATES, not `_write_theme_rows`'s full delete-and-replace
    (that would also wipe every untouched known theme). `by_row` is `other_classify.OtherClassification
    .by_row` - row -> the label Jev chose, `NONE_OF_THESE` for "still genuinely unclassifiable". A row
    missing from `by_row` entirely (its own Jev call failed - see `OtherClassification.failed_rows`) is
    treated exactly like `NONE_OF_THESE`: it stays in Other rather than being silently dropped.

    Sentiment/tone for every TOUCHED theme (a known theme gaining rows, a new theme, or Other losing
    rows) is recomputed from scratch over its own full, final `answer_refs` - via the free lexicon
    (`score_text`, no network), same aggregation (`_aggregate_tone`) `_write_theme_rows` already uses -
    rather than trying to incrementally merge a previously-stored aggregate with new rows, which would
    need the OLD per-row scores this function was never given and has no other way to recover.

    Other's `Theme` row is deleted outright if nothing remains unclassified afterward (matching how a
    dataset that genuinely has no noise cluster at all already looks to every downstream reader - see
    `theme_nodes`'s own `next((t for t in themes if t.label == "Other"), None)`), not kept as a
    zero-size row nothing downstream expects.

    Returns a small summary dict (Stage 3, docs/TODO.md 2026-10-21: the animated flow's own
    Known/New/Still-in-Other results panel needs these real counts, not a second query reconstructing
    them after the fact) - `{"known_added": int, "new_themes": [{"label", "count"}], "still_other_count":
    int}` - or `None` if `other` was already gone (nothing to summarize)."""
    other = db.get(Theme, other_theme_id)
    if other is None:
        return None  # dataset/column was deleted or rebuilt from under this job; nothing left to update

    known_by_label = {
        t.label: t
        for t in db.scalars(
            select(Theme).where(Theme.dataset_id == dataset_id, Theme.column_name == column, Theme.id != other_theme_id)
        ).all()
    }

    matched_known: dict[str, list[int]] = {}
    matched_new: dict[str, list[int]] = {}
    still_other: list[int] = []
    for row in other.answer_refs or []:
        choice = by_row.get(row, NONE_OF_THESE)
        if choice == NONE_OF_THESE:
            still_other.append(row)
        elif choice in known_by_label:
            matched_known.setdefault(choice, []).append(row)
        elif choice in new_label_descriptions:
            matched_new.setdefault(choice, []).append(row)
        else:  # a choice that is neither a known label nor one we asked Jev to use - treat as unclassifiable
            still_other.append(row)

    def _scores_for(rows: list[int]) -> dict[int, AnswerScore]:
        out: dict[int, AnswerScore] = {}
        for row in rows:
            text = row_text.get(row)
            if text is None:
                continue
            polarity, tone = score_text(text)
            out[row] = AnswerScore(row=row, text=text, polarity=polarity, tone=tone)
        return out

    known_added = 0
    for label, new_rows in matched_known.items():
        theme = known_by_label[label]
        refs = sorted(set(theme.answer_refs or []) | set(new_rows))
        tone, sentiment = _aggregate_tone(refs, _scores_for(refs))
        theme.answer_refs = refs
        theme.size = len(refs)
        theme.tone = tone
        theme.sentiment = sentiment
        known_added += len(new_rows)

    column_row = db.scalar(select(Column).where(Column.dataset_id == dataset_id, Column.name == column))
    column_id = column_row.id if column_row else None
    new_themes_summary: list[dict] = []
    for label, new_rows in matched_new.items():
        if len(new_rows) < MIN_OTHER_NEW_THEME_SIZE:
            still_other.extend(new_rows)  # too small to count as its own theme - folds back into Other
            continue
        tone, sentiment = _aggregate_tone(new_rows, _scores_for(new_rows))
        db.add(Theme(
            dataset_id=dataset_id, column_id=column_id, column_name=column,
            label=label, description=new_label_descriptions[label], size=len(new_rows),
            sentiment=sentiment, tone=tone, answer_refs=sorted(new_rows), sub_themes=[],
        ))
        new_themes_summary.append({"label": label, "count": len(new_rows)})

    if still_other:
        tone, sentiment = _aggregate_tone(still_other, _scores_for(still_other))
        other.answer_refs = sorted(still_other)
        other.size = len(still_other)
        other.tone = tone
        other.sentiment = sentiment
    else:
        db.delete(other)

    db.commit()
    return {"known_added": known_added, "new_themes": new_themes_summary, "still_other_count": len(still_other)}


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


def _look_inside_other_error(e: BaseException) -> str | None:
    """Same shape as `_theme_build_error`, for the "Look inside Other" job. `JevError` here means the
    one-off question-building/consolidation step failed before any per-answer classification started
    (`classify_other_answers` itself never raises - a single row's `JevError` is caught per-row and
    recorded in `OtherClassification.failed_rows`, never fails the whole job)."""
    if isinstance(e, LabelingError):
        return f"Finding new themes failed: {e}"
    if isinstance(e, JevError):
        return f"Jev classification failed: {e}"
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
    # A cheap raw non-null count (not the real masked/cleaned answer count `embed_and_cluster_with_vectors`
    # computes later) is enough to size the watchdog - see `_themes_deadline_for`'s own comment for why a
    # flat 300s was confirmed live to kill a real, still-progressing large build.
    deadline = _themes_deadline_for(int(clean_df[column].notna().sum()))

    def _work(step: Callable[[str], None]) -> None:
        step("Turning answers into vectors")
        result, embedded = embed_and_cluster_with_vectors(clean_df, plan, column, embedding_client)
        step("Naming each group")
        labels = label_clusters_with_retry(result, question, claude_client)
        # Claude's reply already flags clusters it thinks are really the same theme (SYSTEM prompt, see
        # labeling.py) - apply_merges actually consolidates them (no new LLM call) before anything else
        # reads `result`/`labels`, so sub-clustering below splits each merged theme's full combined
        # membership, not just one pre-merge cluster's slice.
        result, labels = apply_merges(result, labels)
        step("Finding sub-themes")
        sub_clusters = sub_cluster_themes(result, embedded)
        step("Naming sub-themes")
        parent_labels = {
            cluster.id: label for cluster, label in zip(result.clusters, labels[: len(result.clusters)])
        }
        try:
            sub_labels = label_sub_clusters_with_retry(sub_clusters, parent_labels, question, claude_client)
        except LabelingError as e:
            # Sub-themes are an optional enhancement (plan decision 10): a broken/untrusted reply here must
            # not fail the whole theme build - log it and fall back to no sub-themes for every theme, not
            # a failed job. Any OTHER unexpected exception still propagates, same as everywhere else in
            # this pipeline.
            log.warning("sub-theme labeling failed for dataset %s column %r: %s", dataset_id_, column, e)
            sub_labels = {}
        sub_clusters, sub_labels = apply_sub_merges(sub_clusters, sub_labels)
        step("Scoring tone")
        if use_jev:
            scores = score_column_with_jev(clean_df, plan, column, jev_client)
        else:
            scores = score_column(clean_df, plan, column)
        with _db.SessionLocal() as job_db:
            _write_theme_rows(job_db, dataset_id_, column, result, labels, scores, sub_clusters, sub_labels)

    start_job(
        job, _SLOTS, _work, _theme_build_error,
        deadline_seconds=deadline,
        deadline_message=(
            f"Building themes took longer than {int(deadline)} seconds and did not finish "
            "in time. Try again, or with a smaller file."
        ),
    )

    return {"job_id": job.id, "status": "running"}


class LookInsideOtherRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = Field(max_length=255)


@router.post("/datasets/{dataset_id}/themes/look-inside-other", status_code=202)
def look_inside_other(
    dataset_id: int,
    body: LookInsideOtherRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
    claude_client: ClaudeClient = Depends(get_claude_client),
    jev_client: JevClient = Depends(get_jev_client),
):
    """"Look inside Other" (docs/TODO.md, 2026-10-21): re-clusters a column's "Other" answers, labels and
    consolidates what it finds against the column's own known themes, classifies every Other answer
    against the combined set via Jev, and updates `Theme` rows accordingly - see
    `app/text_pipeline/other_classify.py`'s own docstring for the full mechanism. Same
    validate-cheap-things-synchronously-then-run-in-a-background-job shape as `build_themes` above,
    sharing its `_SLOTS` concurrency pool (this is the same class of heavy embed+Claude+Jev work, not a
    separate budget)."""
    ds = _own_dataset(db, user, dataset_id)
    clean_df, plan = _load_clean_df(ds, db)
    column = body.column
    if column not in plan.columns:
        raise HTTPException(422, "Unknown column.")

    confirmed = (ds.profile or {}).get("confirmed") or {}
    question = (confirmed.get("question") or "").strip()
    if not question:
        question = ((ds.profile or {}).get("question") or {}).get("text") or column

    other = db.scalar(
        select(Theme).where(Theme.dataset_id == ds.id, Theme.column_name == column, Theme.label == "Other")
    )
    if other is None:
        raise HTTPException(
            409, 'There is no "Other" group for this column - build themes first, or everything already '
            "fits a known theme.",
        )
    if not other.answer_refs:
        raise HTTPException(409, '"Other" has no answers to look inside.')

    known_themes = {
        t.label: t.description
        for t in db.scalars(
            select(Theme).where(Theme.dataset_id == ds.id, Theme.column_name == column, Theme.label != "Other")
        ).all()
    }

    if not _SLOTS.acquire(blocking=False):
        raise HTTPException(429, "Theme building is busy with other jobs. Try again in a few seconds.")

    dataset_id_ = ds.id
    other_theme_id = other.id
    other_refs = list(other.answer_refs or [])
    job = create_job(db, dataset_id_, column, "look_inside_other")
    # Sized to Other's own answer count, not the whole dataset's - this job's real work (re-embed,
    # re-cluster, classify) only ever touches the Other-bucket rows, never the full column.
    deadline = _themes_deadline_for(len(other_refs))

    def _work(step: Callable[[str], None]) -> None:
        step("Checking known themes")
        other_refs_set = set(other_refs)
        masked = model_safe_column(clean_df, plan, column)
        row_text: dict[int, str] = {
            int(row_index): text
            for row_index, text in zip(clean_df.index, masked)
            if text and int(row_index) in other_refs_set
        }
        rows = [r for r in other_refs if r in row_text]
        texts = [row_text[r] for r in rows]
        vectors = embedding_client.embed(texts)
        reclustered = recluster_other(rows, texts, vectors)

        step("Grouping new themes into sub-themes")
        candidates = label_and_consolidate(reclustered, question, claude_client)
        criteria, new_label_descriptions = build_classification_question(known_themes, candidates)

        step("Finalizing")
        classification = classify_other_answers(rows, texts, criteria, jev_client)
        with _db.SessionLocal() as job_db:
            summary = _apply_other_classification(
                job_db, dataset_id_, column, other_theme_id,
                classification.by_row, new_label_descriptions, row_text,
            )
            # Written in the SAME session/commit as the Theme-row changes above, not via jobs.py's own
            # `_set_step`/`_mark_done` (those only ever touch a still-"running" job, guarding against a
            # watchdog that already failed it out from under this thread - writing `result` here, before
            # `start_job` below calls `_mark_done`, needs no such guard since the job is still genuinely
            # running at this point).
            if summary is not None:
                job_row = job_db.get(Job, job.id)
                if job_row is not None:
                    job_row.result = summary
                    job_db.commit()

    start_job(
        job, _SLOTS, _work, _look_inside_other_error,
        deadline_seconds=deadline,
        deadline_message=(
            f"Looking inside Other took longer than {int(deadline)} seconds and did not finish in time. "
            "Try again."
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


def _answers_page(
    ds: Dataset, db: Session, column: str | None, refs: list[int], limit: int, offset: int,
) -> tuple[int, int, list[dict]]:
    """Shared pagination/real-text lookup, extracted from what used to be `theme_answers`'s own inline
    body so `sub_theme_answers` below can reuse it against a sub-theme's own `answer_refs` instead of a
    parent `Theme` row's. Returns the clamped `(limit, offset, answers)` - same clamping/lookup behaviour
    as before this extraction, byte-identical for `theme_answers` itself."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    page = refs[offset: offset + limit]

    answers: list[dict] = []
    if page:
        # Real, unmasked cleaned text: the dataset's owner is looking at their own answers, not sending
        # them to a model - `model_safe_column` is deliberately NOT used here (see module docstring).
        clean_df, _plan = _load_clean_df(ds, db)
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

    return limit, offset, answers


@router.get("/datasets/{dataset_id}/themes/{theme_id}/answers")
def theme_answers(
    dataset_id: int, theme_id: int, limit: int = 20, offset: int = 0,
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    ds = _own_dataset(db, user, dataset_id)
    theme = db.get(Theme, theme_id)
    if theme is None or theme.dataset_id != ds.id:
        raise HTTPException(404, "Theme not found.")

    refs = theme.answer_refs or []
    limit, offset, answers = _answers_page(ds, db, theme.column_name, refs, limit, offset)
    return {"theme_id": theme.id, "total": len(refs), "limit": limit, "offset": offset, "answers": answers}


@router.get("/datasets/{dataset_id}/themes/{theme_id}/sub-themes/{index}/answers")
def sub_theme_answers(
    dataset_id: int, theme_id: int, index: int, limit: int = 20, offset: int = 0,
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    """Same ownership/pagination/real-text contract as `theme_answers` above, reused via `_answers_page`
    rather than duplicated - drill-down for one sub-theme's own answers (`Theme.sub_themes[index]`)."""
    ds = _own_dataset(db, user, dataset_id)
    theme = db.get(Theme, theme_id)
    if theme is None or theme.dataset_id != ds.id:
        raise HTTPException(404, "Theme not found.")

    subs = theme.sub_themes or []
    if index < 0 or index >= len(subs):
        raise HTTPException(404, "Sub-theme not found.")
    sub = subs[index]
    refs = sub.get("answer_refs") or []
    limit, offset, answers = _answers_page(ds, db, theme.column_name, refs, limit, offset)
    return {
        "theme_id": theme.id, "sub_theme_index": index, "total": len(refs),
        "limit": limit, "offset": offset, "answers": answers,
    }
