"""Stream 6: theme labelling with Claude. FakeClaudeClient only, no network."""
import json

import pytest

from app.text_pipeline import (
    ClaudeNotConfigured,
    FakeClaudeClient,
    LabelingError,
    label_clusters,
)
from app.text_pipeline.labeling import AnthropicClaudeClient, OTHER_CLUSTER_ID, OTHER_LABEL
from app.text_pipeline.schema import Cluster, ClusterMember, ClusterResult

QUESTION = "What could we do better?"


def make_cluster(cluster_id, texts, distances=None):
    distances = distances or [float(i) for i in range(len(texts))]
    members = [ClusterMember(row=100 * cluster_id + i, text=t, distance=d) for i, (t, d) in enumerate(zip(texts, distances))]
    return Cluster(id=cluster_id, members=members, centroid=[0.0])


def make_result(clusters, noise_texts=()):
    noise = [ClusterMember(row=900 + i, text=t, distance=None) for i, t in enumerate(noise_texts)]
    total = sum(len(c.members) for c in clusters) + len(noise)
    return ClusterResult(column="Why", clusters=clusters, noise=noise, total_answers=total)


def reply_for(cluster_ids, **overrides):
    themes = []
    for cid in cluster_ids:
        entry = {"cluster_id": cid, "label": f"Theme {cid}", "description": f"About cluster {cid}.",
                  "merge_with": [], "note": None}
        entry.update(overrides.get(cid, {}))
        themes.append(entry)
    return json.dumps({"themes": themes})


# ---------------------------------------------------------------- batching


def test_one_batched_call_covers_every_cluster():
    clusters = [make_cluster(0, ["slow shipping", "late delivery", "shipping took forever"]),
                make_cluster(1, ["too expensive", "pricey", "cost too much"]),
                make_cluster(2, ["great support", "helpful staff", "support was great"])]
    result = make_result(clusters)
    client = FakeClaudeClient(reply_for([0, 1, 2]))

    labels = label_clusters(result, QUESTION, client, samples_per_cluster=20)

    assert len(client.calls) == 1  # one call, not one per cluster
    assert [label.cluster_id for label in labels] == [0, 1, 2]
    assert [label.label for label in labels] == ["Theme 0", "Theme 1", "Theme 2"]
    # the survey question reached the prompt
    assert QUESTION in client.calls[0]["prompt"]


def test_no_clusters_and_no_noise_makes_no_call():
    result = make_result([], noise_texts=())
    client = FakeClaudeClient("should never be used")

    labels = label_clusters(result, QUESTION, client)

    assert labels == []
    assert client.calls == []


# ---------------------------------------------------------------- the "Other" group


def test_other_cluster_never_appears_in_the_prompt():
    clusters = [make_cluster(0, ["slow shipping", "late delivery", "shipping took forever"])]
    noise_texts = ["asdkjhaskjdh", "banana truck elephant", "totally unrelated one-off answer"]
    result = make_result(clusters, noise_texts=noise_texts)
    client = FakeClaudeClient(reply_for([0]))

    labels = label_clusters(result, QUESTION, client)

    sent_prompt = client.calls[0]["prompt"]
    for noise_text in noise_texts:
        assert noise_text not in sent_prompt
    sent_payload = json.loads(sent_prompt)
    sent_ids = {c["cluster_id"] for c in sent_payload["clusters"]}
    assert sent_ids == {0}  # only the real cluster, never the noise group

    other = next(label for label in labels if label.cluster_id == OTHER_CLUSTER_ID)
    assert other.label == OTHER_LABEL
    assert other.size == len(noise_texts)


def test_other_label_synthesized_locally_without_noise_it_is_absent():
    clusters = [make_cluster(0, ["slow shipping", "late delivery", "shipping took forever"])]
    result = make_result(clusters, noise_texts=())
    client = FakeClaudeClient(reply_for([0]))

    labels = label_clusters(result, QUESTION, client)

    assert all(label.cluster_id != OTHER_CLUSTER_ID for label in labels)
    assert len(client.calls) == 1


# ---------------------------------------------------------------- size is never trusted from Claude


