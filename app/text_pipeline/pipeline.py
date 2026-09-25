"""Wires the cleaned dataframe to an embedding client to a clustering call for one column.

`app.cleaning.payload.model_safe_column` is the only door text leaves through on the way here; this
module never touches `clean_df[column]` directly.
"""
from __future__ import annotations

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

    vectors = client.embed(texts)
    result = cluster_answers(vectors, texts, row_indexes, min_cluster_size=min_cluster_size)
    result.column = column
    return result
