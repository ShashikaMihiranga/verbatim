"""Shapes shared by the embedding, clustering and pipeline modules, and by the two agents that build on
top of this one (labelling with Claude, sentiment, cross-tabs). Plain dataclasses, not pydantic: nothing
here crosses an HTTP boundary yet, so there is no schema to validate against.

A plain `list[float]` is used for a vector; a dedicated `EmbeddingVector` type would add nothing but a
name (SPEC.md's "don't over-engineer").
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass
class ClusterMember:
    row: int  # original row index in the cleaned dataframe (never renumbered)
    text: str  # the masked answer text that was embedded
    distance: float | None  # euclidean distance from this answer's vector to its cluster's centroid; None for noise


@dataclass
class Cluster:
    id: int  # 0-based, stable for a given run; not the same as HDBSCAN's raw label after noise/tiny-cluster merges
    members: list[ClusterMember]  # every answer assigned to this cluster, confidently
    centroid: list[float] | None  # mean vector of the cluster's members; None if it could not be computed


@dataclass
class ClusterResult:
    column: str  # the column name these answers came from
    clusters: list[Cluster]  # the confident groups, largest first
    noise: list[ClusterMember]  # answers HDBSCAN could not confidently place (label -1); becomes "Other" later, never dropped
    total_answers: int  # non-empty answers that went into clustering (== sum of cluster sizes + len(noise))


@dataclass
class AnswerScore:
    """One answer's lexicon sentiment score (`sentiment.py`). Independent of clustering/theming above -
    this scores individual answers, not groups - but shares the same masked-text input."""

    row: int  # original row index in the cleaned dataframe (never renumbered), same convention as ClusterMember.row
    text: str  # the masked answer text that was scored
    polarity: float  # lexicon score in [-1, 1]; negative = negative wording, positive = positive wording
    tone: Literal["neg", "neu", "pos"]  # bucketed from polarity by sentiment.py's thresholds
