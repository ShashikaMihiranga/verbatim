"""Stream 6: turn cleaned open-ended answers into themes (embed + cluster) and into per-answer sentiment.

Data flow (SPEC.md section 2): `app.cleaning.payload.model_safe_column` is the only door text leaves
through; `embeddings.EmbeddingClient` turns masked text into vectors; `clustering.cluster_answers` groups
vectors with no LLM involved; `pipeline.embed_and_cluster` wires the two together for a single column.
`sentiment.py` scores individual answers with a lexicon (no LLM) and offers an optional Claude spot-check
for scorer agreement; it runs independently of clustering but shares the same masked-text input.
Labelling clusters with Claude and cross-tabs are the next agents' job, built on `ClusterResult`
(`schema.py`).
"""
from .schema import AnswerScore, Cluster, ClusterMember, ClusterResult
from .embeddings import EmbeddingClient, EmbeddingNotConfigured, FakeEmbeddingClient, VoyageEmbeddingClient
from .clustering import adaptive_min_cluster_size, cluster_answers
from .pipeline import TooFewAnswers, embed_and_cluster
from .sentiment import (
    ClaudeNotConfigured,
    FakeClaudeClient,
    SpotCheckParseError,
    SpotCheckReport,
    score_column,
    score_text,
    spot_check,
    tone_split,
)

__all__ = [
    "AnswerScore", "Cluster", "ClusterMember", "ClusterResult",
    "EmbeddingClient", "EmbeddingNotConfigured", "FakeEmbeddingClient", "VoyageEmbeddingClient",
    "adaptive_min_cluster_size", "cluster_answers",
    "TooFewAnswers", "embed_and_cluster",
    "ClaudeNotConfigured", "FakeClaudeClient", "SpotCheckParseError", "SpotCheckReport",
    "score_column", "score_text", "spot_check", "tone_split",
]
