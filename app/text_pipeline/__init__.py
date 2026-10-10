"""Stream 6: turn cleaned open-ended answers into themes (embed + cluster + label) and into per-answer
sentiment.

Data flow (SPEC.md section 2): `app.cleaning.payload.model_safe_column` is the only door text leaves
through; `embeddings.EmbeddingClient` turns masked text into vectors; `clustering.cluster_answers` groups
vectors with no LLM involved; `pipeline.embed_and_cluster` wires the two together for a single column;
`labeling.label_clusters` names the resulting groups with one batched Claude call, built on
`ClusterResult` (`schema.py`). `sentiment.py` scores individual answers with a lexicon (no LLM) and offers
an optional Claude spot-check for scorer agreement; it runs independently of clustering but shares the
same masked-text input. `jev_sentiment.py` adds a second, OPT-IN way to score sentiment - Jev, a model
from TypeSafe AI - reached only via `sentiment.score_column_with_jev`; nothing else in the app calls it.
Cross-tabs and the findings engine are the next stream's job.

Known duplication (built by two agents in parallel, merged 2026-09-25): `labeling.py` and `sentiment.py`
each define their own `ClaudeNotConfigured` exception and `FakeClaudeClient` test double, both mirroring
`embeddings.EmbeddingNotConfigured`'s pattern independently. They are DIFFERENT classes despite the same
name - `except text_pipeline.LabelingClaudeNotConfigured` will not catch a `SentimentClaudeNotConfigured`,
or vice versa. Re-exported below under distinct names rather than letting one silently shadow the other.
A future pass should consolidate into one shared Claude-client abstraction, the same way `embeddings.py`
already gives both consumers a single `EmbeddingClient`.
"""
from .schema import AnswerScore, Cluster, ClusterMember, ClusterResult, ThemeLabel
from .embeddings import EmbeddingClient, EmbeddingNotConfigured, FakeEmbeddingClient, VoyageEmbeddingClient
from .clustering import adaptive_min_cluster_size, adaptive_min_samples, adaptive_n_components, cluster_answers
from .pipeline import EmbeddedAnswers, TooFewAnswers, embed_and_cluster, embed_and_cluster_with_vectors
from .labeling import (
    AnthropicClaudeClient,
    ClaudeClient,
    DEFAULT_SAMPLES_PER_SUBCLUSTER,
    LabelingError,
    SUB_SYSTEM,
    label_clusters,
    label_clusters_with_retry,
    label_sub_clusters,
    label_sub_clusters_with_retry,
)
from .labeling import ClaudeNotConfigured as LabelingClaudeNotConfigured
from .labeling import FakeClaudeClient as FakeLabelingClaudeClient
from .sentiment import (
    SpotCheckParseError,
    SpotCheckReport,
    score_column,
    score_column_with_jev,
    score_text,
    spot_check,
    tone_split,
)
from .sentiment import ClaudeNotConfigured as SentimentClaudeNotConfigured
from .sentiment import FakeClaudeClient as FakeSentimentClaudeClient
from .jev_sentiment import (
    FakeJevClient,
    HttpJevClient,
    JevClient,
    JevError,
    JevNotConfigured,
)

__all__ = [
    "AnswerScore", "Cluster", "ClusterMember", "ClusterResult", "ThemeLabel",
    "EmbeddingClient", "EmbeddingNotConfigured", "FakeEmbeddingClient", "VoyageEmbeddingClient",
    "adaptive_min_cluster_size", "adaptive_min_samples", "adaptive_n_components", "cluster_answers",
    "EmbeddedAnswers", "TooFewAnswers", "embed_and_cluster", "embed_and_cluster_with_vectors",
    "AnthropicClaudeClient", "ClaudeClient", "DEFAULT_SAMPLES_PER_SUBCLUSTER", "LabelingError",
    "SUB_SYSTEM", "label_clusters", "label_clusters_with_retry", "label_sub_clusters",
    "label_sub_clusters_with_retry",
    "LabelingClaudeNotConfigured", "FakeLabelingClaudeClient",
    "SpotCheckParseError", "SpotCheckReport", "score_column", "score_text", "spot_check", "tone_split",
    "SentimentClaudeNotConfigured", "FakeSentimentClaudeClient",
    "score_column_with_jev", "FakeJevClient", "HttpJevClient", "JevClient", "JevError", "JevNotConfigured",
]
