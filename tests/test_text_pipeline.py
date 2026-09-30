"""Stream 6: text pipeline (embed + cluster). All fixtures are inline; FakeEmbeddingClient only, no network."""
import itertools
import os
import socket

import numpy as np
import pandas as pd
import pytest
from sklearn.cluster import HDBSCAN

from app.cleaning import CleaningError, model_safe_column, plan_cleaning
from app.text_pipeline import (
    EmbeddedAnswers,
    EmbeddingNotConfigured,
    FakeEmbeddingClient,
    TooFewAnswers,
    VoyageEmbeddingClient,
    adaptive_min_cluster_size,
    adaptive_min_samples,
    adaptive_n_components,
    cluster_answers,
    embed_and_cluster,
    embed_and_cluster_with_vectors,
)
from app.text_pipeline.clustering import (
    MIN_ANSWERS_FOR_REDUCTION,
    MIN_DIMENSIONS_FOR_REDUCTION,
    _reduce_for_clustering,
    adaptive_fine_min_cluster_size,
)


def profile_for(df, kinds, sensitive=()):
    return {"columns": [{"name": c, "kind": kinds.get(c, "id_or_junk"), "sensitive": c in sensitive}
                        for c in df.columns]}


# ---------------------------------------------------------------- model_safe_column


def test_model_safe_column_masks_and_aligns_rows_with_none_for_blanks():
    df = pd.DataFrame(
        {
            "Why": [
                "my name is Sam Wu, call me on 0412345678",
                np.nan,
                "plain answer with nothing to mask",
                "",
                "another plain one",
            ]
        },
        index=[0, 1, 3, 4, 7],  # a non-contiguous index, as clean_df has after cleaning drops rows
    ).astype(object)
    plan = plan_cleaning(df, profile_for(df, {"Why": "open_text"}))
    out = model_safe_column(df, plan, "Why")

    assert len(out) == len(df) == 5
    assert out[1] is None  # NaN is missing, never a string - None, not "nan" or ""
    assert out[3] == ""  # an actual empty string is a real (empty) value, not a missing one
    assert "Sam" not in out[0] and "0412345678" not in out[0]
    assert out[2] == "plain answer with nothing to mask"
    assert out[4] == "another plain one"
    # Alignment is positional, matching clean_df.index order, not a re-indexed 0..n-1
    assert list(df.index) == [0, 1, 3, 4, 7]


def test_model_safe_column_refuses_sensitive_and_non_text_columns():
    df = pd.DataFrame({"Why": ["a fine open answer here"], "Age": [42], "Gender": ["Male"]}).astype(object)
    plan = plan_cleaning(
        df,
        profile_for(df, {"Why": "open_text", "Age": "numeric", "Gender": "segment"}, sensitive=("Age", "Gender")),
    )
    with pytest.raises(CleaningError):
        model_safe_column(df, plan, "Age")  # sensitive
    with pytest.raises(CleaningError):
        model_safe_column(df, plan, "Gender")  # sensitive
    with pytest.raises(CleaningError):
        model_safe_column(df, plan, "Nope")  # unknown column


def test_model_safe_column_refuses_numeric_non_text_kind():
    df = pd.DataFrame({"Spend": [100, 200, 300]}).astype(object)
    plan = plan_cleaning(df, profile_for(df, {"Spend": "numeric"}))
    with pytest.raises(CleaningError):
        model_safe_column(df, plan, "Spend")  # numeric, not open_text/short_text, and not sensitive


# ---------------------------------------------------------------- clustering fixtures
#
# Each topic below is 30 DISTINCT near-duplicate phrasings, built by combining four small word pools for
# that topic (5 x 5 x 5 x 5 combinations, first 30 taken). No two answers in a topic are identical text
# (an exact repeat would give HDBSCAN a zero-distance point and it tends to carve those into their own
# tiny, extremely dense sub-cluster instead of merging with the rest of the topic - not what a real
# embedding model would do, but a quirk of hashing exact-duplicate bags of words). Distinct combinations
# from a shared, topic-specific vocabulary is closer to what near-duplicate SURVEY answers look like
# anyway, and clusters cleanly with the hash-based FakeEmbeddingClient.

