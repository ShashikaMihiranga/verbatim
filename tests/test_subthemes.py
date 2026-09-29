"""Stream 6 (S1 add-on): sub-theme clustering. All fixtures are inline plain numpy, no FakeEmbeddingClient
needed here - see app/text_pipeline/subthemes.py's own docstring for why a NESTED high-dimensional fixture
(a `_high_dimensional_fixture`-style setup, but with each "parent" itself built from a few sub-families)
is required to exercise `sub_cluster_themes`'s real HDBSCAN-on-a-slice behaviour, mirroring
tests/test_text_pipeline.py's `_high_dimensional_fixture` conventions.
"""
import numpy as np
import pytest

from app.text_pipeline import Cluster, ClusterMember, ClusterResult, EmbeddedAnswers
from app.text_pipeline.subthemes import (
    MAX_SUBTHEMES_PER_THEME,
    MAX_THEMES_TO_SPLIT,
    MIN_SUBTHEME_COVERAGE,
    MIN_THEME_SIZE_FOR_SUBTHEMES,
    eligible_parents,
    sub_cluster_min_size,
    sub_cluster_themes,
)

# ---------------------------------------------------------------- nested fixture (parents made of sub-families)
#
# Mirrors test_text_pipeline.py's _high_dimensional_fixture, one level deeper: each "parent" direction is a
# random unit vector in NESTED_DIMS-space (comfortably past MIN_DIMENSIONS_FOR_REDUCTION=50 so UMAP always
# runs, per MIN_THEME_SIZE_FOR_SUBTHEMES=100's own margin above that), and each of its sub-families is a
# small, distinct offset from that parent direction, with further per-member jitter on top - so a fresh
# cluster_answers() call on just one parent's own vector slice has real, recoverable sub-structure to find,
# the same way a real theme's own answers might split into a few real sub-themes.

NESTED_SUBFAMILIES = 3
NESTED_SUBFAMILY_SIZE = 50
NESTED_DIMS = 300
NESTED_SUB_OFFSET_SCALE = 0.35  # separation between sub-families within one parent
NESTED_MEMBER_NOISE_SCALE = 0.05  # within-sub-family jitter, small relative to the offset above


def _nested_family(parent_center, n_subfamilies, subfamily_size, dims, rng):
    """One parent's own vectors: `n_subfamilies` distinct sub-groups of `subfamily_size` members each,
    all built around `parent_center`. Returns `(vectors, subfamily_of_row)`."""
    vectors: list[list[float]] = []
    subfamily_of_row: list[int] = []
    for s in range(n_subfamilies):
        sub_center = parent_center + rng.normal(scale=NESTED_SUB_OFFSET_SCALE, size=dims)
        for _ in range(subfamily_size):
            v = sub_center + rng.normal(scale=NESTED_MEMBER_NOISE_SCALE, size=dims)
            v = v / np.linalg.norm(v)
            vectors.append(v.tolist())
            subfamily_of_row.append(s)
    return vectors, subfamily_of_row


def _two_parent_fixture(seed=11):
    """2 parents x NESTED_SUBFAMILIES sub-families x NESTED_SUBFAMILY_SIZE members each (150/parent),
    NESTED_DIMS-dimensional and unit-length. Returns a `(ClusterResult, EmbeddedAnswers)` pair ready to
    hand straight to `sub_cluster_themes` - two top-level Cluster "themes" (ids 0 and 1), rows 0-149 and
    150-299 respectively, with no noise (irrelevant to this module - see decision 2)."""
    rng = np.random.RandomState(seed)
    parent_centers = rng.normal(size=(2, NESTED_DIMS))
    parent_centers /= np.linalg.norm(parent_centers, axis=1, keepdims=True)

    all_vectors: list[list[float]] = []
    parent_of_row: list[int] = []
    subfamily_of_row: list[int] = []
    for p in range(2):
        vectors, subfamilies = _nested_family(
            parent_centers[p], NESTED_SUBFAMILIES, NESTED_SUBFAMILY_SIZE, NESTED_DIMS, rng
        )
        all_vectors.extend(vectors)
        parent_of_row.extend([p] * len(vectors))
        subfamily_of_row.extend(subfamilies)

    clusters = []
    for p in range(2):
        rows = [i for i, pr in enumerate(parent_of_row) if pr == p]
        members = [ClusterMember(row=r, text=f"answer {r}", distance=None) for r in rows]
        clusters.append(Cluster(id=p, members=members, centroid=None))

    result = ClusterResult(column="Why", clusters=clusters, noise=[], total_answers=len(all_vectors))
    vectors_arr = np.asarray(all_vectors, dtype="float32")
    embedded = EmbeddedAnswers(
        row_indexes=list(range(len(all_vectors))),
        vectors=vectors_arr,
        position_by_row={i: i for i in range(len(all_vectors))},
    )
    return result, embedded, subfamily_of_row


