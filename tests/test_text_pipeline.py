"""Stream 6: text pipeline (embed + cluster). All fixtures are inline; FakeEmbeddingClient only, no network."""
import itertools
import os

import numpy as np
import pandas as pd
import pytest

from app.cleaning import CleaningError, model_safe_column, plan_cleaning
from app.text_pipeline import (
    EmbeddingNotConfigured,
    FakeEmbeddingClient,
    TooFewAnswers,
    VoyageEmbeddingClient,
    adaptive_min_cluster_size,
    cluster_answers,
    embed_and_cluster,
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


# ---------------------------------------------------------------- VoyageEmbeddingClient (no network)


@pytest.mark.skipif(
    bool(os.environ.get("VOYAGE_API_KEY")),
    reason="only exercises the no-key path; would otherwise construct a real, key-bearing client",
)
def test_voyage_client_raises_without_api_key(monkeypatch):
    monkeypatch.delenv("VOYAGE_API_KEY", raising=False)
    with pytest.raises(EmbeddingNotConfigured):
        VoyageEmbeddingClient()