BATTERY_POOLS = [
    ["battery life", "the battery", "my battery", "battery performance", "battery power"],
    ["drains", "runs down", "fades", "wears down", "dies off"],
    ["far too", "way too", "just too", "really too", "still too"],
    ["quickly", "fast", "rapidly", "soon", "abruptly"],
]
PRICE_POOLS = [
    ["the sticker price", "resale value", "the upfront cost", "overall price", "monthly cost"],
    ["feels", "seems", "stays", "looks", "runs"],
    ["far too", "way too", "just too", "really too", "still too"],
    ["high", "steep", "expensive", "costly", "pricey"],
]
OUTLIERS = [
    "purple elephants dance wildly under the midnight carnival lights",
    "my grandmother's clock collection keeps unusual antique time zones",
    "a lonely kazoo festival happened downtown last tuesday evening",
]


def _combos(pools, n):
    return [" ".join(c) for c in itertools.islice(itertools.product(*pools), n)]


def _fixture_texts():
    battery = _combos(BATTERY_POOLS, 30)
    price = _combos(PRICE_POOLS, 30)
    return battery, price, OUTLIERS


def test_cluster_answers_finds_distinct_fake_clusters_and_keeps_noise():
    battery, price, outliers = _fixture_texts()
    texts = battery + price + outliers
    row_indexes = list(range(len(texts)))
    vectors = FakeEmbeddingClient().embed(texts)

    result = cluster_answers(vectors, texts, row_indexes)

    assert result.total_answers == len(texts) == 63
    # counts must add up: every answer is in exactly one cluster or in noise, nothing dropped
    assert sum(len(c.members) for c in result.clusters) + len(result.noise) == result.total_answers

    assert len(result.clusters) == 2
    sizes = sorted(len(c.members) for c in result.clusters)
    assert sizes == [30, 30]

    # the two topics land in different clusters (not merged together)
    battery_rows = set(range(30))
    price_rows = set(range(30, 60))
    cluster_row_sets = [{m.row for m in c.members} for c in result.clusters]
    assert any(rows == battery_rows for rows in cluster_row_sets)
    assert any(rows == price_rows for rows in cluster_row_sets)

    # the three unrelated outliers never join a real cluster
    outlier_rows = {60, 61, 62}
    noise_rows = {m.row for m in result.noise}
    assert outlier_rows <= noise_rows

    # every clustered member has a distance to its centroid; noise members do not
    assert all(m.distance is not None for c in result.clusters for m in c.members)
    assert all(m.distance is None for m in result.noise)
    assert all(c.centroid is not None for c in result.clusters)

    # cluster ids are stable 0-based, largest first (both equal here, so just check they are 0 and 1)
    assert {c.id for c in result.clusters} == {0, 1}


def test_cluster_answers_min_cluster_size_is_adaptive_by_dataset_size():
    small = adaptive_min_cluster_size(40)
    large = adaptive_min_cluster_size(3000)
    assert small != large
    assert small == 5  # floor
    assert large == 50  # ceiling
    # a mid-size dataset lands between the floor and ceiling
    mid = adaptive_min_cluster_size(1000)
    assert 5 < mid < 50
    assert mid == round(1000 / 50)


def test_adaptive_fine_min_cluster_size_is_finer_than_standard_and_bounded():
    """Same floor/ceiling shape as adaptive_min_cluster_size, but a bigger divisor - only used for
    cluster_answers(..., merge_fine_clusters=True)'s first pass, see docs/DECISIONS.md."""
    assert adaptive_fine_min_cluster_size(40) == 5  # floor
    assert adaptive_fine_min_cluster_size(6000) == 50  # ceiling
    mid = adaptive_fine_min_cluster_size(1597)
    assert mid == round(1597 / 100)
    assert mid < adaptive_min_cluster_size(1597)  # strictly finer than the standard floor at the same n


def test_cluster_answers_deterministic_given_same_input():
    battery, price, outliers = _fixture_texts()
    texts = battery + price + outliers
    row_indexes = list(range(len(texts)))
    vectors = FakeEmbeddingClient().embed(texts)

    r1 = cluster_answers(vectors, texts, row_indexes)
    r2 = cluster_answers(vectors, texts, row_indexes)

    labels1 = sorted(tuple(sorted(m.row for m in c.members)) for c in r1.clusters)
    labels2 = sorted(tuple(sorted(m.row for m in c.members)) for c in r2.clusters)
    assert labels1 == labels2
    assert {m.row for m in r1.noise} == {m.row for m in r2.noise}