def test_size_always_comes_from_cluster_members_never_from_the_response():
    clusters = [make_cluster(0, ["a", "b", "c", "d", "e"])]  # 5 real members
    result = make_result(clusters)
    # A malicious/buggy reply claims a "size" field (not part of our schema) and a huge merge_with.
    reply = json.dumps({"themes": [{
        "cluster_id": 0, "label": "X", "description": "Y", "size": 999999, "merge_with": [], "note": None,
    }]})
    client = FakeClaudeClient(reply)

    labels = label_clusters(result, QUESTION, client)

    assert labels[0].size == 5  # from len(cluster.members), not the claimed 999999


def test_merge_with_is_filtered_to_ids_actually_sent_and_never_self():
    clusters = [make_cluster(0, ["a", "b", "c", "d", "e"]),
                make_cluster(1, ["f", "g", "h", "i", "j"])]
    result = make_result(clusters)
    reply = json.dumps({"themes": [
        {"cluster_id": 0, "label": "X", "description": "Y", "merge_with": [0, 1, 999], "note": None},
        {"cluster_id": 1, "label": "Z", "description": "W", "merge_with": [], "note": "maybe two sub-themes"},
    ]})
    client = FakeClaudeClient(reply)

    labels = label_clusters(result, QUESTION, client)

    by_id = {label.cluster_id: label for label in labels}
    assert by_id[0].merge_with == [1]  # self (0) and unknown id (999) dropped
    assert by_id[1].note == "maybe two sub-themes"


# ---------------------------------------------------------------- error handling


def test_malformed_json_raises_labeling_error_cleanly():
    clusters = [make_cluster(0, ["a", "b", "c", "d", "e"])]
    result = make_result(clusters)
    client = FakeClaudeClient("not json at all, sorry")

    with pytest.raises(LabelingError) as exc_info:
        label_clusters(result, QUESTION, client)
    assert exc_info.value.raw_response == "not json at all, sorry"


def test_missing_cluster_in_reply_raises_labeling_error():
    clusters = [make_cluster(0, ["a", "b", "c", "d", "e"]),
                make_cluster(1, ["f", "g", "h", "i", "j"])]
    result = make_result(clusters)
    client = FakeClaudeClient(reply_for([0]))  # cluster 1 missing from the reply

    with pytest.raises(LabelingError):
        label_clusters(result, QUESTION, client)


def test_reply_with_missing_label_field_raises_labeling_error():
    clusters = [make_cluster(0, ["a", "b", "c", "d", "e"])]
    result = make_result(clusters)
    reply = json.dumps({"themes": [{"cluster_id": 0, "description": "Y", "merge_with": [], "note": None}]})
    client = FakeClaudeClient(reply)

    with pytest.raises(LabelingError):
        label_clusters(result, QUESTION, client)


def test_prose_wrapped_json_is_still_parsed():
    clusters = [make_cluster(0, ["a", "b", "c", "d", "e"])]
    result = make_result(clusters)
    reply = "Sure, here you go:\n" + reply_for([0]) + "\nHope that helps!"
    client = FakeClaudeClient(reply)

    labels = label_clusters(result, QUESTION, client)
    assert labels[0].label == "Theme 0"


# ---------------------------------------------------------------- missing API key


def test_missing_api_key_raises_claude_not_configured(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ClaudeNotConfigured):
        AnthropicClaudeClient()


# ---------------------------------------------------------------- sampling


def test_samples_per_cluster_is_respected_and_closest_to_centroid_first():
    texts = [f"answer {i}" for i in range(30)]
    distances = list(range(30))  # answer 0 is closest to the centroid
    cluster = make_cluster(0, texts, distances=distances)
    result = make_result([cluster])
    client = FakeClaudeClient(reply_for([0]))

    label_clusters(result, QUESTION, client, samples_per_cluster=5)

    sent_payload = json.loads(client.calls[0]["prompt"])
    sample_answers = sent_payload["clusters"][0]["sample_answers"]
    assert len(sample_answers) == 5
    assert sample_answers == ["answer 0", "answer 1", "answer 2", "answer 3", "answer 4"]
