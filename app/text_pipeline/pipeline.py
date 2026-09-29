"""Wires the cleaned dataframe to an embedding client to a clustering call for one column.

`app.cleaning.payload.model_safe_column` is the only door text leaves through on the way here; this
module never touches `clean_df[column]` directly.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..cleaning.models import CleaningPlan
from ..cleaning.payload import model_safe_column
from .clustering import cluster_answers
from .embeddings import EmbeddingClient
from .schema import ClusterResult

MIN_ANSWERS_TO_CLUSTER = 20  # below this, HDBSCAN cannot find anything meaningful; show a message, not a crash


class TooFewAnswers(RuntimeError):
    """A column has too few non-empty answers to cluster meaningfully. Callers should show something
    like "too few answers for themes" and skip the theme view for this column, not treat this as a bug."""


@dataclass
class EmbeddedAnswers:
    """The embedding vectors `embed_and_cluster_with_vectors` computed, kept alongside the
    `ClusterResult` so a later sub-clustering pass (see `subthemes.py`) can reuse them instead of
    paying to re-embed the same answers. `row_indexes`/`vectors` are the same length and order as what
    went into the `cluster_answers` call that produced the paired `ClusterResult` (original dataframe
    row indexes, never renumbered - same convention as `ClusterMember.row`)."""

    row_indexes: list[int]  # same order as vectors, matches ClusterResult member rows
    vectors: np.ndarray  # float32, shape (n, dims)
    position_by_row: dict[int, int]  # row -> index into vectors/row_indexes, for O(1) subset lookups later


def embed_and_cluster_with_vectors(
    clean_df: pd.DataFrame,
    plan: CleaningPlan,
    column: str,
    client: EmbeddingClient,
    min_cluster_size: int | None = None,
) -> tuple[ClusterResult, EmbeddedAnswers]:
    """Embed and cluster every non-empty answer in `column`, same as `embed_and_cluster`, but also
    returns the embedding vectors alongside the `ClusterResult` (as `EmbeddedAnswers`) instead of
    discarding them - see that dataclass's docstring for why.

    Steps: mask every row of `column` through `model_safe_column` (so this never sees an un-redacted
    answer), drop rows that are blank/NaN (keeping their *original* row index out of the result rather
    than renumbering what is left), embed the remaining texts with `client` (which does its own
    batching - see `embeddings.VoyageEmbeddingClient`), then cluster the vectors with `cluster_answers`.

    Raises `TooFewAnswers` (not a generic crash) when there are under `MIN_ANSWERS_TO_CLUSTER` non-empty
    answers. `plan.columns[column]`'s refusal rules (sensitive / non-text) are enforced by
    `model_safe_column` itself and surface as `CleaningError`.
    """
    masked = model_safe_column(clean_df, plan, column)  # same order as clean_df.index; None for blank/NaN

    row_indexes: list[int] = []
    texts: list[str] = []
    for row_index, text in zip(clean_df.index, masked):
        if text:  # None (no value) and "" (masked down to nothing) both mean "no answer"
            row_indexes.append(int(row_index))
            texts.append(text)

    if len(texts) < MIN_ANSWERS_TO_CLUSTER:
        raise TooFewAnswers(
            f"'{column}' has only {len(texts)} non-empty answer(s); at least {MIN_ANSWERS_TO_CLUSTER} "
            "are needed to find themes."
        )

    raw_vectors = client.embed(texts)
    vectors = np.asarray(raw_vectors, dtype="float32")
    result = cluster_answers(raw_vectors, texts, row_indexes, min_cluster_size=min_cluster_size)
    result.column = column

    embedded = EmbeddedAnswers(
        row_indexes=row_indexes,
        vectors=vectors,
        position_by_row={row: i for i, row in enumerate(row_indexes)},
    )
    return result, embedded


def embed_and_cluster(
    clean_df: pd.DataFrame,
    plan: CleaningPlan,
    column: str,
    client: EmbeddingClient,
    min_cluster_size: int | None = None,
) -> ClusterResult:
    """Embed and cluster every non-empty answer in `column`.

    Steps: mask every row of `column` through `model_safe_column` (so this never sees an un-redacted
    answer), drop rows that are blank/NaN (keeping their *original* row index out of the result rather
    than renumbering what is left), embed the remaining texts with `client` (which does its own
    batching - see `embeddings.VoyageEmbeddingClient`), then cluster the vectors with `cluster_answers`.

    Raises `TooFewAnswers` (not a generic crash) when there are under `MIN_ANSWERS_TO_CLUSTER` non-empty
    answers. `plan.columns[column]`'s refusal rules (sensitive / non-text) are enforced by
    `model_safe_column` itself and surface as `CleaningError`.

    A thin wrapper around `embed_and_cluster_with_vectors` that discards the embedding vectors -
    kept so every existing caller's signature/behavior stays unchanged.
    """
    return embed_and_cluster_with_vectors(clean_df, plan, column, client, min_cluster_size=min_cluster_size)[0]
