"""Group answer vectors into themes with HDBSCAN. No LLM here (SPEC.md section 2: "Free once vectors
exist") - labelling the resulting groups with Claude is the next agent's job, working from `ClusterResult`.

Dimensionality reduction before clustering (2026-09-27, see docs/DECISIONS.md for the full story): HDBSCAN
is a density-based algorithm, and density-based clustering degrades badly on raw high-dimensional vectors -
in enough dimensions, distances between points concentrate (everything ends up roughly, uselessly
equidistant from everything else), so HDBSCAN can no longer tell a genuinely dense region from background
noise. Voyage's `voyage-3.5` embeddings are 1024-dimensional. Run straight through HDBSCAN with no
reduction (this module's original design, tested only against `FakeEmbeddingClient`'s 32-dimensional fake
vectors), a real 23,486-row product-review dataset put 22,641 of 23,486 answers (96%) into noise -
essentially no themes found at all, despite the data being genuinely, naturally clusterable and the
embeddings themselves being fine (the same run's sentiment scoring, which does not depend on clustering,
produced a believable 74% positive). This was invisible in this project's own tests because every existing
fixture is low-dimensional; it only showed up the first time real, high-dimensional embeddings went through
the pipeline. The fix, standard practice in text-clustering tools that use HDBSCAN this way (BERTopic,
Top2Vec): reduce to a modest number of dimensions with UMAP first, and cluster the reduced vectors, never
the raw ones. `_reduce_for_clustering` below does this, skipping itself (falling back to clustering the
original vectors exactly as before) when there are too few answers or the input is already low-dimensional
enough that the problem above does not apply - see its docstring for the exact thresholds and why.
"""
from __future__ import annotations

import numpy as np
import umap
from sklearn.cluster import HDBSCAN

from .schema import Cluster, ClusterMember, ClusterResult

MIN_MIN_CLUSTER_SIZE = 5  # never require fewer than this many answers to call something a theme
MAX_MIN_CLUSTER_SIZE = 50  # never require more than this even for a huge dataset, or themes get too coarse
ADAPTIVE_DIVISOR = 50  # roughly one theme-worth of answers per 50 answers total; see docs/DECISIONS.md

# HDBSCAN's own default sets `min_samples` to `min_cluster_size`, which is unusually strict: it makes the
# "how dense must a region be to not be noise" test just as demanding as the "how big must a group be to
# report as a theme" test, and the two are answering different questions. Decoupling them (with a smaller,
# adaptive `min_samples`) is the standard tuning move for this over-aggressive-noise symptom - see
# docs/DECISIONS.md for the reasoning and the real-dataset numbers that motivated it.
MIN_SAMPLES_FLOOR = 3  # below this, HDBSCAN gets too permissive (near single-linkage, noisy micro-clusters)
MIN_SAMPLES_CEILING = 10  # above this we are back to tracking min_cluster_size's own strictness
MIN_SAMPLES_DIVISOR = 3

# Reduction is skipped below either threshold - see `_reduce_for_clustering`'s docstring for the reasoning.
MIN_ANSWERS_FOR_REDUCTION = 50
MIN_DIMENSIONS_FOR_REDUCTION = 50

# Target dimensionality after reduction: 5 is the common default in this space (BERTopic and Top2Vec both
# default to 5), 15 a common practical ceiling (past it, UMAP's own reduction starts giving back some of the
# high-dimensional sparsity it was meant to remove). Growing mildly with answer count follows this module's
# existing "adaptive, not one fixed constant" philosophy (see `adaptive_min_cluster_size`): more answers give
# UMAP more to work with, so a slightly richer reduced space can still be trusted with enough data.
REDUCED_DIMENSIONS_FLOOR = 5
REDUCED_DIMENSIONS_CEILING = 15
REDUCED_DIMENSIONS_DIVISOR = 300

UMAP_N_NEIGHBORS = 15  # UMAP's own well-tested default
UMAP_MIN_DIST = 0.0  # UMAP's own documented recommendation when the output feeds a clustering step, not a plot
UMAP_RANDOM_STATE = 42  # fixed seed: keeps this module's "deterministic given the same input" claim true


def adaptive_min_cluster_size(n_answers: int) -> int:
    """Pick `min_cluster_size` from the answer count instead of one fixed constant (PROJECT_VISION.md's
    "clean adaptively" principle applies just as much to clustering as to the cleaning steps).

    Formula: round(n_answers / 50), clamped to [5, 50]. 50 answers or fewer -> the floor of 5 (a theme
    needs at least a handful of answers to mean anything). 2500 or more -> the ceiling of 50 (past that,
    bigger minimums would swallow real sub-themes into noise or into each other).
    """
    return max(MIN_MIN_CLUSTER_SIZE, min(MAX_MIN_CLUSTER_SIZE, round(n_answers / ADAPTIVE_DIVISOR)))