# ---------------------------------------------------------------- high-dimensional fixture (proves the bug + fix)
#
# The bug this section proves: on a real 23,486-row product-review dataset, clustering the raw
# 1024-dimensional Voyage embeddings directly with HDBSCAN put 22,641/23,486 answers (96%) into noise -
# essentially no themes found - because density-based clustering degrades badly on raw high-dimensional
# vectors (distances concentrate; HDBSCAN can no longer tell a dense region from background noise). Every
# other fixture in this file uses FakeEmbeddingClient's 32-dimensional vectors, which never triggered this
# because the failure is specifically about high dimensionality. This fixture is deliberately different:
# real dimensionality (300, comfortably past MIN_DIMENSIONS_FOR_REDUCTION), enough rows to clear
# MIN_ANSWERS_FOR_REDUCTION, and a few genuinely separable groups plus unstructured noise vectors - built
# with plain numpy (not FakeEmbeddingClient, which is only 32-dimensional by design) so the group structure
# is known ground truth to assert against.

HIGH_DIM_GROUPS = 3
HIGH_DIM_GROUP_SIZE = 60
HIGH_DIM_NOISE_COUNT = 15
HIGH_DIM_DIMS = 300
HIGH_DIM_NOISE_SCALE = 0.3  # per-dimension noise added to each group member, before renormalising to unit length


def _high_dimensional_fixture(seed: int = 7):
    """`HIGH_DIM_GROUPS` separable groups of `HIGH_DIM_GROUP_SIZE` vectors each, plus `HIGH_DIM_NOISE_COUNT`
    unrelated noise vectors, all `HIGH_DIM_DIMS`-dimensional and unit-length (like real embeddings). Each
    group is a random direction in `HIGH_DIM_DIMS`-space; members are that direction plus substantial
    per-dimension noise spread across ALL dimensions (mimicking how a real embedding's true semantic signal
    is thin relative to the many other directions in the space) before renormalising. Returns
    `(vectors, true_group_of_each_row)`, `true_group_of_each_row[i]` being 0/1/2 for a real group or -1 for
    a noise vector; deterministic for a fixed `seed` (same numpy `RandomState` every call).
    """
    rng = np.random.RandomState(seed)
    centers = rng.normal(size=(HIGH_DIM_GROUPS, HIGH_DIM_DIMS))
    centers /= np.linalg.norm(centers, axis=1, keepdims=True)

    vectors: list[list[float]] = []
    true_groups: list[int] = []
    for g in range(HIGH_DIM_GROUPS):
        for _ in range(HIGH_DIM_GROUP_SIZE):
            v = centers[g] + rng.normal(scale=HIGH_DIM_NOISE_SCALE, size=HIGH_DIM_DIMS)
            v = v / np.linalg.norm(v)
            vectors.append(v.tolist())
            true_groups.append(g)
    for _ in range(HIGH_DIM_NOISE_COUNT):
        v = rng.normal(size=HIGH_DIM_DIMS)
        v = v / np.linalg.norm(v)
        vectors.append(v.tolist())
        true_groups.append(-1)
    return vectors, true_groups


def test_reduce_for_clustering_skips_itself_below_the_answer_count_threshold():
    small_vectors = [[0.1] * (MIN_DIMENSIONS_FOR_REDUCTION + 10) for _ in range(MIN_ANSWERS_FOR_REDUCTION - 1)]
    assert _reduce_for_clustering(small_vectors) is small_vectors


def test_reduce_for_clustering_skips_itself_below_the_dimension_threshold():
    low_dim_vectors = [[0.1] * (MIN_DIMENSIONS_FOR_REDUCTION - 1) for _ in range(MIN_ANSWERS_FOR_REDUCTION + 10)]
    assert _reduce_for_clustering(low_dim_vectors) is low_dim_vectors


def test_reduce_for_clustering_reduces_large_high_dimensional_input():
    vectors, _ = _high_dimensional_fixture()
    reduced = _reduce_for_clustering(vectors)
    assert len(reduced) == len(vectors)
    assert len(reduced[0]) == adaptive_n_components(len(vectors))
    assert len(reduced[0]) < len(vectors[0])  # a real reduction happened, not a no-op


def test_cluster_answers_on_raw_high_dimensional_vectors_finds_almost_nothing():
    """The bug, reproduced directly: HDBSCAN straight on raw high-dimensional vectors (no reduction, the
    module's behaviour before this fix) fails to recover even well-separated groups."""
    vectors, true_groups = _high_dimensional_fixture()
    min_cluster_size = 20
    model = HDBSCAN(min_cluster_size=min_cluster_size, min_samples=min_cluster_size, store_centers="centroid", copy=True)
    labels = model.fit_predict(np.asarray(vectors))

    n_clusters = len({label for label in labels if label != -1})
    noise_count = int((labels == -1).sum())
    assert n_clusters == 0  # not one real cluster recovered from 3 genuinely separable groups
    assert noise_count == len(vectors)  # every single answer written off as noise