def test_sub_cluster_themes_recovers_real_subfamilies_for_both_parents():
    result, embedded, subfamily_of_row = _two_parent_fixture()
    parent_size = NESTED_SUBFAMILIES * NESTED_SUBFAMILY_SIZE  # 150

    sub = sub_cluster_themes(result, embedded)

    assert set(sub.keys()) == {0, 1}
    for parent_id, kept in sub.items():
        assert 2 <= len(kept) <= MAX_SUBTHEMES_PER_THEME
        coverage = sum(len(c.members) for c in kept) / parent_size
        assert coverage >= MIN_SUBTHEME_COVERAGE
        # kept sub-clusters are sorted largest first (cluster_answers' own guarantee)
        sizes = [len(c.members) for c in kept]
        assert sizes == sorted(sizes, reverse=True)
        # purity: each kept sub-cluster should be dominated by a single real sub-family
        for c in kept:
            true_subs = [subfamily_of_row[m.row] for m in c.members]
            most_common = max(set(true_subs), key=true_subs.count)
            purity = sum(1 for t in true_subs if t == most_common) / len(true_subs)
            assert purity > 0.7


def test_sub_cluster_themes_caps_at_max_subthemes_even_with_more_real_subfamilies():
    rng = np.random.RandomState(23)
    parent_center = rng.normal(size=NESTED_DIMS)
    parent_center /= np.linalg.norm(parent_center)
    vectors, subfamilies = _nested_family(parent_center, 5, 40, NESTED_DIMS, rng)  # 5 real sub-families

    members = [ClusterMember(row=i, text=f"answer {i}", distance=None) for i in range(len(vectors))]
    parent = Cluster(id=0, members=members, centroid=None)
    result = ClusterResult(column="Why", clusters=[parent], noise=[], total_answers=len(vectors))
    embedded = EmbeddedAnswers(
        row_indexes=list(range(len(vectors))),
        vectors=np.asarray(vectors, dtype="float32"),
        position_by_row={i: i for i in range(len(vectors))},
    )

    sub = sub_cluster_themes(result, embedded)

    assert 0 in sub
    assert len(sub[0]) <= MAX_SUBTHEMES_PER_THEME


TINY_DIMS = 4  # irrelevant to these two tests - cluster_answers itself is monkeypatched out below, so the
# real vector content never matters; only sub_cluster_themes' own coverage/count gating is under test.


def _flat_parent_setup(n=150, dims=TINY_DIMS):
    parent = _dummy_cluster(0, n)
    result = ClusterResult(column="Why", clusters=[parent], noise=[], total_answers=n)
    embedded = EmbeddedAnswers(
        row_indexes=list(range(n)),
        vectors=np.zeros((n, dims), dtype="float32"),
        position_by_row={i: i for i in range(n)},
    )
    return result, embedded


def test_sub_cluster_themes_omits_parent_below_coverage_threshold(monkeypatch):
    # Isolate the coverage rule from the count rule and from HDBSCAN's own real (occasionally noisy)
    # behaviour: cluster_answers is monkeypatched to return exactly 2 real sub-clusters (satisfying the
    # ">= 2" rule) that together cover well under MIN_SUBTHEME_COVERAGE of the parent's 150 answers.
    result, embedded = _flat_parent_setup(n=150)

    def fake_cluster_answers(vectors, texts, row_indexes, min_cluster_size=None):
        c0 = Cluster(id=0, members=[ClusterMember(row=row_indexes[i], text=texts[i], distance=0.0) for i in range(20)], centroid=None)
        c1 = Cluster(id=1, members=[ClusterMember(row=row_indexes[i], text=texts[i], distance=0.0) for i in range(20, 40)], centroid=None)
        noise = [ClusterMember(row=row_indexes[i], text=texts[i], distance=None) for i in range(40, len(row_indexes))]
        return ClusterResult(column="", clusters=[c0, c1], noise=noise, total_answers=len(row_indexes))

    monkeypatch.setattr("app.text_pipeline.subthemes.cluster_answers", fake_cluster_answers)

    sub = sub_cluster_themes(result, embedded)

    assert 0 not in sub  # 40/150 == 26.7% coverage, well under the 50% floor


