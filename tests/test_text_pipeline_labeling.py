"""Stream 6: theme labelling with Claude. FakeClaudeClient only, no network."""
import json

import pytest

from app.text_pipeline import LabelingError, label_clusters, label_sub_clusters
from app.text_pipeline.labeling import (
    AnthropicClaudeClient,
    ClaudeNotConfigured,
    FakeClaudeClient,
    OTHER_CLUSTER_ID,
    OTHER_LABEL,
)
from app.text_pipeline.schema import Cluster, ClusterMember, ClusterResult, ThemeLabel

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


# ---------------------------------------------------------------- label_sub_clusters


def make_parent_label(parent_id):
    return ThemeLabel(
        cluster_id=parent_id,
        label=f"Parent {parent_id}",
        description=f"Description of parent {parent_id}.",
        size=999,
        merge_with=[],
        note=None,
    )


def sub_reply_for(flat_ids, **overrides):
    """Builds a reply keyed by FLAT ids, same shape as reply_for but named distinctly since
    label_sub_clusters' cluster ids are the flat 0..K-1 space, not each sub-cluster's own local id."""
    themes = []
    for fid in flat_ids:
        entry = {"cluster_id": fid, "label": f"Sub {fid}", "description": f"About sub-cluster {fid}.",
                  "merge_with": [], "note": None}
        entry.update(overrides.get(fid, {}))
        themes.append(entry)
    return json.dumps({"themes": themes})


def test_label_sub_clusters_makes_one_call_across_multiple_parents_with_parent_context():
    parent0_subs = [make_cluster(10, ["a", "b", "c"]), make_cluster(11, ["d", "e", "f"])]
    parent1_subs = [make_cluster(20, ["g", "h", "i"]), make_cluster(21, ["j", "k", "l"]),
                     make_cluster(22, ["m", "n", "o"])]
    sub_clusters = {0: parent0_subs, 1: parent1_subs}
    parent_labels = {0: make_parent_label(0), 1: make_parent_label(1)}
    client = FakeClaudeClient(sub_reply_for(range(5)))

    result = label_sub_clusters(sub_clusters, parent_labels, QUESTION, client)

    assert len(client.calls) == 1  # one batched call total, not one per parent

    sent_payload = json.loads(client.calls[0]["prompt"])
    assert sent_payload["survey_question"] == QUESTION
    assert len(sent_payload["clusters"]) == 5  # 2 + 3 sub-clusters, flattened

    # every sub-cluster's request entry carries its OWN parent's label/description
    by_flat_id = {entry["cluster_id"]: entry for entry in sent_payload["clusters"]}
    for fid in (0, 1):  # parent 0's two sub-clusters
        assert by_flat_id[fid]["parent_theme"] == {"label": "Parent 0", "description": "Description of parent 0."}
    for fid in (2, 3, 4):  # parent 1's three sub-clusters
        assert by_flat_id[fid]["parent_theme"] == {"label": "Parent 1", "description": "Description of parent 1."}

    assert set(result.keys()) == {0, 1}
    assert len(result[0]) == 2
    assert len(result[1]) == 3


def test_label_sub_clusters_flat_ids_are_globally_unique_across_parents():
    sub_clusters = {
        100: [make_cluster(0, ["a"]), make_cluster(1, ["b"]), make_cluster(2, ["c"])],
        200: [make_cluster(0, ["d"]), make_cluster(1, ["e"]), make_cluster(2, ["f"])],
        300: [make_cluster(0, ["g"]), make_cluster(1, ["h"]), make_cluster(2, ["i"])],
    }
    parent_labels = {100: make_parent_label(100), 200: make_parent_label(200), 300: make_parent_label(300)}
    client = FakeClaudeClient(sub_reply_for(range(9)))

    result = label_sub_clusters(sub_clusters, parent_labels, QUESTION, client)

    sent_payload = json.loads(client.calls[0]["prompt"])
    sent_ids = [entry["cluster_id"] for entry in sent_payload["clusters"]]
    assert len(sent_ids) == 9
    assert len(set(sent_ids)) == 9  # no collisions despite each parent's sub-clusters starting at local id 0

    all_returned_ids = [label.cluster_id for labels in result.values() for label in labels]
    assert len(all_returned_ids) == len(set(all_returned_ids)) == 9


def test_label_sub_clusters_raises_labeling_error_when_reply_missing_an_id():
    sub_clusters = {0: [make_cluster(0, ["a"]), make_cluster(1, ["b"])]}
    parent_labels = {0: make_parent_label(0)}
    client = FakeClaudeClient(sub_reply_for([0]))  # flat id 1 missing from the reply

    with pytest.raises(LabelingError):
        label_sub_clusters(sub_clusters, parent_labels, QUESTION, client)


def test_label_sub_clusters_sizes_always_come_from_members_never_from_the_reply():
    sub = make_cluster(0, ["a", "b", "c", "d", "e"])  # 5 real members
    sub_clusters = {0: [sub]}
    parent_labels = {0: make_parent_label(0)}
    reply = json.dumps({"themes": [{
        "cluster_id": 0, "label": "X", "description": "Y", "size": 999999, "merge_with": [], "note": None,
    }]})
    client = FakeClaudeClient(reply)

    result = label_sub_clusters(sub_clusters, parent_labels, QUESTION, client)

    assert result[0][0].size == 5


def test_label_sub_clusters_dedupes_identical_sibling_labels_within_one_parent():
    parent0_subs = [make_cluster(0, ["a"]), make_cluster(1, ["b"]), make_cluster(2, ["c"])]
    sub_clusters = {0: parent0_subs}
    parent_labels = {0: make_parent_label(0)}
    # all three siblings come back with the identical label from Claude
    reply = json.dumps({"themes": [
        {"cluster_id": 0, "label": "Same Label", "description": "d0", "merge_with": [], "note": None},
        {"cluster_id": 1, "label": "Same Label", "description": "d1", "merge_with": [], "note": None},
        {"cluster_id": 2, "label": "Same Label", "description": "d2", "merge_with": [], "note": None},
    ]})
    client = FakeClaudeClient(reply)

    result = label_sub_clusters(sub_clusters, parent_labels, QUESTION, client)

    labels = [label.label for label in result[0]]
    assert labels == ["Same Label", "Same Label (2)", "Same Label (3)"]


def test_label_sub_clusters_dedupe_is_scoped_per_parent_not_global():
    sub_clusters = {
        0: [make_cluster(0, ["a"])],
        1: [make_cluster(0, ["b"])],
    }
    parent_labels = {0: make_parent_label(0), 1: make_parent_label(1)}
    reply = json.dumps({"themes": [
        {"cluster_id": 0, "label": "Same Label", "description": "d0", "merge_with": [], "note": None},
        {"cluster_id": 1, "label": "Same Label", "description": "d1", "merge_with": [], "note": None},
    ]})
    client = FakeClaudeClient(reply)

    result = label_sub_clusters(sub_clusters, parent_labels, QUESTION, client)

    # two DIFFERENT parents' sub-clusters getting the same label is not a collision - no " (2)" needed
    assert result[0][0].label == "Same Label"
    assert result[1][0].label == "Same Label"


def test_label_sub_clusters_empty_input_makes_no_calls_and_returns_empty_dict():
    client = FakeClaudeClient("should never be used")

    result = label_sub_clusters({}, {}, QUESTION, client)

    assert result == {}
    assert client.calls == []