def test_cluster_answers_recovers_separable_groups_with_reduction():
    """The fix, proven against the same fixture: routing through `cluster_answers` (UMAP reduction, then
    HDBSCAN with the tuned `min_samples`) recovers the real group structure the raw-vector path above missed
    entirely."""
    vectors, true_groups = _high_dimensional_fixture()
    texts = [f"answer {i}" for i in range(len(vectors))]
    row_indexes = list(range(len(vectors)))

    result = cluster_answers(vectors, texts, row_indexes, min_cluster_size=20)

    assert sum(len(c.members) for c in result.clusters) + len(result.noise) == result.total_answers
    # real structure recovered: at least as many clusters as true groups, and most answers land somewhere
    # real rather than being written off as noise (contrast with 0 clusters / 100% noise for the raw path).
    assert len(result.clusters) >= 2
    noise_fraction = len(result.noise) / result.total_answers
    assert noise_fraction < 0.5

    # purity: for each recovered cluster, most of its members should share the same true group
    true_group_of_row = dict(zip(row_indexes, true_groups))
    correctly_grouped = 0
    total_grouped = 0
    for cluster in result.clusters:
        member_true_groups = [true_group_of_row[m.row] for m in cluster.members]
        total_grouped += len(member_true_groups)
        most_common = max(set(member_true_groups), key=member_true_groups.count)
        correctly_grouped += sum(1 for g in member_true_groups if g == most_common)
    assert total_grouped > 0
    assert correctly_grouped / total_grouped > 0.75  # clusters are overwhelmingly single-group, not a jumble


def test_cluster_answers_reduction_path_is_deterministic_given_same_input():
    vectors, _ = _high_dimensional_fixture()
    texts = [f"answer {i}" for i in range(len(vectors))]
    row_indexes = list(range(len(vectors)))

    r1 = cluster_answers(vectors, texts, row_indexes, min_cluster_size=20)
    r2 = cluster_answers(vectors, texts, row_indexes, min_cluster_size=20)

    labels1 = sorted(tuple(sorted(m.row for m in c.members)) for c in r1.clusters)
    labels2 = sorted(tuple(sorted(m.row for m in c.members)) for c in r2.clusters)
    assert labels1 == labels2
    assert {m.row for m in r1.noise} == {m.row for m in r2.noise}


def _bigger_separable_fixture(seed: int = 11):
    """Same shape/style as `_high_dimensional_fixture`, but at n=1597 (3 x 500 + 97 noise) - deliberately
    matching the real dataset size `finer_floor` was calibrated against (docs/DECISIONS.md's 2026-09-30
    entry), where the fine floor (round(1597/100)=16) lands well above `MIN_MIN_CLUSTER_SIZE`'s absolute
    floor of 5. At the smaller `_high_dimensional_fixture()` size (n=195), the fine and standard floors
    both clamp to that same absolute minimum, which would not fairly exercise this feature at all."""
    rng_groups, rng_group_size, rng_noise = 3, 500, 97
    rng = np.random.RandomState(seed)
    centers = rng.normal(size=(rng_groups, HIGH_DIM_DIMS))
    centers /= np.linalg.norm(centers, axis=1, keepdims=True)
    vectors: list[list[float]] = []
    true_groups: list[int] = []
    for g in range(rng_groups):
        for _ in range(rng_group_size):
            v = centers[g] + rng.normal(scale=HIGH_DIM_NOISE_SCALE, size=HIGH_DIM_DIMS)
            vectors.append((v / np.linalg.norm(v)).tolist())
            true_groups.append(g)
    for _ in range(rng_noise):
        v = rng.normal(size=HIGH_DIM_DIMS)
        vectors.append((v / np.linalg.norm(v)).tolist())
        true_groups.append(-1)
    return vectors, true_groups


def _purity(result, row_indexes, true_group_of_row):
    correct, total = 0, 0
    for cluster in result.clusters:
        member_true_groups = [true_group_of_row[m.row] for m in cluster.members]
        total += len(member_true_groups)
        most_common = max(set(member_true_groups), key=member_true_groups.count)
        correct += sum(1 for g in member_true_groups if g == most_common)
    return correct, total