def test_sub_cluster_themes_omits_parent_with_only_one_real_subcluster(monkeypatch):
    # Isolate the "at least 2 sub-clusters" rule: cluster_answers is monkeypatched to return exactly one
    # real cluster covering 100% of the parent - full coverage is not enough on its own.
    result, embedded = _flat_parent_setup(n=150)

    def fake_cluster_answers(vectors, texts, row_indexes, min_cluster_size=None):
        c0 = Cluster(id=0, members=[ClusterMember(row=r, text=t, distance=0.0) for r, t in zip(row_indexes, texts)], centroid=None)
        return ClusterResult(column="", clusters=[c0], noise=[], total_answers=len(row_indexes))

    monkeypatch.setattr("app.text_pipeline.subthemes.cluster_answers", fake_cluster_answers)

    sub = sub_cluster_themes(result, embedded)

    assert 0 not in sub  # 100% coverage but only 1 sub-cluster - fails the "at least 2" rule


def test_sub_cluster_themes_omits_parent_with_zero_real_subclusters(monkeypatch):
    # The "at least 2" rule also covers the 0-sub-cluster case (everything comes back as noise).
    result, embedded = _flat_parent_setup(n=150)

    def fake_cluster_answers(vectors, texts, row_indexes, min_cluster_size=None):
        noise = [ClusterMember(row=r, text=t, distance=None) for r, t in zip(row_indexes, texts)]
        return ClusterResult(column="", clusters=[], noise=noise, total_answers=len(row_indexes))

    monkeypatch.setattr("app.text_pipeline.subthemes.cluster_answers", fake_cluster_answers)

    sub = sub_cluster_themes(result, embedded)

    assert 0 not in sub


# ---------------------------------------------------------------- eligible_parents


def _dummy_cluster(cluster_id, size):
    members = [ClusterMember(row=i, text="x", distance=None) for i in range(size)]
    return Cluster(id=cluster_id, members=members, centroid=None)


def test_eligible_parents_excludes_just_below_the_floor_and_includes_at_the_floor():
    below = _dummy_cluster(0, MIN_THEME_SIZE_FOR_SUBTHEMES - 1)
    at_floor = _dummy_cluster(1, MIN_THEME_SIZE_FOR_SUBTHEMES)
    result = ClusterResult(column="Why", clusters=[at_floor, below], noise=[], total_answers=299)

    elig = eligible_parents(result)

    assert [c.id for c in elig] == [1]


def test_eligible_parents_caps_at_max_themes_to_split_even_with_more_large_clusters():
    clusters = [_dummy_cluster(i, 500 - i) for i in range(MAX_THEMES_TO_SPLIT + 2)]  # all well above the floor
    result = ClusterResult(column="Why", clusters=clusters, noise=[], total_answers=sum(len(c.members) for c in clusters))

    elig = eligible_parents(result)

    assert len(elig) == MAX_THEMES_TO_SPLIT
    assert [c.id for c in elig] == list(range(MAX_THEMES_TO_SPLIT))


def test_eligible_parents_never_includes_noise():
    real = _dummy_cluster(0, MIN_THEME_SIZE_FOR_SUBTHEMES)
    huge_noise = [ClusterMember(row=1000 + i, text="x", distance=None) for i in range(5000)]
    result = ClusterResult(column="Why", clusters=[real], noise=huge_noise, total_answers=5000 + MIN_THEME_SIZE_FOR_SUBTHEMES)

    elig = eligible_parents(result)

    assert [c.id for c in elig] == [0]  # noise, however large, never becomes an eligible "parent"


# ---------------------------------------------------------------- sub_cluster_min_size


def test_sub_cluster_min_size_scales_with_parent_size_and_floors_at_five():
    assert sub_cluster_min_size(20) == 5  # round(20*0.10) == 2, floored to 5
    assert sub_cluster_min_size(50) == 5  # round(50*0.10) == 5, exactly at the floor
    assert sub_cluster_min_size(100) == 10
    assert sub_cluster_min_size(1000) == 100
