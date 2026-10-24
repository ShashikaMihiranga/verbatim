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

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sklearn.decomposition import PCA
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db as _db
from .api_upload import _dataset_role, _own_dataset, current_user
from .chart_data import (
    BinnedGridData, CategoryAvgData, ContextData, FreqData, GroupTrendData, MapData, OverviewData,
    PhraseData, QualityData, QuoteData, ReportData, ScoreData, SegmentData, TrendData,
)
from .charts import TITLES, render_parts
from .cleaning import CleaningError, CleaningPlan, model_safe_column
from .db import get_db
from .findings import question_for, theme_nodes
from .jobs import REPORT_JOB_MAX_AGE, blocking_job, create_job, set_progress, start_job
from .models import CleanedFile, Column, Dataset, Job, Report, Theme, User
from .text_pipeline import (
    AnswerScore,
    AnthropicClaudeClient,
    ClaudeClient,
    Cluster,
    EmbeddedAnswers,
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
    sub_cluster_candidates,
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


def _cluster_centroid(cluster: Cluster, embedded: "EmbeddedAnswers | None") -> list[float] | None:
    """The real mean embedding vector of `cluster`'s own (post-merge) members - NOT `cluster.centroid`
    (`app.text_pipeline.schema.Cluster.centroid`), which HDBSCAN genuinely computes but
    `app.text_pipeline.merging.apply_merges` then unconditionally discards for EVERY cluster, merged or
    not (`_merge_one_level`'s own comment: "nothing downstream reads a Cluster's own centroid after
    labeling... recomputing it would buy nothing" - found live, 2026-10-24: that was true until this
    block needed one, so `_write_theme_rows` always received `centroid=None` and this map was always
    empty even on a real dataset with real themes). Recomputed here instead, from vectors
    `embed_and_cluster_with_vectors` already computed for clustering (`embedded`, kept alongside the
    `ClusterResult` precisely so a later pass can reuse them - see `EmbeddedAnswers`'s own docstring) -
    still zero extra embedding calls, just a local numpy mean over vectors already in memory, computed
    AFTER merging so it reflects the real, final theme membership."""
    if embedded is None:
        return None
    idxs = [embedded.position_by_row[m.row] for m in cluster.members if m.row in embedded.position_by_row]
    if not idxs:
        return None
    return list(np.asarray(embedded.vectors)[idxs].mean(axis=0))


def _pca_normalize_01(vectors: np.ndarray) -> np.ndarray:
    """Shared PCA-then-min-max-scale core behind `_project_centroids_2d` (per-theme) and
    `_sample_answer_positions` (per-answer, `answer_map` block) - pure local sklearn PCA, no network cost.
    Returns an (n, 2) array with both columns scaled to 0..1 over exactly the rows given (never a wider or
    narrower range - every caller already decides what set of vectors belongs in one shared scale before
    calling this)."""
    xy = PCA(n_components=2).fit_transform(vectors)
    x_lo, x_hi = xy[:, 0].min(), xy[:, 0].max()
    y_lo, y_hi = xy[:, 1].min(), xy[:, 1].max()
    x_span = (x_hi - x_lo) or 1.0
    y_span = (y_hi - y_lo) or 1.0
    xy[:, 0] = (xy[:, 0] - x_lo) / x_span
    xy[:, 1] = (xy[:, 1] - y_lo) / y_span
    return xy


# Cap on how many real answers get a stored position (chart-block stream, 2026-10-24, batch 4:
# answer_map) - a representative SAMPLE is enough to show a dataset's real cluster shape/separation
# honestly (the whole point of this block, "Charging answers form two separate clusters"); storing every
# row of a 40,000-row dataset would bloat `Column.answer_positions` and the report API response for no
# visual benefit (a dot map this size is already dense well before 3,000 points).
MAX_ANSWER_POSITIONS = 3000


def _sample_answer_positions(embedded: "EmbeddedAnswers | None", seed: int = 0) -> dict[int, tuple[float, float]]:
    """Real 2D positions for a bounded, reproducible (same `seed` - the dataset's own id, see the call
    site) sample of real answers, from the SAME embedding vectors already computed for clustering - no
    new embedding call. `{}` when there is nothing to sample (fewer than 2 embedded rows can't form a
    meaningful spread, same reasoning `_project_centroids_2d` already documents for themes)."""
    if embedded is None or len(embedded.row_indexes) < 2:
        return {}
    rng = np.random.default_rng(seed)
    if len(embedded.row_indexes) <= MAX_ANSWER_POSITIONS:
        sample_idx = np.arange(len(embedded.row_indexes))
    else:
        sample_idx = rng.choice(len(embedded.row_indexes), size=MAX_ANSWER_POSITIONS, replace=False)
    xy = _pca_normalize_01(np.asarray(embedded.vectors)[sample_idx])
    return {embedded.row_indexes[i]: (float(x), float(y)) for i, (x, y) in zip(sample_idx, xy)}


def _project_centroids_2d(centroids: list[list[float] | None]) -> list[tuple[float, float] | None]:
    """2D positions for the theme-similarity map (chart-block stream, 2026-10-24, batch 3 -
    `theme_similarity` block) from each real theme's own (post-merge) centroid - see `_cluster_centroid`
    for where `centroids` comes from and why it is not simply `[c.centroid for c in result.clusters]`.
    Pure local PCA via sklearn, which this app already depends on for HDBSCAN itself - no network cost.

    `None` entries (a cluster whose centroid could not be recomputed - `_cluster_centroid` returns `None`
    when no member row has a matching embedding vector) pass straight through as `None`, at the same
    position in the returned list - never dropped, never given an invented centroid, so the caller can zip
    this 1:1 against its own cluster list.

    Normalized to 0..1 on each axis (matching `ThemeNode.map_xy`'s own documented range) by min-max scaling
    over only the REAL centroids - never by the dropped `None` ones. Fewer than 2 real centroids can't form
    a meaningful 2D spread (PCA needs at least 2 points, and 1 point has no "relative to each other"
    position worth plotting), so every entry stays `None` in that case - an honest gap, not a fabricated
    single dot in the middle of the chart."""
    real = [(i, c) for i, c in enumerate(centroids) if c is not None]
    out: list[tuple[float, float] | None] = [None] * len(centroids)
    if len(real) < 2:
        return out
    idxs, vectors = zip(*real)
    xy = _pca_normalize_01(np.array(vectors))
    for i, (x, y) in zip(idxs, xy):
        out[i] = (float(x), float(y))
    return out


def _write_theme_rows(
    db: Session, dataset_id: int, column: str, result, labels, scores,
    sub_clusters: dict[int, list[Cluster]] | None = None,
    sub_labels: dict[int, list[ThemeLabel]] | None = None,
    embedded: "EmbeddedAnswers | None" = None,
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
    unconditionally (sub-clustering never touches noise/"Other" - see subthemes.py), gets `[]`.

    `embedded` (chart-block stream, 2026-10-24, batch 3) is the `EmbeddedAnswers` `embed_and_cluster_with_vectors`
    already produced, optionally passed through so `map_x`/`map_y` can be computed from each theme's real
    (post-merge) member vectors - see `_cluster_centroid`. `None` (the default) leaves every theme's
    `map_x`/`map_y` at their honest `None` default, same as a caller that never passes it (e.g. tests)."""
    scores_by_row = {s.row: s for s in scores if s is not None}

    # `label_clusters` returns one entry per `result.clusters` (same order), plus at most one extra
    # "Other" entry appended at the end iff `result.noise` is non-empty - see its docstring.
    real_labels = labels[: len(result.clusters)]
    other_labels = labels[len(result.clusters):]

    column_row = db.scalar(select(Column).where(Column.dataset_id == dataset_id, Column.name == column))
    column_id = column_row.id if column_row else None

    # chart-block stream, 2026-10-24, batch 3 (theme_similarity): one real 2D position per REAL theme
    # (never "Other" - noise has no single centroid), recomputed from each theme's own real post-merge
    # member vectors - see _cluster_centroid's own docstring for why this is NOT cluster.centroid.
    positions = _project_centroids_2d([_cluster_centroid(c, embedded) for c in result.clusters])

    new_rows: list[Theme] = []
    for cluster, label, pos in zip(result.clusters, real_labels, positions):
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
            map_x=pos[0] if pos else None, map_y=pos[1] if pos else None,
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
    # New themes make every stored finding sentence describe themes that no longer exist (found live on
    # dataset 12: five findings about deleted themes all fell back to the same chart). Same policy as
    # rename/merge/split: drop the report so the page offers "Build report" again.
    _invalidate_report_for_edit(db, dataset_id, column)
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
    *,
    vec_by_row: dict[int, list[float]] | None = None,
    question: str | None = None, claude_client: ClaudeClient | None = None,
    failed_count: int = 0,
    low_confidence_count: int = 0,
    non_answer_count: int = 0,
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

    `vec_by_row`/`question`/`claude_client` (Stage 3a, docs/TODO.md 2026-10-23) are all optional -
    `None` (the default, every call site/test before this stage) skips sub-clustering entirely, leaving
    every new theme's `sub_themes` at `[]` exactly as before. When given, each surviving new theme with
    enough answers gets the SAME sub-clustering pass a normal top-level theme would
    (`other_classify.sub_cluster_candidates`, reusing the vectors already in memory from this job's own
    re-embed step - no second Voyage call), labeled with one extra batched Claude call covering every
    eligible new theme at once (`label_sub_clusters_with_retry`, same "one call for everything, not one
    per theme" discipline `label_clusters_with_retry` already uses) - never a build-failing error: a
    `LabelingError` here just means no new theme gets sub-themes this run, same graceful fallback
    `app/api_themes.py`'s own top-level build already uses for the identical failure.

    `failed_count` (fixed 2026-10-23, found live on a 19,799-row Other bucket where every single Jev call
    failed on a rejected API key): `len(OtherClassification.failed_rows)` from the caller's own
    `classify_other_answers` run - surfaced in the summary so a systemic failure (every row failed) is
    visible in the job's own result instead of looking identical to a legitimate "nothing matched"
    outcome. A failed row already stays in Other either way (see this docstring's own note above) -
    this only changes what gets REPORTED, never what gets written.

    `low_confidence_count` (BUG-032) and `non_answer_count` (BUG-048) are reported the same way: rows the
    caller already left out of `by_row` or set to `NONE_OF_THESE`, so they stay in Other here.

    Returns a small summary dict (Stage 3, docs/TODO.md 2026-10-21/23: the animated flow's own
    Known/New/Still-in-Other results panel and its own result-chart tabs need these real numbers, not a
    second query reconstructing them after the fact) - `{"known_added": int, "new_themes": [{"label",
    "count", "sentiment", "tone"}], "still_other_count": int, "failed_classification_count": int}` - or
    `None` if `other` was already gone (nothing to summarize)."""
    other = db.get(Theme, other_theme_id)
    if other is None:
        return None  # dataset/column was deleted or rebuilt from under this job; nothing left to update

    known_by_label = {
        t.label: t
        for t in db.scalars(
            select(Theme).where(Theme.dataset_id == dataset_id, Theme.column_name == column, Theme.id != other_theme_id)
        ).all()
    }
    # Captured before anything moves: the report's Inside Other panel shows "It was y% before this run",
    # and every share it prints uses the column's answered total as its denominator.
    other_before_count = len(other.answer_refs or [])
    answered_total = sum(t.size for t in known_by_label.values()) + (other.size or 0)

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
    new_theme_objects: list[Theme] = []
    surviving_new: dict[str, list[int]] = {}
    new_theme_tone_sentiment: dict[str, tuple[dict, float]] = {}
    for label, new_rows in matched_new.items():
        if len(new_rows) < MIN_OTHER_NEW_THEME_SIZE:
            still_other.extend(new_rows)  # too small to count as its own theme - folds back into Other
            continue
        tone, sentiment = _aggregate_tone(new_rows, _scores_for(new_rows))
        theme = Theme(
            dataset_id=dataset_id, column_id=column_id, column_name=column,
            label=label, description=new_label_descriptions[label], size=len(new_rows),
            sentiment=sentiment, tone=tone, answer_refs=sorted(new_rows), sub_themes=[],
        )
        db.add(theme)
        new_theme_objects.append(theme)
        surviving_new[label] = new_rows
        new_theme_tone_sentiment[label] = (tone, sentiment)

    # Sub-clustering (Stage 3a, docs/TODO.md 2026-10-23) - see this function's own docstring for the
    # optional-params contract. Skips cleanly (no new theme gets sub_themes) on anything short of a
    # full "vectors + Claude client supplied, and at least one new theme survived" - never fails the
    # whole job over an Icicle-chart nicety.
    if vec_by_row is not None and claude_client is not None and surviving_new:
        rows_by_parent = {i: rows for i, rows in enumerate(surviving_new.values())}
        sub_clusters = sub_cluster_candidates(rows_by_parent, vec_by_row, row_text)
        if sub_clusters:
            parent_labels = {
                i: ThemeLabel(
                    cluster_id=i, label=lbl, description=new_label_descriptions[lbl],
                    size=len(rows), merge_with=[], note=None,
                )
                for i, (lbl, rows) in enumerate(surviving_new.items())
            }
            try:
                sub_labels_by_parent = label_sub_clusters_with_retry(
                    sub_clusters, parent_labels, question or "", claude_client,
                )
                sub_clusters, sub_labels_by_parent = apply_sub_merges(sub_clusters, sub_labels_by_parent)
            except LabelingError as e:
                log.warning(
                    "sub-theme labeling failed for dataset %s column %r (Look inside Other): %s",
                    dataset_id, column, e,
                )
                sub_labels_by_parent = {}
            for i, theme in enumerate(new_theme_objects):
                clusters = sub_clusters.get(i)
                sub_labels = sub_labels_by_parent.get(i)
                if not clusters or not sub_labels:
                    continue
                sub_themes_json: list[dict] = []
                for sc, sl in zip(clusters, sub_labels):
                    sub_rows = [m.row for m in sc.members]
                    sub_tone, sub_sentiment = _aggregate_tone(sub_rows, _scores_for(sub_rows))
                    sub_themes_json.append({
                        "label": sl.label, "description": sl.description, "size": sl.size,
                        "sentiment": sub_sentiment, "tone": sub_tone, "answer_refs": sub_rows,
                    })
                theme.sub_themes = sub_themes_json

    new_themes_summary: list[dict] = [
        {
            "label": label, "count": len(rows),
            "sentiment": new_theme_tone_sentiment[label][1], "tone": new_theme_tone_sentiment[label][0],
        }
        for label, rows in surviving_new.items()
    ]

    if still_other:
        tone, sentiment = _aggregate_tone(still_other, _scores_for(still_other))
        other.answer_refs = sorted(still_other)
        other.size = len(still_other)
        other.tone = tone
        other.sentiment = sentiment
    else:
        db.delete(other)

    db.commit()
    return {
        "known_added": known_added, "new_themes": new_themes_summary, "still_other_count": len(still_other),
        "failed_classification_count": failed_count,
        "low_confidence_count": low_confidence_count, "non_answer_count": non_answer_count,
        "other_before_count": other_before_count, "answered_total": answered_total,
        "known_gains": [{"label": label, "count": len(rows)}
                        for label, rows in sorted(matched_known.items(), key=lambda kv: -len(kv[1]))],
    }


# One question per chart (docs/REPORT_UI_REWORK.md): only the icicle ("what's inside the new themes"), and
# only when a new theme has sub-themes. The panel draws "which new themes are biggest and how they sound"
# itself from `new_themes[].tone`: the server rank chart compared tone against a placeholder 0.00 average
# here. "othergrowth" was a bar chart shown under a "Sankey" label; "sentsun" repeated the same tone.
_OTHER_RESULT_CHART_IDS = ("icicle",)


def _build_other_result_charts(theme_rows: list[Theme]) -> dict[str, dict]:
    """Stage 3a (docs/TODO.md, 2026-10-23): the "Look inside Other" job's own result-chart tabs - a
    SEPARATE mini chart set from the main report's, scoped to just the newly-discovered themes from one
    run, not the dataset's top-level known themes. Same "build a minimal ReportData for one chart" trick
    `themes_chart` above already uses for the Themes screen's own one-chart view - reuses `f_rank`/
    `f_icicle`/`f_sentsun` completely unchanged (3 of 4 real tabs need no new renderer at all), plus the
    one genuinely new renderer this stage adds, `f_other_growth` (chart id `"othergrowth"`). No Arc tab
    here: the mockup's Arc view needs the exact multi-label co-occurrence signal already confirmed
    impossible for the main report's own Arc tab (Stage 2) - every answer belongs to exactly one theme by
    construction (now including Jev's own classification step), so there is no real arc data a new chart
    could show; the frontend's own tab bar shows an explanatory message for that tab instead of calling
    this function's output. Returns `{}` if `theme_rows` is empty (nothing to chart)."""
    if not theme_rows:
        return {}
    total = sum(t.size for t in theme_rows)
    nodes = theme_nodes(theme_rows, total)
    placeholder_theme = nodes[0].name if nodes else ""
    data = ReportData(
        question="", total=total, answered=total, overall_sentiment=0.0, themes=nodes,
        selected_theme=placeholder_theme, hover_theme=placeholder_theme,
        overview=OverviewData(stats=[], insights=[]),
        score=ScoreData(name="", bands=[]),
        segment=SegmentData(name="", groups=[], rows=[]),
        trend=TrendData(labels=[], series=[], sentiment=[], hover_index=0, note=""),
        group_trend=GroupTrendData(group_column="", labels=[], series=[], note=""),
        binned_grid=BinnedGridData(row_name="", col_name="", row_labels=[], col_labels=[], cells=[]),
        cooccurrence=[],
        answer_map=MapData(seed=0, tip_text="", tip_note=""),
        frequency=FreqData(question="", answered=0, items=[], highlight="", footnote=""),
        category_avg=CategoryAvgData(category_name="", number_name="", overall_avg=0.0, items=[]),
        phrases=PhraseData(phrases=[], highlight=""),
        quotes=QuoteData(quotes=[], highlight_index=0),
        quality=QualityData(bins=[], typical_bin="", typical_note="", notes=[]),
        context=ContextData(kind="", kind_options=[], kind_hover="", framing="", length="", columns_note=""),
    )
    charts: dict[str, dict] = {}
    for chart_id in _OTHER_RESULT_CHART_IDS:
        if chart_id == "icicle" and not any(n.children for n in nodes):
            continue  # no new theme has sub-themes: an icicle would only repeat the rank chart
        chart_html, chart_width, chart_height = render_parts(chart_id, data)
        charts[chart_id] = {
            "chart_title": TITLES.get(chart_id, chart_id),
            "chart_html": chart_html, "chart_width": chart_width, "chart_height": chart_height,
        }
    return charts


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


def _all_rows_failed_message(n: int, sample_error: str | None) -> str:
    """Why a Look inside run checked nothing, in words the report page can show as-is."""
    reason = (sample_error or "no reason given").removeprefix("JevError: ").rstrip(".")
    hint = ""
    if "HTTP 402" in reason:
        hint = " (payment required: check the Jev account's credit)"
    elif "HTTP 401" in reason or "HTTP 403" in reason:
        hint = " (check the Jev API key)"
    return (f"none of the {n:,} answers in Other could be checked, so nothing was changed. "
            f"{reason}{hint}.")


def _look_inside_other_error(e: BaseException) -> str | None:
    """Same shape as `_theme_build_error`, for the "Look inside Other" job. `JevError` here means the
    one-off question-building/consolidation step failed before any per-answer classification started
    (`classify_other_answers` itself never raises - a single row's `JevError` is caught per-row and
    recorded in `OtherClassification.failed_rows`; only when EVERY row fails does `_work` raise a
    `JevError` itself, with `_all_rows_failed_message`)."""
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
    ds = _own_dataset(db, user, dataset_id, min_role="editor")
    clean_df, plan = _load_clean_df(ds, db)
    column = body.column
    if column not in plan.columns:
        raise HTTPException(422, "Unknown column.")
    _refuse_while_report_builds(db, ds.id, column)

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
            _write_theme_rows(job_db, dataset_id_, column, result, labels, scores, sub_clusters, sub_labels, embedded)
            # chart-block stream, 2026-10-24, batch 4 (answer_map): a real per-answer position sample,
            # stored on this dataset+column's own Column row - independent of theme assignment (see
            # Column.answer_positions' own docstring for why it lives here, not on Theme).
            positions = _sample_answer_positions(embedded, seed=dataset_id_)
            col_row = job_db.scalar(select(Column).where(Column.dataset_id == dataset_id_, Column.name == column))
            if col_row is not None:
                col_row.answer_positions = {str(r): list(xy) for r, xy in positions.items()}
                job_db.commit()

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
    ds = _own_dataset(db, user, dataset_id, min_role="editor")
    clean_df, plan = _load_clean_df(ds, db)
    column = body.column
    if column not in plan.columns:
        raise HTTPException(422, "Unknown column.")
    _refuse_while_report_builds(db, ds.id, column)

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
        step("Finding patterns in Other")
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

        step("Naming new themes")
        candidates = label_and_consolidate(reclustered, question, claude_client, for_other=True)
        criteria, new_label_descriptions = build_classification_question(known_themes, candidates)
        # Non-answers ("no comment", "n/a") never go to Jev: missing from `by_row`, they stay in Other
        # (BUG-048), and cannot be pulled into a known theme either.
        non_answer_rows = set(candidates.non_answer_rows)
        classify_rows = [r for r in rows if r not in non_answer_rows]
        classify_texts = [row_text[r] for r in classify_rows]

        step("Matching answers to themes")

        def _progress(done: int, total: int, by_row: dict[int, str], failed: list[int]) -> None:
            # Live counts for the report's Inside Other panel. Small new groups can still fold back into
            # Other at the end (MIN_OTHER_NEW_THEME_SIZE), so the finished result is the final word.
            known: dict[str, int] = {}
            new: dict[str, int] = {}
            still = len(failed)
            for choice in by_row.values():
                if choice in known_themes:
                    known[choice] = known.get(choice, 0) + 1
                elif choice in new_label_descriptions:
                    new[choice] = new.get(choice, 0) + 1
                else:
                    still += 1
            set_progress(job.id, {"done": done, "total": total, "known": known, "new": new, "still_other": still})

        classification = classify_other_answers(
            classify_rows, classify_texts, criteria, jev_client, on_progress=_progress,
        )
        if classify_rows and len(classification.failed_rows) == len(classify_rows):
            # Every call failed: a systemic problem (key, credit, outage), not "nothing matched". Fail the
            # job before anything is applied, with the real reason (docs/BUGS.md BUG-040).
            raise JevError(_all_rows_failed_message(len(classify_rows), classification.sample_error))
        step("Updating the report")
        vec_by_row = dict(zip(rows, vectors))
        with _db.SessionLocal() as job_db:
            summary = _apply_other_classification(
                job_db, dataset_id_, column, other_theme_id,
                classification.by_row, new_label_descriptions, row_text,
                vec_by_row=vec_by_row, question=question, claude_client=claude_client,
                failed_count=len(classification.failed_rows),
                low_confidence_count=len(classification.low_confidence_rows),
                non_answer_count=len(non_answer_rows),
            )
            # Result-chart fragments (Stage 3a, docs/TODO.md 2026-10-23): built in the SAME session,
            # right after the new Theme rows exist with real ids - re-queries by label rather than
            # threading ORM objects out of `_apply_other_classification` (that function already commits
            # internally, and a fresh `select` is simpler/safer than trusting objects across a commit).
            if summary is not None and summary["new_themes"]:
                new_labels = [nt["label"] for nt in summary["new_themes"]]
                new_theme_rows = list(job_db.scalars(
                    select(Theme).where(
                        Theme.dataset_id == dataset_id_, Theme.column_name == column, Theme.label.in_(new_labels),
                    )
                ).all())
                summary["charts"] = _build_other_result_charts(new_theme_rows)
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


def _refuse_while_report_builds(db: Session, dataset_id: int, column: str) -> None:
    """409 while a report job for this column is running: changing themes under it would leave the new
    report describing themes that no longer exist."""
    if blocking_job(db, dataset_id, column, ("report",), REPORT_JOB_MAX_AGE) is not None:
        raise HTTPException(409, "A report is being built for this column. Try again when it finishes.")


def _invalidate_report_for_edit(db: Session, dataset_id: int, column: str) -> None:
    """Theme editing (docs/TODO.md, fixed 2026-10-22: rename/merge/split). A rename/merge/split changes
    what a theme IS, which makes every stored `Finding.sentence` for this column (plain-English prose
    written about the theme's OLD shape) stale - deletes the dataset+column's `Report` row outright,
    rather than trying to patch individual `Finding` rows (which would still need a real Claude call to
    write a correct replacement sentence anyway). This is the SAME "no report built yet" state `GET
    /report` already handles gracefully (`app/api_report.py::get_report`'s own 404), so the owner just
    re-clicks the existing "Build report"/"Rebuild report" button to get fresh, correct findings - no new
    rebuild-trigger plumbing needed. Mirrors `app/api_report.py::_latest_report_for_column`'s own
    "match by stored content.column" lookup (not imported from there - that module imports FROM this one,
    so importing back would be circular)."""
    for report in db.scalars(select(Report).where(Report.dataset_id == dataset_id)).all():
        if isinstance(report.content, dict) and report.content.get("column") == column:
            db.delete(report)


class RenameThemeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=2000)


@router.patch("/datasets/{dataset_id}/themes/{theme_id}")
def rename_theme(
    dataset_id: int, theme_id: int, body: RenameThemeRequest,
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    """Theme editing (docs/TODO.md, fixed 2026-10-22): the trivial case - updates `label`/`description`
    on one stored `Theme` row in place, same "load the affected row(s) by id, mutate, commit" shape
    `_apply_other_classification` already established, not `_write_theme_rows`'s full delete-and-
    replace. Synchronous (no background job): nothing here re-embeds or re-clusters anything."""
    ds = _own_dataset(db, user, dataset_id, min_role="editor")
    theme = db.get(Theme, theme_id)
    if theme is None or theme.dataset_id != ds.id:
        raise HTTPException(404, "Theme not found.")
    _refuse_while_report_builds(db, ds.id, theme.column_name)

    theme.label = body.label.strip()
    if body.description is not None:
        theme.description = body.description.strip() or None
    _invalidate_report_for_edit(db, ds.id, theme.column_name)
    db.commit()

    total = sum(t.size for t in _stored_themes(db, ds.id, theme.column_name))
    return _theme_dict(theme, total)


class MergeThemesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    column: str = Field(max_length=255)
    theme_ids: list[int] = Field(min_length=2, max_length=20)
    label: str | None = Field(default=None, max_length=255)


@router.post("/datasets/{dataset_id}/themes/merge")
def merge_themes(
    dataset_id: int, body: MergeThemesRequest,
    db: Session = Depends(get_db), user: User = Depends(current_user),
):
    """Theme editing (docs/TODO.md, fixed 2026-10-22): unions `answer_refs` across the given `Theme`
    rows into the largest one (the same "largest wins" survivor convention
    `app/text_pipeline/merging.py::_merge_one_level` already uses for the pipeline's own automatic
    same-label merging - not that function's own entry point, which operates on `Cluster`/`ThemeLabel`
    objects that only exist transiently during a build, never on live ORM rows), recomputes `tone`/
    `sentiment` from scratch via `score_text` over the real cleaned text (no network - the owner's own
    text, same `_load_clean_df` access `_write_theme_rows` already uses, not masked: nothing here
    crosses to an external model), and deletes the absorbed rows (cascading any `Finding.theme_id`
    pointing at one to `NULL` - handled by `_invalidate_report_for_edit` below regardless)."""
    ds = _own_dataset(db, user, dataset_id, min_role="editor")
    _refuse_while_report_builds(db, ds.id, body.column)
    rows = list(db.scalars(
        select(Theme).where(
            Theme.dataset_id == ds.id, Theme.column_name == body.column, Theme.id.in_(body.theme_ids),
        )
    ).all())
    found_ids = {t.id for t in rows}
    missing = sorted(set(body.theme_ids) - found_ids)
    if missing:
        raise HTTPException(404, f"Theme id(s) not found: {missing}")
    if len(rows) < 2:
        raise HTTPException(422, "Merging needs at least 2 distinct themes.")

    clean_df, _plan = _load_clean_df(ds, db)
    survivor = max(rows, key=lambda t: t.size)
    label = (body.label or "").strip() or survivor.label

    refs = sorted({r for t in rows for r in (t.answer_refs or [])})
    scores: dict[int, AnswerScore] = {}
    for r in refs:
        try:
            text = clean_df.at[r, body.column]
        except KeyError:
            continue
        if not isinstance(text, str) or not text:
            continue
        polarity, tone = score_text(text)
        scores[r] = AnswerScore(row=r, text=text, polarity=polarity, tone=tone)
    tone, sentiment = _aggregate_tone(refs, scores)

    survivor.label = label
    survivor.answer_refs = refs
    survivor.size = len(refs)
    survivor.tone = tone
    survivor.sentiment = sentiment
    for t in rows:
        if t.id != survivor.id:
            db.delete(t)

    _invalidate_report_for_edit(db, ds.id, body.column)
    db.commit()

    total = sum(t.size for t in _stored_themes(db, ds.id, body.column))
    return _theme_dict(survivor, total)


def _split_theme_error(e: BaseException) -> str | None:
    """Same shape as `_look_inside_other_error` - the split job's only real-network step is the one
    batched Claude labeling call (`label_and_consolidate`); re-embedding is Voyage, not Claude/Jev, and
    `EmbeddingNotConfigured`/network errors there are unanticipated (no masking-boundary issue specific
    to splitting an existing theme), so they fall through to the generic `job.error` message."""
    if isinstance(e, LabelingError):
        return f"Finding new themes failed: {e}"
    return None


def _apply_theme_split(
    db: Session, dataset_id: int, column: str, theme_id: int,
    candidates: "ConsolidatedCandidates", row_text: dict[int, str],
) -> dict | None:
    """Theme editing (docs/TODO.md, fixed 2026-10-22): split - writes `label_and_consolidate`'s output as
    new `Theme` rows, same "load the affected row(s), mutate/add, commit" shape `_apply_other_classification`
    already established. Unlike that function, there is no Jev classification step here (nothing to match
    a leftover remainder against known themes) - a piece too small to count as its own theme
    (`MIN_OTHER_NEW_THEME_SIZE`, reused rather than a second magic number) and `label_and_consolidate`'s own
    dropped noise both fold back into the ORIGINAL theme's shrunk `answer_refs`, not a classification
    target. The original is deleted outright only if nothing remains (mirrors `_apply_other_classification`'s
    own "delete rather than keep a zero-size row" rule) - in practice a genuine split almost always leaves
    SOME remainder (the merged-cluster noise), so this is the less common path here than in that function.

    Returns `{"new_themes": [{"label","count"}], "remainder_count": int}`, or `None` if the original
    theme was already gone (dataset/column deleted or rebuilt from under this job)."""
    original = db.get(Theme, theme_id)
    if original is None:
        return None

    column_row = db.scalar(select(Column).where(Column.dataset_id == dataset_id, Column.name == column))
    column_id = column_row.id if column_row else None

    def _scores_for(rows) -> dict[int, AnswerScore]:
        out: dict[int, AnswerScore] = {}
        for row in rows:
            text = row_text.get(row)
            if text is None:
                continue
            polarity, tone = score_text(text)
            out[row] = AnswerScore(row=row, text=text, polarity=polarity, tone=tone)
        return out

    # Starts from EVERY row this split actually considered (`row_text`'s own keys - the real, non-blank
    # answers the job embedded/reclustered), not `candidates.result.noise`. A real bug found via live
    # browser verification, not assumed away: `label_and_consolidate` has its own early-return for "every
    # cluster got labeled Other" that discards `result.noise`/`result.clusters` entirely (returns `[]` for
    # both, by design - see that function's own docstring), which used to leave `remainder` empty in that
    # case - with no new themes created either, the whole original theme (and every one of its real
    # answers) was silently deleted outright, with the job still reporting "done", not "failed". Starting
    # from the full row set and only REMOVING rows once they positively land in a new theme makes every
    # row accounted for by construction, the same safety shape `_apply_other_classification` already uses
    # (default to staying put, never silently dropped).
    remainder: set[int] = set(row_text.keys())
    cluster_by_id = {c.id: c for c in candidates.result.clusters}
    new_themes_summary: list[dict] = []
    for label in candidates.labels:
        cluster = cluster_by_id.get(label.cluster_id)
        if cluster is None:
            continue
        rows = [m.row for m in cluster.members]
        if len(rows) < MIN_OTHER_NEW_THEME_SIZE:
            continue  # too small to count as its own theme - stays in remainder (already there by default)
        tone, sentiment = _aggregate_tone(rows, _scores_for(rows))
        db.add(Theme(
            dataset_id=dataset_id, column_id=column_id, column_name=column,
            label=label.label, description=label.description, size=len(rows),
            sentiment=sentiment, tone=tone, answer_refs=sorted(rows), sub_themes=[],
        ))
        new_themes_summary.append({"label": label.label, "count": len(rows)})
        remainder.difference_update(rows)  # these rows are now accounted for by their new theme

    if remainder:
        remainder_rows = sorted(remainder)
        tone, sentiment = _aggregate_tone(remainder_rows, _scores_for(remainder_rows))
        original.answer_refs = remainder_rows
        original.size = len(remainder_rows)
        original.tone = tone
        original.sentiment = sentiment
    else:
        db.delete(original)

    _invalidate_report_for_edit(db, dataset_id, column)
    db.commit()
    return {"new_themes": new_themes_summary, "remainder_count": len(remainder)}


@router.post("/datasets/{dataset_id}/themes/{theme_id}/split", status_code=202)
def split_theme(
    dataset_id: int, theme_id: int,
    db: Session = Depends(get_db), user: User = Depends(current_user),
    embedding_client: EmbeddingClient = Depends(get_embedding_client),
    claude_client: ClaudeClient = Depends(get_claude_client),
):
    """Theme editing (docs/TODO.md, fixed 2026-10-22): the big case - re-embeds and re-clusters ONE
    theme's own `answer_refs`, same technique "Look inside Other" already uses
    (`other_classify.recluster_other`/`label_and_consolidate`, completely unchanged - this reuses them
    directly rather than `subthemes.sub_cluster_themes`, which needs vectors already in memory from a
    just-finished build; `Theme` rows never persist embedding vectors, so a split triggered days later
    has no vectors to slice and must re-embed, exactly like "Look inside Other" does for the Other
    bucket). A background job (`app/jobs.py`, like that feature) since re-embedding/re-clustering/
    labeling is real, possibly-slow work - unlike rename/merge above, which are synchronous."""
    ds = _own_dataset(db, user, dataset_id, min_role="editor")
    theme = db.get(Theme, theme_id)
    if theme is None or theme.dataset_id != ds.id:
        raise HTTPException(404, "Theme not found.")
    _refuse_while_report_builds(db, ds.id, theme.column_name)
    column = theme.column_name
    if not column:
        raise HTTPException(409, "This theme has no column recorded; cannot split it.")
    refs = list(theme.answer_refs or [])
    if len(refs) < 2 * MIN_OTHER_NEW_THEME_SIZE:
        raise HTTPException(
            409, f"Need at least {2 * MIN_OTHER_NEW_THEME_SIZE} answers to split this theme into real pieces.",
        )

    clean_df, plan = _load_clean_df(ds, db)
    confirmed = (ds.profile or {}).get("confirmed") or {}
    question = (confirmed.get("question") or "").strip()
    if not question:
        question = ((ds.profile or {}).get("question") or {}).get("text") or column

    if not _SLOTS.acquire(blocking=False):
        raise HTTPException(429, "Theme building is busy with other jobs. Try again in a few seconds.")

    dataset_id_ = ds.id
    theme_id_ = theme.id
    job = create_job(db, dataset_id_, column, "split_theme")
    deadline = _themes_deadline_for(len(refs))

    def _work(step: Callable[[str], None]) -> None:
        step("Re-embedding this theme's answers")
        refs_set = set(refs)
        masked = model_safe_column(clean_df, plan, column)
        row_text: dict[int, str] = {
            int(row_index): text
            for row_index, text in zip(clean_df.index, masked)
            if text and int(row_index) in refs_set
        }
        rows = [r for r in refs if r in row_text]
        texts = [row_text[r] for r in rows]
        vectors = embedding_client.embed(texts)
        reclustered = recluster_other(rows, texts, vectors)

        step("Naming the pieces")
        candidates = label_and_consolidate(reclustered, question, claude_client)

        step("Finalizing")
        with _db.SessionLocal() as job_db:
            summary = _apply_theme_split(job_db, dataset_id_, column, theme_id_, candidates, row_text)
            if summary is not None:
                job_row = job_db.get(Job, job.id)
                if job_row is not None:
                    job_row.result = summary
                    job_db.commit()

    start_job(
        job, _SLOTS, _work, _split_theme_error,
        deadline_seconds=deadline,
        deadline_message=(
            f"Splitting this theme took longer than {int(deadline)} seconds and did not finish in time. "
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
        group_trend=GroupTrendData(group_column="", labels=[], series=[], note=""),
        binned_grid=BinnedGridData(row_name="", col_name="", row_labels=[], col_labels=[], cells=[]),
        cooccurrence=[],
        answer_map=MapData(seed=0, tip_text="", tip_note=""),
        frequency=FreqData(question="", answered=0, items=[], highlight="", footnote=""),
        category_avg=CategoryAvgData(category_name="", number_name="", overall_avg=0.0, items=[]),
        phrases=PhraseData(phrases=[], highlight=""),
        quotes=QuoteData(quotes=[], highlight_index=0),
        quality=QualityData(bins=[], typical_bin="", typical_note="", notes=[]),
        context=ContextData(kind="", kind_options=[], kind_hover="", framing="", length="", columns_note=""),
    )
    chart_html, chart_width, chart_height = render_parts("treemap", data)
    return {"chart_html": chart_html, "chart_width": chart_width, "chart_height": chart_height}


def _answers_page(
    ds: Dataset, db: Session, column: str | None, refs: list[int], limit: int, offset: int,
    *, hide_text: bool = False,
) -> tuple[int, int, list[dict]]:
    """Shared pagination/real-text lookup, extracted from what used to be `theme_answers`'s own inline
    body so `sub_theme_answers` below can reuse it against a sub-theme's own `answer_refs` instead of a
    parent `Theme` row's. Returns the clamped `(limit, offset, answers)` - same clamping/lookup behaviour
    as before this extraction, byte-identical for `theme_answers` itself when `hide_text` is left at its
    default `False` (every caller before sharing/roles existed).

    `hide_text` (sharing/roles, fixed 2026-10-22): `True` for a "viewer"-role caller - `text` comes back
    `None` instead of the real verbatim ("hide verbatims for external audiences", SPEC.md section 5).
    This is NOT the same mechanism as `model_safe_column`'s masking (that redacts PII for a MODEL prompt,
    still showing the owner real surrounding text); a viewer gets no verbatim text at all, full stop -
    the real text is still read server-side (needed for `tone`, computed locally, no network) but never
    serialized back to a viewer-role caller."""
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
            answers.append({"row": int(row), "text": None if hide_text else raw, "tone": tone})

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
    hide_text = _dataset_role(db, user, ds) == "viewer"
    limit, offset, answers = _answers_page(ds, db, theme.column_name, refs, limit, offset, hide_text=hide_text)
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
    hide_text = _dataset_role(db, user, ds) == "viewer"
    limit, offset, answers = _answers_page(ds, db, theme.column_name, refs, limit, offset, hide_text=hide_text)
    return {
        "theme_id": theme.id, "sub_theme_index": index, "total": len(refs),
        "limit": limit, "offset": offset, "answers": answers,
    }