def test_cluster_answers_with_finer_floor_recovers_more_without_fragmenting_or_losing_purity():
    """finer_floor=True's whole point: recover small-but-real structure that a dataset-wide floor would
    write off as noise, WITHOUT the two failure modes an earlier, dropped design had (see
    docs/DECISIONS.md's 2026-09-30 entry) - fragmenting already-good big groups, or degrading purity by
    also loosening HDBSCAN's density strictness. Checked directly against the plain/standard path on the
    identical fixture, not just in isolation."""
    vectors, true_groups = _bigger_separable_fixture()
    texts = [f"answer {i}" for i in range(len(vectors))]
    row_indexes = list(range(len(vectors)))
    true_group_of_row = dict(zip(row_indexes, true_groups))

    standard = cluster_answers(vectors, texts, row_indexes)
    finer = cluster_answers(vectors, texts, row_indexes, finer_floor=True)

    for result in (standard, finer):
        assert sum(len(c.members) for c in result.clusters) + len(result.noise) == result.total_answers
        assert all(m.distance is not None for c in result.clusters for m in c.members)
        assert all(c.centroid is not None for c in result.clusters)

    # recovers at least as much real structure (no fewer answers left in noise)...
    assert len(finer.noise) <= len(standard.noise)
    # ...without fragmenting the 3 true groups into many small pieces...
    assert len(finer.clusters) <= 5
    # ...and without sacrificing purity to get there (the bug this pins: min_samples must stay pinned to
    # the standard floor's strictness, not loosen along with the finer size floor).
    standard_correct, standard_total = _purity(standard, row_indexes, true_group_of_row)
    finer_correct, finer_total = _purity(finer, row_indexes, true_group_of_row)
    assert finer_total > 0
    assert finer_correct / finer_total > 0.85
    assert finer_correct / finer_total >= (standard_correct / standard_total) - 0.05  # within noise of the standard path's own purity


def test_adaptive_min_samples_is_smaller_than_min_cluster_size_and_bounded():
    assert adaptive_min_samples(5) == 3  # floor
    assert adaptive_min_samples(50) == 10  # ceiling
    assert adaptive_min_samples(30) == round(30 / 3)
    assert adaptive_min_samples(30) < 30  # always more permissive than min_cluster_size itself


def test_adaptive_n_components_is_bounded_and_grows_mildly_with_answer_count():
    assert adaptive_n_components(60) == 5  # floor
    assert adaptive_n_components(10_000) == 15  # ceiling
    mid = adaptive_n_components(3000)
    assert 5 < mid < 15
    assert mid == round(3000 / 300)


# ---------------------------------------------------------------- zero network (UMAP/HDBSCAN are pure local compute)


class _NoSockets:
    def __enter__(self):
        self._orig = socket.socket

        def _blocked(*a, **k):
            raise AssertionError("a real socket was opened - clustering must never touch the network")

        socket.socket = _blocked
        return self

    def __exit__(self, *exc):
        socket.socket = self._orig


def test_cluster_answers_with_reduction_never_touches_the_network():
    vectors, _ = _high_dimensional_fixture()
    texts = [f"answer {i}" for i in range(len(vectors))]
    row_indexes = list(range(len(vectors)))

    with _NoSockets():
        result = cluster_answers(vectors, texts, row_indexes, min_cluster_size=20)
    assert result.total_answers == len(vectors)


# ---------------------------------------------------------------- pipeline


def _survey_df(n_good=25, n_blank=3):
    battery, price, _ = _fixture_texts()
    texts = (battery + price)[:n_good] + [np.nan] * n_blank
    return pd.DataFrame({"Why": texts}).astype(object)


def test_embed_and_cluster_end_to_end_with_fake_client():
    df = _survey_df(n_good=40, n_blank=2)
    plan = plan_cleaning(df, profile_for(df, {"Why": "open_text"}))

    result = embed_and_cluster(df, plan, "Why", FakeEmbeddingClient())

    assert result.column == "Why"
    assert result.total_answers == 40  # the 2 blanks are excluded, never renumbered into the count
    assert sum(len(c.members) for c in result.clusters) + len(result.noise) == 40


def test_embed_and_cluster_too_few_answers_raises_clear_error():
    df = _survey_df(n_good=10, n_blank=5)  # well under MIN_ANSWERS_TO_CLUSTER
    plan = plan_cleaning(df, profile_for(df, {"Why": "open_text"}))

    with pytest.raises(TooFewAnswers):
        embed_and_cluster(df, plan, "Why", FakeEmbeddingClient())