def adaptive_min_samples(min_cluster_size: int) -> int:
    """Pick HDBSCAN's `min_samples` from `min_cluster_size` rather than letting it default to
    `min_cluster_size` one-for-one (see the module-level comment above `MIN_SAMPLES_FLOOR`).

    Formula: round(min_cluster_size / 3), clamped to [3, 10]. At the smallest `min_cluster_size` (5) this
    floors at 3; at the largest (50) it ceilings at 10 - always well below `min_cluster_size` itself, so
    HDBSCAN is more willing to call a region "dense enough" than it is to call a group "big enough to be a
    theme". Those are deliberately different bars.
    """
    return max(MIN_SAMPLES_FLOOR, min(MIN_SAMPLES_CEILING, round(min_cluster_size / MIN_SAMPLES_DIVISOR)))


def adaptive_n_components(n_answers: int) -> int:
    """Pick UMAP's target dimensionality from the answer count instead of one fixed constant, same spirit
    as `adaptive_min_cluster_size`.

    Formula: round(n_answers / 300), clamped to [5, 15]. Only ever called once `n_answers` has already
    cleared `MIN_ANSWERS_FOR_REDUCTION`, so the floor of 5 is the common case for modest datasets; the
    ceiling of 15 caps out around a few thousand answers and up (the real 23,486-row dataset that exposed
    this bug would land here, at the ceiling).
    """
    return max(REDUCED_DIMENSIONS_FLOOR, min(REDUCED_DIMENSIONS_CEILING, round(n_answers / REDUCED_DIMENSIONS_DIVISOR)))


