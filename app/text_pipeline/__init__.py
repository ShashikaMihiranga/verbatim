"""Stream 6: turn cleaned open-ended answers into themes, by embedding then clustering.

Data flow (SPEC.md section 2): `app.cleaning.payload.model_safe_column` is the only door text leaves
through; `embeddings.EmbeddingClient` turns masked text into vectors; `clustering.cluster_answers` groups
vectors with no LLM involved; `pipeline.embed_and_cluster` wires the two together for a single column.
Labelling clusters with Claude, sentiment, and cross-tabs are the next agents' job, built on `ClusterResult`
(`schema.py`).
"""
from .schema import Cluster, ClusterMember, ClusterResult
from .embeddings import EmbeddingClient, EmbeddingNotConfigured, FakeEmbeddingClient, VoyageEmbeddingClient
from .clustering import adaptive_min_cluster_size, cluster_answers
from .pipeline import TooFewAnswers, embed_and_cluster

__all__ = [
    "Cluster", "ClusterMember", "ClusterResult",
    "EmbeddingClient", "EmbeddingNotConfigured", "FakeEmbeddingClient", "VoyageEmbeddingClient",
    "adaptive_min_cluster_size", "cluster_answers",
    "TooFewAnswers", "embed_and_cluster",
]