def test_embed_and_cluster_keeps_original_row_indexes():
    df = _survey_df(n_good=25, n_blank=3)  # 25 real answers at positions 0-24, blanks at 25-27
    # A non-contiguous index, like a dataframe that already had rows dropped by cleaning: the 3 blank
    # rows (last 3 positions) get index labels 33, 34, 35, well outside the "good answer" range.
    df.index = list(range(0, 22)) + list(range(30, 36))
    plan = plan_cleaning(df, profile_for(df, {"Why": "open_text"}))

    result = embed_and_cluster(df, plan, "Why", FakeEmbeddingClient())

    all_rows = {m.row for c in result.clusters for m in c.members} | {m.row for m in result.noise}
    assert all_rows <= set(df.index)  # every reported row is a real index label, never renumbered
    assert not all_rows & {33, 34, 35}  # the blank rows' index labels never appear: they were skipped


# ---------------------------------------------------------------- embed_and_cluster_with_vectors


def test_embed_and_cluster_with_vectors_returns_embedded_answers_consistent_with_the_result():
    df = _survey_df(n_good=25, n_blank=3)
    plan = plan_cleaning(df, profile_for(df, {"Why": "open_text"}))
    client = FakeEmbeddingClient()

    result, embedded = embed_and_cluster_with_vectors(df, plan, "Why", client)

    assert isinstance(embedded, EmbeddedAnswers)
    assert isinstance(embedded.vectors, np.ndarray)
    assert embedded.vectors.dtype == np.float32
    assert embedded.vectors.shape == (len(embedded.row_indexes), 32)  # FakeEmbeddingClient default dims

    # every member row across every cluster + noise appears in position_by_row, and the vector there is
    # the right one for that row - verified against FakeEmbeddingClient's own deterministic mapping.
    all_members = [m for c in result.clusters for m in c.members] + result.noise
    assert all_members  # sanity: there is something to check
    for member in all_members:
        assert member.row in embedded.position_by_row
        position = embedded.position_by_row[member.row]
        assert embedded.row_indexes[position] == member.row
        expected_vector = FakeEmbeddingClient().embed([member.text])[0]
        actual_vector = embedded.vectors[position]
        assert np.allclose(actual_vector, expected_vector, atol=1e-6)

    # embedded.row_indexes is exactly the set of rows that went into clustering (== total_answers)
    assert len(embedded.row_indexes) == result.total_answers
    assert set(embedded.row_indexes) == {m.row for m in all_members}


def test_embed_and_cluster_with_vectors_raises_too_few_answers_same_as_wrapper():
    df = _survey_df(n_good=10, n_blank=5)
    plan = plan_cleaning(df, profile_for(df, {"Why": "open_text"}))

    with pytest.raises(TooFewAnswers):
        embed_and_cluster_with_vectors(df, plan, "Why", FakeEmbeddingClient())


def test_embed_and_cluster_is_unchanged_now_that_it_wraps_with_vectors():
    """embed_and_cluster's return value/behavior must be byte-identical to before - it is now a thin
    wrapper around embed_and_cluster_with_vectors, discarding the EmbeddedAnswers half of the tuple."""
    df = _survey_df(n_good=40, n_blank=2)
    plan = plan_cleaning(df, profile_for(df, {"Why": "open_text"}))

    result = embed_and_cluster(df, plan, "Why", FakeEmbeddingClient())
    result_via_pair, _ = embed_and_cluster_with_vectors(df, plan, "Why", FakeEmbeddingClient())

    assert result.column == result_via_pair.column == "Why"
    assert result.total_answers == result_via_pair.total_answers == 40
    assert sum(len(c.members) for c in result.clusters) + len(result.noise) == 40
    r1_rows = sorted(tuple(sorted(m.row for m in c.members)) for c in result.clusters)
    r2_rows = sorted(tuple(sorted(m.row for m in c.members)) for c in result_via_pair.clusters)
    assert r1_rows == r2_rows
    assert {m.row for m in result.noise} == {m.row for m in result_via_pair.noise}


# ---------------------------------------------------------------- VoyageEmbeddingClient (no network)


@pytest.mark.skipif(
    bool(os.environ.get("VOYAGE_API_KEY")),
    reason="only exercises the no-key path; would otherwise construct a real, key-bearing client",
)
def test_voyage_client_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    with pytest.raises(EmbeddingNotConfigured):
        VoyageEmbeddingClient()
