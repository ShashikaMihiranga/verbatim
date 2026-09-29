"""Second, nested clustering pass within each theme's own answers - a sub-theme pass. Pure logic, no
Claude/LLM calls (those live in `labeling.py:label_sub_clusters`); this module only decides WHICH
clusters get split and what their sub-clusters are, deterministically, given a `ClusterResult` and the
`EmbeddedAnswers` (see `pipeline.py`) already paid for while building it.

See the plan's "Design decisions" 2-7 for the reasoning behind every constant and rule below; the short
version: never touch noise/"Other" (decision 2), only the biggest, most-populated themes are worth a
second pass (decisions 3-4), size the sub-clusters relative to their OWN parent rather than the
whole-dataset formula (decision 5), and only keep a parent's sub-themes if enough of them survive and
they cover enough of the parent to not visually mislead a treemap block (decisions 6-7).
"""
from __future__ import annotations

import numpy as np

from .clustering import MIN_MIN_CLUSTER_SIZE, cluster_answers
from .pipeline import EmbeddedAnswers
from .schema import Cluster, ClusterResult

MIN_THEME_SIZE_FOR_SUBTHEMES = 100  # a theme needs at least this many answers before a sub-pass is attempted -
    # comfortably above MIN_ANSWERS_FOR_REDUCTION=50 (clustering.py), so UMAP reduction always runs for an
    # eligible theme and the sub-pass never hits the raw-high-dimensional-HDBSCAN "96% noise" failure mode
    # documented in clustering.py's own module docstring / docs/DECISIONS.md's 2026-09-27 entry.
MAX_THEMES_TO_SPLIT = 7      # matches app/charts.py's t1..t7 palette - a theme ranked 8th+ already gets merged
    # into one "Other" rectangle by treemap_rows() and its sub-themes could never be drawn regardless.
MAX_SUBTHEMES_PER_THEME = 3  # app/charts.py's MIX = [46, 36, 27] is a hardcoded 3-element list; a 4th
    # sub-theme raises IndexError there - this module never emits more than 3, by construction.
MIN_SUBTHEME_SHARE_OF_PARENT = 0.10  # a sub-theme must hold at least 10% of its parent's own answers
MIN_SUBTHEME_COVERAGE = 0.50         # a parent's sub-themes are stored only if the surviving ones
    # together cover at least half its answers - otherwise a treemap block would visually imply "this
    # theme = these 1-2 small sub-themes" when they're actually a sliver of it (squarify scales sub-rects
    # to fill the WHOLE parent rectangle regardless of true coverage).


def sub_cluster_min_size(n_parent: int) -> int:
    """max(5, round(n_parent * MIN_SUBTHEME_SHARE_OF_PARENT)) - MIN_MIN_CLUSTER_SIZE (5) is clustering.py's
    own floor, reused here rather than a second magic number."""
    return max(MIN_MIN_CLUSTER_SIZE, round(n_parent * MIN_SUBTHEME_SHARE_OF_PARENT))


def eligible_parents(result: ClusterResult) -> list[Cluster]:
    """The top MAX_THEMES_TO_SPLIT real clusters (result.clusters is already sorted largest-first) whose
    len(members) >= MIN_THEME_SIZE_FOR_SUBTHEMES. Never includes noise (result.noise / "Other" is a
    separate list entirely, never touched by this function) - see the plan's decision 2."""
    top = result.clusters[:MAX_THEMES_TO_SPLIT]
    return [cluster for cluster in top if len(cluster.members) >= MIN_THEME_SIZE_FOR_SUBTHEMES]


def sub_cluster_themes(
    result: ClusterResult, embedded: EmbeddedAnswers,
) -> dict[int, list[Cluster]]:
    """For each cluster in eligible_parents(result): slice `embedded.vectors`/row_indexes/texts down to
    just that parent cluster's own member rows (using `embedded.position_by_row` for the lookup, and
    preserving the parent's own `cluster.members` order when slicing - UMAP has a fixed random_state=42,
    so stable input order matters for reproducibility), then run a fresh `cluster_answers` call on just
    that slice with `min_cluster_size=sub_cluster_min_size(len(cluster.members))`.

    Keeps only the MAX_SUBTHEMES_PER_THEME largest resulting sub-clusters (already sorted largest-first
    by cluster_answers itself). A parent's entry is stored in the returned dict only if at least 2
    sub-clusters survive AND together they cover at least MIN_SUBTHEME_COVERAGE of the parent's own
    answers; otherwise the parent's id is omitted from the dict entirely (not an empty list).

    Sub-cluster ids in each returned list are whatever cluster_answers assigned them locally (0-based
    per that inner call, NOT globally unique across parents - combining multiple parents' results into
    one labeling batch is labeling.py:label_sub_clusters's job, not this function's).
    """
    out: dict[int, list[Cluster]] = {}
    for parent in eligible_parents(result):
        positions = [embedded.position_by_row[member.row] for member in parent.members]
        sliced_vectors = embedded.vectors[np.array(positions, dtype=int)]
        sliced_texts = [member.text for member in parent.members]
        sliced_row_indexes = [member.row for member in parent.members]

        sub_result = cluster_answers(
            sliced_vectors.tolist(),
            sliced_texts,
            sliced_row_indexes,
            min_cluster_size=sub_cluster_min_size(len(parent.members)),
        )

        kept = sub_result.clusters[:MAX_SUBTHEMES_PER_THEME]
        coverage = sum(len(c.members) for c in kept) / len(parent.members) if parent.members else 0.0

        if len(kept) >= 2 and coverage >= MIN_SUBTHEME_COVERAGE:
            out[parent.id] = kept

    return out