def _euclidean(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _reduce_for_clustering(vectors: list[list[float]]) -> list[list[float]]:
    """Reduce `vectors` to a modest number of dimensions with UMAP before HDBSCAN sees them - see this
    module's docstring for why raw high-dimensional vectors defeat HDBSCAN.

    Skips itself (returns `vectors` unchanged) below either of two thresholds, so small and/or already
    low-dimensional inputs cluster exactly as this module always has:

    - Fewer than `MIN_ANSWERS_FOR_REDUCTION` (50) answers: UMAP needs enough points to build a meaningful
      local-neighbourhood graph. Its own neighbour count defaults to `UMAP_N_NEIGHBORS` (15); a widely used
      rule of thumb is to have at least three to four times that many points before trusting the result, and
      50 sits just above that band. This also comfortably covers every existing small-fixture test in
      tests/test_text_pipeline.py (63 answers is the largest), so those keep clustering exactly as before -
      not because the threshold was tuned to dodge them, but because a few dozen answers is genuinely too
      few for UMAP's neighbour graph to be trustworthy either way.
    - Fewer than `MIN_DIMENSIONS_FOR_REDUCTION` (50) raw dimensions: the failure this reduction step fixes
      (distance concentration in high-dimensional space) is a high-dimensionality problem specifically. Real
      Voyage embeddings are 1024-dimensional; `FakeEmbeddingClient`'s test vectors default to 32. 50 sits
      between those two, so low-dimensional inputs (including every existing test fixture) are recognised as
      not needing the fix that exists for a different, higher-dimensional problem.

    `metric="cosine"` because these are normalised text-embedding vectors (Euclidean is UMAP's default, and
    is the wrong metric for direction-encoded, unit-length vectors like these). `min_dist=0.0` because UMAP's
    own guidance is to pack points as tightly as the manifold allows when the output feeds a clustering step
    (as opposed to a 2D plot, where a larger `min_dist` avoids an unreadable solid blob).
    `random_state=UMAP_RANDOM_STATE` is fixed so the same input always reduces to the same output - the
    reason this module can still claim to be deterministic given the same input (see `cluster_answers`'s
    docstring). A fixed `random_state` also forces UMAP to run single-threaded (its own documented
    trade-off: parallelism is not reproducible), which is slower but is the correct trade for this module's
    determinism guarantee.
    """
    n = len(vectors)
    dims = len(vectors[0]) if vectors else 0
    if n < MIN_ANSWERS_FOR_REDUCTION or dims < MIN_DIMENSIONS_FOR_REDUCTION:
        return vectors

    n_components = adaptive_n_components(n)
    n_neighbors = min(UMAP_N_NEIGHBORS, n - 1)
    reducer = umap.UMAP(
        n_components=n_components,
        n_neighbors=n_neighbors,
        min_dist=UMAP_MIN_DIST,
        metric="cosine",
        random_state=UMAP_RANDOM_STATE,
    )
    reduced = reducer.fit_transform(np.asarray(vectors, dtype=float))
    return reduced.tolist()


def cluster_answers(
    vectors: list[list[float]],
    texts: list[str],
    row_indexes: list[int],
    min_cluster_size: int | None = None,
) -> ClusterResult:
    """Cluster `vectors` (one per answer, same order as `texts` and `row_indexes`) into themes.

    `row_indexes[i]` is the original dataframe row that `texts[i]` / `vectors[i]` came from; it is carried
    through untouched so callers can map a cluster back to real rows even though blank/skipped rows were
    never included here (see `pipeline.embed_and_cluster`).

    Before HDBSCAN runs, `vectors` are passed through `_reduce_for_clustering`, which reduces them to a
    modest number of dimensions with UMAP (skipping itself for small and/or already low-dimensional inputs -
    see that function's docstring). HDBSCAN then clusters on the reduced vectors, not the raw ones; cluster
    centroids and each member's `distance` are computed in that same reduced space, so they stay consistent
    with what HDBSCAN actually saw. Whenever reduction actually runs, `min_samples` is also set from
    `min_cluster_size` via `adaptive_min_samples` rather than left at HDBSCAN's own default (which ties it
    to `min_cluster_size` one-for-one - unusually strict; see the module-level comment above
    `MIN_SAMPLES_FLOOR`). When reduction is skipped (small and/or low-dimensional input), `min_samples`
    stays at HDBSCAN's own original default too, so small inputs cluster exactly as this module always has.

    HDBSCAN labels answers it cannot confidently place as noise (label -1); those become `ClusterResult.noise`,
    never dropped. A cluster HDBSCAN does find that is smaller than `min_cluster_size` (this can happen because
    HDBSCAN's own `min_cluster_size` only bounds the search, not every accepted cluster after `cluster_selection_method`
    trades off stability) is folded into noise too, rather than reported as a one- or two-answer "theme".

    Deterministic given the same input: HDBSCAN itself has no `random_state` to set (it is a density-based
    algorithm with no random initialisation, unlike e.g. k-means). The UMAP reduction step this module now
    runs first does have a random component (its optimisation is stochastic), but `_reduce_for_clustering`
    fixes `random_state=UMAP_RANDOM_STATE`, so the same vectors always reduce to the same reduced vectors,
    and therefore HDBSCAN always produces the same labels - the same guarantee as before, now resting on a
    fixed seed instead of "nothing to seed".
    """
    n = len(vectors)
    if not (len(texts) == len(row_indexes) == n):
        raise ValueError("vectors, texts and row_indexes must be the same length.")
    if min_cluster_size is None:
        min_cluster_size = adaptive_min_cluster_size(n)
    min_cluster_size = max(2, min_cluster_size)  # HDBSCAN itself requires at least 2

    if n == 0:
        return ClusterResult(column="", clusters=[], noise=[], total_answers=0)

    clustering_vectors = _reduce_for_clustering(vectors)
    reduction_applied = clustering_vectors is not vectors
    # The `min_samples` tuning below (see `adaptive_min_samples`) is the fix for a symptom that only shows
    # up in the same real-world scenario the reduction step fixes - real, high-dimensional embeddings at a
    # meaningful scale. Tying it to whether reduction actually ran keeps small/low-dimensional inputs
    # (every existing small-fixture test) clustering with HDBSCAN's own original default (`min_samples ==
    # min_cluster_size`), unchanged from this module's behaviour before this fix.
    min_samples = adaptive_min_samples(min_cluster_size) if reduction_applied else min_cluster_size

    model = HDBSCAN(min_cluster_size=min_cluster_size, min_samples=min_samples, store_centers="centroid", copy=True)
    labels = model.fit_predict(clustering_vectors)
    centroids = getattr(model, "centroids_", None)  # one row per non-noise label, in label order

    groups: dict[int, list[int]] = {}
    for i, label in enumerate(labels):
        groups.setdefault(int(label), []).append(i)
    noise_positions = list(groups.pop(-1, []))

    clusters: list[Cluster] = []
    for label, positions in groups.items():
        centroid = list(centroids[label]) if centroids is not None else None
        if len(positions) < min_cluster_size:
            # HDBSCAN itself found this group too small to trust; treat it as noise rather than a theme.
            noise_positions.extend(positions)
            continue
        cluster_members = []
        for i in positions:
            distance = _euclidean(clustering_vectors[i], centroid) if centroid is not None else None
            cluster_members.append(ClusterMember(row=row_indexes[i], text=texts[i], distance=distance))
        clusters.append(Cluster(id=-1, members=cluster_members, centroid=centroid))

    clusters.sort(key=lambda c: len(c.members), reverse=True)
    for new_id, cluster in enumerate(clusters):
        cluster.id = new_id

    noise = [ClusterMember(row=row_indexes[i], text=texts[i], distance=None) for i in sorted(noise_positions)]

    return ClusterResult(column="", clusters=clusters, noise=noise, total_answers=n)
