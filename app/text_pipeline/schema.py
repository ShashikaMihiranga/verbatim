"""Shapes shared by the embedding, clustering, pipeline and labeling modules, and by the sentiment and
cross-tabs work built on top of this one. Plain dataclasses, not pydantic: nothing here crosses an HTTP
boundary yet, so there is no schema to validate against.

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
class ThemeLabel:
    """Claude's read on one cluster (or the locally-synthesized "Other" group), plus the numbers our own
    code computed - never the model's. See `labeling.py:label_clusters`."""

    cluster_id: int  # matches Cluster.id for a real theme; -1 (labeling.OTHER_CLUSTER_ID) for "Other"
    label: str  # a few words, e.g. "Battery life complaints"
    description: str  # one plain-English sentence describing what the answers have in common
    size: int  # == len(cluster.members) (or len(result.noise) for "Other"); copied by our code, never asked of Claude
    merge_with: list[int]  # ids of other clusters Claude thinks are really the same theme as this one; [] if none
    note: str | None  # e.g. a flag that this cluster looks like two sub-themes and could be split; None if nothing to add


@dataclass
class AnswerScore:
    """One answer's lexicon sentiment score (`sentiment.py`). Independent of clustering/theming above -
    this scores individual answers, not groups - but shares the same masked-text input."""

    row: int  # original row index in the cleaned dataframe (never renumbered), same convention as ClusterMember.row
    text: str  # the masked answer text that was scored
    polarity: float  # lexicon score in [-1, 1]; negative = negative wording, positive = positive wording
    tone: Literal["neg", "neu", "pos"]  # bucketed from polarity by sentiment.py's thresholds
