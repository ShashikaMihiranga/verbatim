"""Group answer vectors into themes with HDBSCAN. No LLM here (SPEC.md section 2: "Free once vectors
exist") - labelling the resulting groups with Claude is the next agent's job, working from `ClusterResult`.
"""
from __future__ import annotations

from sklearn.cluster import HDBSCAN

from .schema import Cluster, ClusterMember, ClusterResult

MIN_MIN_CLUSTER_SIZE = 5  # never require fewer than this many answers to call something a theme
MAX_MIN_CLUSTER_SIZE = 50  # never require more than this even for a huge dataset, or themes get too coarse
ADAPTIVE_DIVISOR = 50  # roughly one theme-worth of answers per 50 answers total; see docs/DECISIONS.md


def adaptive_min_cluster_size(n_answers: int) -> int:
    """Pick `min_cluster_size` from the answer count instead of one fixed constant (PROJECT_VISION.md's
    "clean adaptively" principle applies just as much to clustering as to the cleaning steps).

    Formula: round(n_answers / 50), clamped to [5, 50]. 50 answers or fewer -> the floor of 5 (a theme
    needs at least a handful of answers to mean anything). 2500 or more -> the ceiling of 50 (past that,
    bigger minimums would swallow real sub-themes into noise or into each other).
    """
    return max(MIN_MIN_CLUSTER_SIZE, min(MAX_MIN_CLUSTER_SIZE, round(n_answers / ADAPTIVE_DIVISOR)))


def _euclidean(a: list[float], b: list[float]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


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

    HDBSCAN labels answers it cannot confidently place as noise (label -1); those become `ClusterResult.noise`,
    never dropped. A cluster HDBSCAN does find that is smaller than `min_cluster_size` (this can happen because
    HDBSCAN's own `min_cluster_size` only bounds the search, not every accepted cluster after `cluster_selection_method`
    trades off stability) is folded into noise too, rather than reported as a one- or two-answer "theme".

    Deterministic given the same input: HDBSCAN here has no `random_state` to set (it is a density-based
    algorithm with no random initialisation, unlike e.g. k-means), so the same vectors always produce the
    same labels.
    """
    n = len(vectors)
    if not (len(texts) == len(row_indexes) == n):
        raise ValueError("vectors, texts and row_indexes must be the same length.")
    if min_cluster_size is None:
        min_cluster_size = adaptive_min_cluster_size(n)
    min_cluster_size = max(2, min_cluster_size)  # HDBSCAN itself requires at least 2

    if n == 0:
        return ClusterResult(column="", clusters=[], noise=[], total_answers=0)

    model = HDBSCAN(min_cluster_size=min_cluster_size, store_centers="centroid", copy=True)
    labels = model.fit_predict(vectors)
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
            distance = _euclidean(vectors[i], centroid) if centroid is not None else None
            cluster_members.append(ClusterMember(row=row_indexes[i], text=texts[i], distance=distance))
        clusters.append(Cluster(id=-1, members=cluster_members, centroid=centroid))

    clusters.sort(key=lambda c: len(c.members), reverse=True)
    for new_id, cluster in enumerate(clusters):
        cluster.id = new_id

    noise = [ClusterMember(row=row_indexes[i], text=texts[i], distance=None) for i in sorted(noise_positions)]

    return ClusterResult(column="", clusters=clusters, noise=noise, total_answers=n)
